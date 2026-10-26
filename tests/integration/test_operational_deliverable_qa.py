"""Operational QA acceptance with real SQLite, DataWorker, DeliverableQA and operator CLI."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import patch

import pytest
from test_runtime_operator_cli import CLI, cli

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.bootstrap.operator import compose_operator
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.qa import SQLiteQAJournal
from agentmine.presentation.operator_cli import run_cli

__all__ = ["cli"]


def execute_data(
    cli: CLI, *, semantic: bool = False, missing: bool = False, invalid_data: bool = False
) -> None:
    manifest = json.loads(cli.manifest.read_text(encoding="utf-8"))
    manifest["acceptance"] = {
        "formats": [{"name": "data.csv", "format": "text/csv"}],
        "requirements": [
            {
                "id": "requirement:name",
                "artifact": "data.csv",
                "kind": "semantic" if semantic else "column",
                "criterion": "Human interpretation required"
                if semantic
                else "absent"
                if missing
                else "name",
            }
        ],
    }
    if invalid_data:
        manifest["max_records"] = 1
        manifest["min_records"] = 1
    cli.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    assert cli.prepare()[0] == 0 and cli.execute()[0] == 0


def qa(cli: CLI, identity: str = "qa-001") -> tuple[int, dict[str, object]]:
    return cli.command(
        "work", "qa", "--execution-id", "cli-exec", "--inspection-id", identity, "--confirm"
    )


def qa_status(cli: CLI) -> dict[str, object]:
    value = cli.command("work", "status", "--execution-id", "cli-exec")[1]["qa"]
    assert isinstance(value, dict)
    return value


def operator_command(cli: CLI, *arguments: str) -> int:
    services = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    return run_cli(
        ["--db", str(cli.world.database.path), "--ledger", "ledger", *arguments],
        services,
        io.StringIO(),
    )


def test_pass_records_evidence_and_requires_separate_operator_review(cli: CLI) -> None:
    execute_data(cli)
    code, report = qa(cli)
    assert code == 0 and report["qa_outcome"] == "PASS"
    assert cli.world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW
    assert cli.world.current().approval is None and cli.world.current().submission is None
    assert cli.world.current().verified_revenue.amount == 0
    status = qa_status(cli)
    retained = status["report"]
    assert isinstance(retained, dict) and retained["outcome"] == "PASS"
    assert status["required_action"] == "OPERATOR_REVIEW_REQUIRED"
    assert (
        operator_command(
            cli,
            "review",
            "--opportunity",
            "op",
            "--review-id",
            "submission-review",
            "--destination",
            "operator:manual-target",
        )
        == 0
    )


@pytest.mark.parametrize("mode", ["missing_requirement", "invalid_data"])
def test_revision_required_preserves_evidence_and_blocks_first_run_replay(
    cli: CLI, mode: str
) -> None:
    execute_data(cli, missing=mode == "missing_requirement", invalid_data=mode == "invalid_data")
    code, report = qa(cli)
    assert code == 0 and report["qa_outcome"] == "NEEDS_REVISION"
    assert cli.world.current().state == OpportunityState.IN_PROGRESS
    assert cli.world.current().deliverable is None and cli.world.current().approval is None
    assert cli.execute()[1]["command_status"] == "BLOCKED"
    assert qa_status(cli)["required_action"] == "F05_REWORK_REQUIRED"
    assert qa(cli)[1]["qa_outcome"] == "NEEDS_REVISION"


def test_semantic_acceptance_remains_human_pending_without_ai(cli: CLI) -> None:
    execute_data(cli, semantic=True)
    code, report = qa(cli)
    assert code == 0 and report["qa_outcome"] == "REQUIRES_HUMAN_REVIEW"
    assert cli.world.current().state == OpportunityState.QA_PENDING
    assert cli.world.current().qa is None
    assert qa_status(cli)["required_action"] == "HUMAN_QA_ACTION_REQUIRED"


def test_missing_approved_acceptance_is_not_guessed(cli: CLI) -> None:
    assert cli.prepare()[0] == 0 and cli.execute()[0] == 0
    assert qa(cli)[0] != 0
    assert cli.world.current().state == OpportunityState.QA_PENDING


@pytest.mark.parametrize("corruption", ["missing_result", "corrupt_result", "content_digest"])
def test_missing_or_corrupt_evidence_never_produces_pass(cli: CLI, corruption: str) -> None:
    execute_data(cli)
    with cli.world.database.transaction(write=True) as connection:
        if corruption == "missing_result":
            connection.execute("DELETE FROM snapshots WHERE kind='data_result'")
        elif corruption == "corrupt_result":
            connection.execute("UPDATE snapshots SET payload='{}' WHERE kind='data_result'")
        else:
            connection.execute("UPDATE snapshots SET payload='{}' WHERE kind='content'")
    assert qa(cli)[0] != 0
    assert cli.world.current().state == OpportunityState.QA_PENDING
    assert SQLiteQAJournal(cli.world.database).get_report(Reference("qa-001")) is None


def test_report_persistence_crash_recovers_original_inspection_without_rechecks(cli: CLI) -> None:
    execute_data(cli)
    original_save = SQLiteQAJournal.save_report

    def save(journal: SQLiteQAJournal, report: object) -> None:
        original_save(journal, report)  # type: ignore[arg-type]
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "qa_report", "Acknowledgement lost")

    with patch.object(SQLiteQAJournal, "save_report", save):
        assert qa(cli)[0] != 0
    assert cli.world.current().state == OpportunityState.QA_PENDING
    retained = SQLiteQAJournal(cli.world.database).get_report(Reference("qa-001"))
    assert retained is not None
    cli.world.database = SQLiteDatabase(cli.world.database.path)
    with patch(
        "agentmine.application.use_cases.deliverable_qa.deterministic",
        side_effect=AssertionError("do not recompute report"),
    ):
        assert qa(cli)[1]["qa_outcome"] == "PASS"
    assert SQLiteQAJournal(cli.world.database).get_report(Reference("qa-001")) == retained


def test_completed_inspection_retry_does_not_rewind_approved_state(cli: CLI) -> None:
    execute_data(cli)
    assert qa(cli)[0] == 0
    # Existing review/decide commands; no second approval workflow.
    assert (
        operator_command(
            cli,
            "review",
            "--opportunity",
            "op",
            "--review-id",
            "review-1",
            "--destination",
            "manual:target",
        )
        == 0
    )
    assert (
        operator_command(
            cli,
            "decide",
            "--review-id",
            "review-1",
            "--decision",
            "APPROVE",
            "--reason",
            "Reviewed test artifacts",
        )
        == 0
    )
    assert cli.world.current().state == OpportunityState.APPROVED_FOR_SUBMISSION
    assert qa(cli)[1]["qa_outcome"] == "PASS"
    assert cli.world.current().state == OpportunityState.APPROVED_FOR_SUBMISSION
    assert cli.world.current().submission is None


def test_different_inspection_id_cannot_replace_first_version_decision(cli: CLI) -> None:
    execute_data(cli)
    assert qa(cli)[0] == 0
    assert qa(cli, "different-id")[0] != 0
    assert SQLiteQAJournal(cli.world.database).get_report(Reference("different-id")) is None


def test_concurrent_qa_attempts_preserve_single_inspection_owner(cli: CLI) -> None:
    execute_data(cli)
    ready = Barrier(2)

    def attempt(identity: str) -> int:
        ready.wait(timeout=10)
        return qa(cli, identity)[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ("qa-a", "qa-b")))
    assert sorted(results) == [0, 1]
    journal = SQLiteQAJournal(cli.world.database)
    reports = [journal.get_report(Reference(value)) for value in ("qa-a", "qa-b")]
    assert sum(report is not None for report in reports) == 1
    assert cli.world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW


def test_stale_revision_after_report_never_rebases_decision(cli: CLI) -> None:
    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    execute_data(cli)
    save_report = SQLiteQAJournal.save_report

    def stale(journal: SQLiteQAJournal, report: object) -> None:
        save_report(journal, report)  # type: ignore[arg-type]
        repository = SQLiteOpportunityRepository(cli.world.database)
        old = repository.get(Reference("op"))
        assert old is not None
        repository.save(OpportunitySave(old.value, old.revision))

    with patch.object(SQLiteQAJournal, "save_report", stale):
        assert qa(cli)[0] == 1
    assert cli.world.current().state == OpportunityState.QA_PENDING
    assert qa(cli)[0] == 1
    assert qa_status(cli)["applied"] is False


@pytest.mark.parametrize("failed_kind", ["qa", "opportunity", "operational_qa_applied"])
def test_qa_completion_rolls_back_all_state_and_recovers(cli: CLI, failed_kind: str) -> None:
    import sqlite3

    from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository

    execute_data(cli)
    original_write = SQLiteDatabase.write

    def write(database: SQLiteDatabase, *args: object, **kwargs: object) -> None:
        original_write(database, *args, **kwargs)  # type: ignore[arg-type]
        if args[1] == failed_kind:
            raise sqlite3.OperationalError("simulated completion failure")

    with patch.object(SQLiteDatabase, "write", write):
        assert qa(cli)[0] != 0
    assert cli.world.current().state == OpportunityState.QA_PENDING
    assert (
        SQLiteExecutionRepository(cli.world.database).get_qa(Reference("cli-deliverable"), 1)
        is None
    )
    assert qa_status(cli)["applied"] is False
    assert SQLiteQAJournal(cli.world.database).get_report(Reference("qa-001")) is not None
    assert qa(cli)[1]["qa_outcome"] == "PASS"


def test_conflicting_inspection_payload_cannot_overwrite_report(cli: CLI) -> None:
    from agentmine.infrastructure.sqlite.operational_qa import SQLiteOperationalQARepository

    execute_data(cli)
    assert qa(cli)[0] == 0
    repository = SQLiteOperationalQARepository(cli.world.database)
    binding = repository.get_binding(Reference("qa-001"))
    inspection = repository.get_inspection(Reference("qa-001"))
    assert binding is not None and inspection is not None
    changed = replace(
        inspection, requirements=(replace(inspection.requirements[0], criterion="different"),)
    )
    with pytest.raises(PortError):
        repository.claim(binding, changed)
    assert qa(cli)[1]["qa_outcome"] == "PASS"


def test_same_id_concurrent_qa_has_one_application_and_no_cost(cli: CLI) -> None:
    from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository

    execute_data(cli)
    ledger = SQLiteCostLedgerRepository(cli.world.database)
    before = ledger.get(Reference("ledger"))
    ready = Barrier(2)

    def attempt() -> int:
        ready.wait(timeout=10)
        return qa(cli)[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result() for future in futures]
        assert 0 in results and all(value in (0, 1) for value in results)
    assert qa(cli)[0] == 0  # A transient competing read retries the same immutable identity.
    assert ledger.get(Reference("ledger")) == before
    assert cli.world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW


def test_source_change_blocks_new_qa_without_mock_or_paid_fallback(cli: CLI) -> None:
    execute_data(cli)
    cli.world.source.requirements = "Changed mandatory requirements"
    with patch(
        "agentmine.infrastructure.llm.bedrock.create_bedrock_client",
        side_effect=AssertionError("no provider"),
    ):
        assert qa(cli)[0] != 0
    assert SQLiteQAJournal(cli.world.database).get_report(Reference("qa-001")) is None


def test_live_report_retry_does_not_run_first_execution_or_refresh(cli: CLI) -> None:
    from fakes import FakeSource

    from agentmine.application.workers.data import DataWorker

    execute_data(cli)
    assert qa(cli)[0] == 0
    with (
        patch.object(DataWorker, "execute", side_effect=AssertionError("no work")),
        patch.object(FakeSource, "refresh", side_effect=AssertionError("historical report only")),
    ):
        assert qa(cli)[1]["qa_outcome"] == "PASS"


def test_acceptance_cannot_be_weakened_after_execution(cli: CLI) -> None:
    execute_data(cli, missing=True)
    manifest = json.loads(cli.manifest.read_text(encoding="utf-8"))
    manifest["acceptance"]["requirements"][0]["criterion"] = "name"
    cli.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    assert cli.prepare()[0] != 0
    assert qa(cli)[1]["qa_outcome"] == "NEEDS_REVISION"


@pytest.mark.parametrize("mismatch", ["result_identity", "execution_identity"])
def test_plan_result_execution_bindings_are_authoritative(cli: CLI, mismatch: str) -> None:
    from agentmine.application.contracts.data import DataResult
    from agentmine.infrastructure.sqlite.database import IndexValues
    from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository

    execute_data(cli)
    if mismatch == "result_identity":
        retained = cli.world.database.get("data_result", "cli-exec", DataResult)
        assert retained is not None
        with cli.world.database.transaction(write=True) as connection:
            cli.world.database.write(
                connection,
                "data_result",
                "cli-exec",
                replace(retained.value, execution_reference=Reference("wrong")),
                retained.revision + 1,
                IndexValues(),
            )
        assert qa(cli)[0] != 0
    else:
        execution = cli.world.current().execution
        assert execution is not None
        with patch.object(
            SQLiteExecutionRepository,
            "get",
            return_value=replace(execution, reference=Reference("wrong")),
        ):
            assert qa(cli)[0] != 0
    assert SQLiteQAJournal(cli.world.database).get_report(Reference("qa-001")) is None


def test_real_qa_engine_detects_coherently_corrupted_values_as_fail(cli: CLI) -> None:
    from agentmine.application.contracts.qa import bundle_content
    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.workers.data_artifacts import artifacts
    from agentmine.domain.opportunity import Opportunity
    from agentmine.domain.work import Deliverable
    from agentmine.infrastructure.sqlite.database import IndexValues, composite_key
    from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    execute_data(
        cli
    )  # A real worker executed first. The following is test-only coherent corruption.
    view = cli.world.runtime().inspect(Reference("cli-exec"))
    assert view is not None and view.result is not None
    records = list(view.result.records)
    cells = list(records[0].cells)
    cells[0] = replace(cells[0], value="Unsupported replacement")
    records[0] = replace(records[0], cells=tuple(cells))
    result = replace(
        view.result, records=tuple(records), artifacts=artifacts(view.run.plan, tuple(records), ())
    )
    content = bundle_content(result)
    deliverable = Deliverable(
        Reference("cli-deliverable"), Reference("cli-exec"), 1, content.reference
    )
    old = view.opportunity_snapshot.value
    assert (
        old.eligibility is not None
        and old.economic_assessment is not None
        and old.scoring_assessment is not None
        and old.task is not None
        and old.execution is not None
    )
    changed = (
        Opportunity(old.reference, old.title, old.potential_reward)
        .normalize()
        .check_eligibility()
        .assess_eligibility(old.eligibility)
        .evaluate(old.economic_assessment)
        .assign_score(old.scoring_assessment)
        .plan(old.task)
        .start(old.execution)
        .finish(deliverable)
    )
    SQLiteExecutionRepository(cli.world.database).save_content(content)
    with cli.world.database.transaction(write=True) as connection:
        cli.world.database.write(connection, "data_result", "cli-exec", result, 1, IndexValues())
        cli.world.database.write(
            connection,
            "deliverable",
            composite_key("cli-deliverable", 1),
            deliverable,
            1,
            IndexValues(),
        )
        cli.world.database.write(
            connection, "runtime_finish", "cli-exec", deliverable, 1, IndexValues()
        )
    SQLiteOpportunityRepository(cli.world.database).save(
        OpportunitySave(changed, view.opportunity_snapshot.revision)
    )
    code, report = qa(cli)
    assert code == 0 and report["qa_outcome"] == "FAIL"
    assert cli.world.current().state == OpportunityState.IN_PROGRESS
    assert cli.execute()[1]["reason"] == "REWORK_REQUIRED"


def test_status_exposes_retained_unapplied_report_as_recovery(cli: CLI) -> None:
    from agentmine.infrastructure.sqlite.operational_qa import SQLiteOperationalQARepository

    execute_data(cli)
    with patch.object(
        SQLiteOperationalQARepository,
        "complete",
        side_effect=PortError(PortErrorCode.OUTCOME_UNKNOWN, "qa_complete", "Unknown completion"),
    ):
        assert qa(cli)[0] != 0
    status = qa_status(cli)
    assert status["applied"] is False and status["report"] is not None
    assert status["required_action"] == "RETRY_SAME_INSPECTION"
    assert cli.world.current().state == OpportunityState.QA_PENDING
