"""C5 continuous offline CLI, independent bytes and crash/restart evidence; no live actions."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from partition_e2e_fakes import FIXTURES, SCENARIOS, Scenario, simulation

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.data import DataResult
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.workers.data import DataWorker
from agentmine.domain.budget import BudgetAuthorization, OperatingMode
from agentmine.domain.money import Money
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAReport
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.qa import SQLiteQAJournal
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_continuous_cli_v2_oracle_and_export(tmp_path: Path, scenario: Scenario) -> None:
    s = simulation(tmp_path, scenario)
    w = s.cli.world
    code, prepared = s.prepare()
    assert code == 0
    assert prepared["output_policy"] == {
        "contract_version": 2,
        "id_column": "id",
        "duplicate_policy": "REJECT_ALL",
    }
    assert prepared["preparation_dispatches_work"] is False
    assert s.command("work", "show", "--spec-id", "cli-spec")[1] == prepared
    assert w.runtime().get_run(Reference("cli-exec")) is None
    code, executed = s.execute()
    assert code == 0 and executed["command_status"] == "COMPLETED"
    view = w.runtime().inspect(Reference("cli-exec"))
    assert view is not None and view.result is not None and view.deliverable is not None
    expected_files = sorted(p.name for p in s.expected.iterdir() if p.suffix in (".csv", ".json"))
    assert sorted(a.name for a in view.result.artifacts) == expected_files
    for a in view.result.artifacts:
        assert a.content.encode("utf-8") == (s.expected / a.name).read_bytes()
    assert w.current().state == OpportunityState.QA_PENDING
    ledger = w.budget().ledger.get(Reference("ledger"))
    assert ledger is not None
    assert ledger.value.requested_mode == OperatingMode.SCOUT_ONLY
    assert (
        ledger.value.policy.monthly_ai_budget.amount
        == ledger.value.policy.daily_ai_budget.amount
        == 0
    )
    assert len(ledger.value.records) == 1 and ledger.value.records[0].actual_cost.amount == 0
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no redispatch")):
        assert s.execute()[0] == 0
    code, report = s.qa()
    assert code == 0 and report["qa_outcome"] == scenario["outcome"]
    assert w.current().state == (
        OpportunityState.READY_FOR_HUMAN_REVIEW
        if scenario["outcome"] == "PASS"
        else OpportunityState.IN_PROGRESS
    )
    w.database = SQLiteDatabase(w.database.path)
    assert s.qa()[1] == report
    assert s.command("work", "status", "--execution-id", "cli-exec")[0] == 0
    code, exported = s.export()
    assert code == 0 and exported["external_submission"] is False
    assert sorted(p.name for p in s.cli.export.iterdir()) == sorted(
        [*expected_files, "manifest.json"]
    )
    for name in expected_files:
        assert (s.cli.export / name).read_bytes() == (s.expected / name).read_bytes()
    manifest = json.loads((s.cli.export / "manifest.json").read_text())
    assert manifest["contract_version"] == 2
    assert (
        manifest["evidence_complete"] == view.result.partition.evidence_complete
        if view.result.partition is not None
        else False
    )
    assert manifest["content_reference"] == view.deliverable.content_reference.value
    assert s.export()[0] == 0
    assert w.budget().ledger.get(Reference("ledger")) == ledger
    assert (
        w.current().approval is None
        and w.current().submission is None
        and w.current().verified_revenue.amount == 0
    )
    s.save_transcript(tmp_path / "cli-transcript.json")


def test_legacy_default_bytes_and_export_unchanged(tmp_path: Path) -> None:
    s = simulation(tmp_path, next(c for c in SCENARIOS if c["name"] == "b41-complete"))
    manifest = json.loads(s.cli.manifest.read_text())
    manifest.pop("output_policy")
    acceptance = manifest["acceptance"]
    acceptance.pop("partition_acceptance")
    acceptance["formats"] = [f for f in acceptance["formats"] if f["name"] != "rejected.json"]
    for f in acceptance["formats"]:
        f["name"] = f["name"].replace("clean.", "data.")
    for r in acceptance["requirements"]:
        r["artifact"] = "data.json"
        r["kind"] = "column"
    s.cli.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    assert s.prepare()[0] == 0 and s.execute()[0] == 0 and s.qa()[1]["qa_outcome"] == "PASS"
    assert s.export()[0] == 0
    for name in ("data.csv", "data.json", "validation.json"):
        assert (s.cli.export / name).read_bytes() == (
            FIXTURES / "legacy-complete" / name
        ).read_bytes()
    assert "contract_version" not in json.loads((s.cli.export / "manifest.json").read_text())


def test_independent_fixture_hashes() -> None:
    for name, digest in json.loads((FIXTURES / "sha256.json").read_text()).items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "damage",
    [
        "no_acceptance",
        "no_thresholds",
        "implicit_threshold",
        "unsupported_policy",
        "unknown_version",
        "bool_version",
        "unknown_policy_field",
        "normalization_override",
        "missing_id",
        "unknown_top",
        "semantic",
        "v2_names_only",
    ],
)
def test_cli_requires_complete_explicit_v2(tmp_path: Path, damage: str) -> None:
    s = simulation(tmp_path, SCENARIOS[0])
    m = json.loads(s.cli.manifest.read_text())
    if damage == "no_acceptance":
        m.pop("acceptance")
    elif damage == "no_thresholds":
        m["acceptance"].pop("partition_acceptance")
    elif damage == "implicit_threshold":
        m["acceptance"]["partition_acceptance"].pop("max_rejected_records")
    elif damage == "unsupported_policy":
        m["output_policy"]["duplicate_policy"] = "FIRST_WINS"
    elif damage == "unknown_version":
        m["output_policy"]["contract_version"] = 3
    elif damage == "bool_version":
        m["output_policy"]["contract_version"] = True
    elif damage == "unknown_policy_field":
        m["output_policy"]["anything"] = True
    elif damage == "normalization_override":
        m["output_policy"]["normalization"] = "guess"
    elif damage == "missing_id":
        m["output_policy"].pop("id_column")
    elif damage == "unknown_top":
        m["contract_version"] = 2
    elif damage == "semantic":
        m["columns"][1]["semantic_reason"] = "Use AI"
    else:
        m.pop("output_policy")
    s.cli.manifest.write_text(json.dumps(m), encoding="utf-8")
    assert s.prepare()[0] != 0
    assert s.cli.world.runtime().get_specification(Reference("cli-spec")) is None
    assert s.cli.world.runtime().get_run(Reference("cli-exec")) is None


@pytest.mark.parametrize("damage", ["threshold", "schema", "source_bytes"])
def test_same_specification_cannot_change_approved_scope(tmp_path: Path, damage: str) -> None:
    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0
    original = s.cli.world.runtime().get_specification(Reference("cli-spec"))
    assert original is not None
    m = json.loads(s.cli.manifest.read_text())
    if damage == "threshold":
        m["acceptance"]["partition_acceptance"]["max_rejected_records"] = 0
    elif damage == "schema":
        m["columns"][0]["case"] = "lower"
    else:
        (s.cli.root / m["sources"][0]["path"]).write_text("[]", encoding="utf-8")
        m["sources"][0]["sha256"] = hashlib.sha256(b"[]").hexdigest()
    s.cli.manifest.write_text(json.dumps(m), encoding="utf-8")
    assert s.prepare()[0] != 0
    assert s.cli.world.runtime().get_specification(Reference("cli-spec")) == original
    assert s.cli.world.runtime().get_run(Reference("cli-exec")) is None


@pytest.mark.parametrize(
    "problem", ["missing_input", "digest", "source_unavailable", "terms", "deadline", "ineligible"]
)
def test_missing_or_stale_authority_cannot_dispatch(tmp_path: Path, problem: str) -> None:
    s = simulation(tmp_path, SCENARIOS[0])
    m = json.loads(s.cli.manifest.read_text())
    if problem == "missing_input":
        (s.cli.root / m["sources"][0]["path"]).unlink()
        assert s.prepare()[0] != 0
        return
    if problem == "digest":
        (s.cli.root / m["sources"][0]["path"]).write_text("[]", encoding="utf-8")
        assert s.prepare()[0] != 0
        return
    assert s.prepare()[0] == 0
    if problem == "terms":
        s.cli.world.source.terms_reference = Reference("changed")
    elif problem == "deadline":
        s.cli.world.source.deadline = s.cli.world.clock.now()
    elif problem == "ineligible":
        s.cli.world.source.is_open = False
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no worker")):
        if problem == "source_unavailable":
            with patch.object(
                type(s.cli.world.source),
                "refresh",
                side_effect=PortError(PortErrorCode.UNAVAILABLE, "test", "offline"),
            ):
                code, data = s.execute()
        else:
            code, data = s.execute()
    assert code != 0 and data["command_status"] == "BLOCKED"
    assert s.cli.world.runtime().get_run(Reference("cli-exec")) is None


@pytest.mark.parametrize(
    "stage",
    ["before_result", "after_result", "before_cost", "after_cost", "before_finish", "after_finish"],
)
def test_cli_crash_recovery_uses_original_identity(tmp_path: Path, stage: str) -> None:
    from datetime import datetime

    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0
    original_save = SQLiteDataJournal.save_result
    original_record = BudgetManager.record
    original_finish = SQLiteWorkerRuntimeRepository.finish

    def save(journal: SQLiteDataJournal, result: DataResult) -> None:
        if stage == "after_result":
            original_save(journal, result)
        raise PortError(PortErrorCode.UNAVAILABLE, "test", "result write acknowledgement")

    def record(
        manager: BudgetManager, auth: BudgetAuthorization, actual: Money, at: datetime
    ) -> CostRecord:
        assert SQLiteDataJournal(s.cli.world.database).get_result(Reference("cli-exec")) is not None
        if stage == "after_cost":
            original_record(manager, auth, actual, at)
        raise PortError(PortErrorCode.UNAVAILABLE, "test", "cost write acknowledgement")

    from agentmine.application.contracts.runtime import WorkerRunFinish

    def finish(repo: SQLiteWorkerRuntimeRepository, command: WorkerRunFinish) -> bool:
        if stage == "after_finish":
            original_finish(repo, command)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "test", "finish acknowledgement")

    if stage in ("before_result", "after_result"):
        with patch.object(SQLiteDataJournal, "save_result", save):
            assert s.execute()[0] != 0
    elif stage in ("before_cost", "after_cost"):
        with patch.object(BudgetManager, "record", record):
            assert s.execute()[0] != 0
    else:
        with patch.object(SQLiteWorkerRuntimeRepository, "finish", finish):
            assert s.execute()[0] != 0
    before = s.cli.world.runtime().get_run(Reference("cli-exec"))
    assert before is not None
    s.cli.world.database = SQLiteDatabase(s.cli.world.database.path)
    assert s.command("work", "recover", "--execution-id", "cli-exec", "--confirm")[0] == 0
    assert s.cli.world.runtime().get_run(Reference("cli-exec")) == before
    ledger = s.cli.world.budget().ledger.get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.records) == 1
    assert s.qa()[1]["qa_outcome"] == "PASS" and s.export()[0] == 0


@pytest.mark.parametrize(
    "damage", ["missing", "extra", "bytes", "conflicting_destination", "traversal", "unrelated"]
)
def test_v2_export_is_exact_and_no_clobber(tmp_path: Path, damage: str) -> None:
    from agentmine.application.contracts.data import DataArtifact

    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0 and s.execute()[0] == 0
    view = s.cli.world.runtime().inspect(Reference("cli-exec"))
    assert view is not None and view.result is not None
    if damage in ("missing", "extra", "bytes", "traversal"):
        artifacts = view.result.artifacts
        if damage == "missing":
            artifacts = artifacts[:-1]
        elif damage == "extra":
            artifacts = (*artifacts, DataArtifact("extra.json", "application/json", "{}"))
        elif damage == "traversal":
            artifacts = (replace(artifacts[0], name="../escape.csv"), *artifacts[1:])
        else:
            artifacts = (replace(artifacts[0], content="tampered"), *artifacts[1:])
        bad = replace(view.result, artifacts=artifacts)
        # Explicit test-only hostile reader; never rewrite authoritative SQLite history.
        from agentmine.application.use_cases.data_history import LocalDataHistory

        with patch.object(LocalDataHistory, "inspect", return_value=replace(view, result=bad)):
            assert s.export()[0] != 0
    else:
        s.cli.export.mkdir()
        file = s.cli.export / (
            "clean.json" if damage == "conflicting_destination" else "unrelated.txt"
        )
        file.write_text("keep", encoding="utf-8")
        assert s.export()[0] != 0 and file.read_text() == "keep"
    assert not (tmp_path / "escape.csv").exists()


def test_cli_qa_crash_and_altered_inspection_do_not_rebase(tmp_path: Path) -> None:
    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0 and s.execute()[0] == 0
    original = SQLiteQAJournal.save_report

    def crash(journal: SQLiteQAJournal, report: QAReport) -> None:
        original(journal, report)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "test", "lost ack")

    with patch.object(SQLiteQAJournal, "save_report", crash):
        assert s.qa()[0] != 0
    assert s.cli.world.current().state == OpportunityState.QA_PENDING
    s.cli.world.database = SQLiteDatabase(s.cli.world.database.path)
    assert s.qa()[1]["qa_outcome"] == "PASS"
    from agentmine.infrastructure.sqlite.operational_qa import SQLiteOperationalQARepository

    repo = SQLiteOperationalQARepository(s.cli.world.database)
    inspection = repo.get_inspection(Reference("cli-qa"))
    assert inspection is not None
    altered = replace(inspection)
    object.__setattr__(altered, "partition_acceptance", None)
    with patch.object(SQLiteOperationalQARepository, "get_inspection", return_value=altered):
        assert s.qa()[0] != 0
    assert s.cli.world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW


@pytest.mark.parametrize("damage", ["no_policy", "wrong_completeness", "missing_deliverable"])
def test_export_adapter_never_infers_v2_from_names(tmp_path: Path, damage: str) -> None:
    from agentmine.infrastructure.local_artifact_export import LocalArtifactExporter

    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0 and s.execute()[0] == 0
    view = s.cli.world.runtime().inspect(Reference("cli-exec"))
    assert view is not None and view.result is not None and view.deliverable is not None
    exporter = LocalArtifactExporter(s.cli.export)
    with pytest.raises(PortError):
        exporter.export(
            Reference("cli-exec"),
            view.deliverable.content_reference,
            view.result.artifacts,
            deliverable=None if damage == "missing_deliverable" else view.deliverable,
            output_policy=None if damage == "no_policy" else view.run.specification.output_policy,
            evidence_complete=None if damage == "no_policy" else False,
        )


@pytest.mark.parametrize("kind", ["content", "deliverable", "opportunity", "runtime_finish"])
def test_cli_atomic_finish_partial_writes_roll_back_and_recover(tmp_path: Path, kind: str) -> None:
    import sqlite3

    from agentmine.application.contracts.runtime import WorkerRunFinish
    from agentmine.infrastructure.sqlite.database import IndexValues

    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0
    original_finish = SQLiteWorkerRuntimeRepository.finish
    original_write = SQLiteDatabase.write

    def write(
        db: SQLiteDatabase,
        connection: sqlite3.Connection,
        write_kind: str,
        key: str,
        value: object,
        revision: int,
        indexes: IndexValues,
    ) -> None:
        original_write(db, connection, write_kind, key, value, revision, indexes)
        if write_kind == kind:
            raise PortError(PortErrorCode.UNAVAILABLE, "test", "after atomic write")

    def finish(repo: SQLiteWorkerRuntimeRepository, command: WorkerRunFinish) -> bool:
        with patch.object(SQLiteDatabase, "write", write):
            return original_finish(repo, command)

    with patch.object(SQLiteWorkerRuntimeRepository, "finish", finish):
        assert s.execute()[0] != 0
    view = s.cli.world.runtime().inspect(Reference("cli-exec"))
    assert view is not None and view.result is not None and not view.finished
    assert view.deliverable is None and s.cli.world.current().state == OpportunityState.IN_PROGRESS
    ledger = s.cli.world.budget().ledger.get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.records) == 1
    s.cli.world.database = SQLiteDatabase(s.cli.world.database.path)
    with patch.object(
        DataWorker, "execute", side_effect=AssertionError("no redispatch after durable result")
    ):
        assert s.command("work", "recover", "--execution-id", "cli-exec", "--confirm")[0] == 0
    assert s.cli.world.budget().ledger.get(Reference("ledger")) == ledger
    assert s.qa()[1]["qa_outcome"] == "PASS" and s.export()[0] == 0


def test_unknown_ai_claim_blocks_without_authorization_or_fake_zero(tmp_path: Path) -> None:
    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0
    ledger = s.cli.world.budget().ledger.get(Reference("ledger"))
    # Explicit test-only durable ambiguous claim, no provider or positive cost is invented.
    s.cli.world.database.immutable("data_ai_claim", "cli-op", Reference("test-only-unknown-claim"))
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no worker")):
        code, data = s.execute()
    assert code != 0 and data["reason"] == "EXTERNAL_OUTCOME_UNKNOWN"
    assert s.cli.world.budget().ledger.get(Reference("ledger")) == ledger
    assert s.cli.world.runtime().get_run(Reference("cli-exec")) is None


@pytest.mark.parametrize("which", ["prepare", "execute"])
def test_cli_explicit_operator_intent_is_required(tmp_path: Path, which: str) -> None:
    s = simulation(tmp_path, SCENARIOS[0])
    if which == "prepare":
        c = s.cli
        result = s.command(
            "work",
            "prepare",
            "--opportunity",
            "op",
            "--spec-id",
            "cli-spec",
            "--inputs",
            str(c.manifest),
            "--input-root",
            str(c.root),
            "--facts",
            str(c.facts),
            "--minimum-time-seconds",
            "3600",
            "--evaluation",
            "evaluation",
        )
    else:
        assert s.prepare()[0] == 0
        result = s.command(
            "work",
            "execute",
            "--spec-id",
            "cli-spec",
            "--execution-id",
            "cli-exec",
            "--operation-id",
            "cli-op",
            "--deliverable-id",
            "cli-deliverable",
            "--expected-revision",
            str(s.cli.world.request.expected_opportunity_revision),
        )
    assert result[0] != 0
    assert s.cli.world.runtime().get_run(Reference("cli-exec")) is None


@pytest.mark.parametrize("changed", ["threshold", "source"])
def test_completed_run_cannot_replay_under_changed_frozen_spec(
    tmp_path: Path, changed: str
) -> None:
    from agentmine.application.contracts.data import PartitionAcceptance
    from agentmine.application.contracts.runtime import InputEvidence

    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0 and s.execute()[0] == 0
    run = s.cli.world.runtime().get_run(Reference("cli-exec"))
    assert run is not None and run.specification.acceptance is not None
    original = run.specification
    assert original.acceptance is not None
    if changed == "threshold":
        altered = replace(
            original,
            acceptance=replace(
                original.acceptance, partition_acceptance=PartitionAcceptance(2, 1, 0)
            ),
        )
    else:
        sources = (replace(original.sources[0], content="[]"),)
        altered = replace(
            original,
            sources=sources,
            input_evidence=tuple(
                InputEvidence(x.reference, Reference("sha256:" + x.digest)) for x in sources
            ),
        )
    ledger = s.cli.world.budget().ledger.get(Reference("ledger"))
    with (
        patch.object(SQLiteWorkerRuntimeRepository, "get_specification", return_value=altered),
        patch.object(DataWorker, "execute", side_effect=AssertionError("no replay")),
    ):
        code, data = s.execute()
    assert code != 0 and data["reason"] == "IDENTITY_CONFLICT"
    assert s.cli.world.budget().ledger.get(Reference("ledger")) == ledger


def test_conflicting_operation_id_and_content_digest_fail_closed(tmp_path: Path) -> None:
    s = simulation(tmp_path, SCENARIOS[0])
    assert s.prepare()[0] == 0 and s.execute()[0] == 0
    code, data = s.command(
        "work",
        "execute",
        "--spec-id",
        "cli-spec",
        "--execution-id",
        "cli-exec",
        "--operation-id",
        "other-op",
        "--deliverable-id",
        "cli-deliverable",
        "--expected-revision",
        str(s.cli.world.request.expected_opportunity_revision),
        "--confirm",
    )
    assert code != 0 and data["reason"] == "IDENTITY_CONFLICT"
    view = s.cli.world.runtime().inspect(Reference("cli-exec"))
    assert view is not None and view.deliverable is not None
    from agentmine.application.use_cases.data_history import LocalDataHistory

    with patch.object(
        LocalDataHistory,
        "inspect",
        return_value=replace(
            view,
            deliverable=replace(
                view.deliverable, content_reference=Reference("sha256:" + "0" * 64)
            ),
        ),
    ):
        assert s.export()[0] != 0


def test_explicit_v2_revision_reuses_existing_consent_and_qa_path(tmp_path: Path) -> None:
    from datetime import timedelta

    from test_revision_operator_qa import approve, execute, prepare

    s = simulation(tmp_path, next(x for x in SCENARIOS if x["name"] == "mixed-denied"))
    assert (
        s.prepare()[0] == 0 and s.execute()[0] == 0 and s.qa()[1]["qa_outcome"] == "NEEDS_REVISION"
    )
    original = SQLiteDataJournal(s.cli.world.database).get_result(Reference("cli-exec"))
    manifest = json.loads(s.cli.manifest.read_text())
    raw = b'[{"id":"a1","qty":"1"},{"id":"b2","qty":"2"}]'
    (s.cli.root / manifest["sources"][0]["path"]).write_bytes(raw)
    manifest["sources"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    s.cli.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    s.cli.world.clock.instant += timedelta(seconds=1)
    assert prepare(s.cli, trigger_id="cli-qa")[0] == 0
    # Proposal cannot dispatch before its own explicit approval.
    assert execute(s.cli)[0] != 0
    assert approve(s.cli)[0] == 0
    assert execute(s.cli)[0] == 0
    code, report = s.command(
        "work",
        "qa",
        "--execution-id",
        "revision-2-exec",
        "--inspection-id",
        "revision-2-qa",
        "--confirm",
    )
    assert code == 0 and report["qa_outcome"] == "PASS"
    assert s.cli.world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW
    assert (
        s.command(
            "work", "export", "--execution-id", "revision-2-exec", "--directory", str(s.cli.export)
        )[0]
        == 0
    )
    exported = json.loads((s.cli.export / "manifest.json").read_text())
    assert exported["contract_version"] == 2 and exported["deliverable"]["version"] == 2
    assert SQLiteDataJournal(s.cli.world.database).get_result(Reference("cli-exec")) == original
    assert s.qa()[1]["qa_outcome"] == "NEEDS_REVISION"
    assert s.cli.world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW
    assert s.cli.world.current().approval is None and s.cli.world.current().submission is None
    assert s.cli.world.current().verified_revenue.amount == 0
