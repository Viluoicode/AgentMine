"""Operator CLI with real SQLite/DataWorker and explicitly injected offline source."""

import io
import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from test_worker_execution_runtime import World, build_world

from agentmine.bootstrap.operator import compose_operator, main
from agentmine.domain.values import Reference
from agentmine.presentation.operator_cli import run_cli


@dataclass
class CLI:
    world: World
    root: Path
    manifest: Path
    facts: Path
    export: Path

    def command(self, *arguments: str) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        services = compose_operator(
            self.world.database.path,
            self.world.specification.ledger_reference,
            self.world.specification.actor,
            self.world.clock,
            self.world.source,
            input_root=self.root,
            export_directory=self.export,
        )
        code = run_cli(
            ["--db", str(self.world.database.path), "--ledger", "ledger", *arguments],
            services,
            output,
        )
        return code, json.loads(output.getvalue())

    def prepare(self) -> tuple[int, dict[str, object]]:
        return self.command(
            "work",
            "prepare",
            "--opportunity",
            "op",
            "--spec-id",
            "cli-spec",
            "--inputs",
            str(self.manifest),
            "--input-root",
            str(self.root),
            "--facts",
            str(self.facts),
            "--minimum-time-seconds",
            "3600",
            "--evaluation",
            "evaluation",
            "--approve-inputs",
        )

    def execute(self) -> tuple[int, dict[str, object]]:
        return self.command(
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
            str(self.world.request.expected_opportunity_revision),
            "--confirm",
        )


@pytest.fixture
def cli(tmp_path: Path) -> CLI:
    world = build_world(tmp_path)
    root = tmp_path / "inputs"
    root.mkdir()
    source = world.specification.sources[0]
    (root / "input.json").write_bytes(source.content.encode("utf-8"))
    manifest = tmp_path / "spec.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "local-input",
                        "path": "input.json",
                        "sha256": source.digest,
                        "format": "json",
                        "locator": "operator:approved-data",
                        "collected_at": source.collected_at.isoformat(),
                    }
                ],
                "columns": [{"name": "name", "path": ["name"]}],
                "min_records": 2,
                "max_records": 2,
            }
        ),
        encoding="utf-8",
    )
    facts = tmp_path / "facts.json"
    facts.write_text(
        json.dumps(
            {
                "facts": {
                    "ai_policy": "allowed",
                    "geography": {"allowed": [], "excluded": []},
                    "account": "not_required",
                    "identity": "not_required",
                    "physical_presence": "not_required",
                    "task_type": "data_processing",
                    "required_skills": [],
                    "submission": "automatic",
                    "payment": {"upfront_fee": False, "secret_credentials": False},
                    "prohibited_actions": [],
                },
                "profile": {},
            }
        ),
        encoding="utf-8",
    )
    return CLI(world, root, manifest, facts, tmp_path / "export")


def test_prepare_inspect_execute_status_and_export(cli: CLI) -> None:
    code, data = cli.prepare()
    assert code == 0 and data["specification_id"] == "cli-spec"
    assert cli.command("work", "show", "--spec-id", "cli-spec")[0] == 0
    assert (
        cli.command("opportunity", "show", "--opportunity", "op")[1]["opportunity_state"]
        == "PLANNED"
    )
    code, data = cli.execute()
    assert code == 0 and data["command_status"] == "COMPLETED"
    assert data["opportunity_state"] == "QA_PENDING"
    code, status = cli.command("work", "status", "--execution-id", "cli-exec")
    assert code == 0 and status["execution_history_completed"] is True
    code, exported = cli.command(
        "work", "export", "--execution-id", "cli-exec", "--directory", str(cli.export)
    )
    assert code == 0 and exported["external_submission"] is False
    assert (cli.export / "data.json").is_file() and (cli.export / "manifest.json").is_file()
    assert (
        cli.command("work", "export", "--execution-id", "cli-exec", "--directory", str(cli.export))[
            0
        ]
        == 0
    )


@pytest.mark.parametrize("case", ["missing", "tampered", "traversal", "semantic", "unknown-field"])
def test_invalid_local_input_cannot_prepare(cli: CLI, case: str) -> None:
    manifest = json.loads(cli.manifest.read_text(encoding="utf-8"))
    if case == "missing":
        (cli.root / "input.json").unlink()
    elif case == "tampered":
        (cli.root / "input.json").write_text('[{"name":"changed"}]', encoding="utf-8")
    elif case == "traversal":
        manifest["sources"][0]["path"] = "../facts.json"
    elif case == "semantic":
        manifest["columns"][0]["semantic_reason"] = "Use AI"
    else:
        manifest["authorization"] = True
    cli.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    code, data = cli.prepare()
    assert code != 0 and data["status"] == "failed"
    assert cli.world.runtime().get_specification(Reference("cli-spec")) is None


def test_unavailable_source_no_fallback(cli: CLI) -> None:
    from fakes import FakeSource

    from agentmine.application.errors import PortError, PortErrorCode

    with patch.object(
        FakeSource,
        "refresh",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "source", "Unavailable"),
    ):
        assert cli.prepare()[0] != 0


def test_editing_file_after_approval_does_not_edit_frozen_input(cli: CLI) -> None:
    assert cli.prepare()[0] == 0
    (cli.root / "input.json").write_text("changed", encoding="utf-8")
    assert cli.prepare()[0] != 0
    assert cli.execute()[0] == 0


def test_recovery_reopens_same_ids_without_recomputation(cli: CLI) -> None:
    from agentmine.application.errors import PortError, PortErrorCode
    from agentmine.application.workers.data import DataWorker
    from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository

    assert cli.prepare()[0] == 0
    with patch.object(
        SQLiteWorkerRuntimeRepository,
        "finish",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "finish", "Failure"),
    ):
        assert cli.execute()[1]["command_status"] == "RECOVERABLE"
    with patch.object(
        DataWorker, "execute", side_effect=AssertionError("must reuse existing result")
    ):
        code, data = cli.command("work", "recover", "--execution-id", "cli-exec", "--confirm")
    assert code == 0 and data["opportunity_state"] == "QA_PENDING"
    assert cli.execute()[1]["command_status"] == "COMPLETED"
    assert cli.world.current().submission is None and cli.world.current().payment is None


def test_missing_actor_and_unconfirmed_intent_fail_before_work(
    cli: CLI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENTMINE_OPERATOR_ID", raising=False)
    assert (
        main(
            [
                "--db",
                str(cli.world.database.path),
                "--ledger",
                "ledger",
                "work",
                "recover",
                "--execution-id",
                "cli-exec",
                "--confirm",
            ]
        )
        == 2
    )
    assert (
        cli.command(
            "work",
            "execute",
            "--spec-id",
            "missing",
            "--execution-id",
            "e",
            "--operation-id",
            "o",
            "--deliverable-id",
            "d",
            "--expected-revision",
            "1",
        )[0]
        != 0
    )


def normalized_workspace(cli: CLI) -> None:
    from test_worker_execution_runtime import usd

    from agentmine.application.contracts.opportunities import DiscoveryRequest
    from agentmine.application.contracts.records import BudgetCommit
    from agentmine.application.use_cases.planning import DiscoverOpportunities, NormalizeOpportunity
    from agentmine.domain.budget import Budget, BudgetPolicy
    from agentmine.infrastructure.sqlite.database import SQLiteDatabase
    from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    # A separate fresh workspace; never rewind or reset an existing lifecycle.
    database = SQLiteDatabase(cli.root.parent / "fresh-cli.sqlite3")
    opportunities = SQLiteOpportunityRepository(database)
    budget = Budget(BudgetPolicy(usd("10"), usd("5"), usd("3"), usd("1")))
    SQLiteCostLedgerRepository(database).commit(
        BudgetCommit(Reference("ledger"), budget, None, None)
    )
    DiscoverOpportunities(cli.world.source, opportunities, cli.world.clock).execute(
        DiscoveryRequest(1)
    )
    NormalizeOpportunity(opportunities).execute(Reference("op"))
    cli.world.database = database


def test_existing_eligibility_economics_score_and_plan_are_usable_from_cli(cli: CLI) -> None:
    from dataclasses import replace

    normalized_workspace(cli)
    assert (
        cli.command(
            "opportunity",
            "eligibility",
            "--opportunity",
            "op",
            "--facts",
            str(cli.facts),
            "--minimum-time-seconds",
            "3600",
        )[1]["opportunity_state"]
        == "ELIGIBLE"
    )
    economics = cli.root.parent / "economic.json"
    economics.write_text(
        json.dumps(
            {
                "currency": "USD",
                "predicted_success_probability": {
                    "value": "0.5",
                    "rationale": "Explicit subjective operator test estimate",
                },
                "estimated_cost": {
                    "ai": "0",
                    "tool": "0",
                    "infrastructure": "0",
                    "transaction": "0",
                },
                "cost_rationale": "Offline test assumptions, not actual billing",
            }
        ),
        encoding="utf-8",
    )
    code, data = cli.command(
        "opportunity", "evaluate", "--opportunity", "op", "--inputs", str(economics)
    )
    assert code == 0 and data["opportunity_state"] == "EVALUATED"
    scoring = cli.root.parent / "scoring.json"
    scoring.write_text(
        json.dumps(
            {
                "policy": {
                    "version": "operator-v1",
                    "net_value_target": "10",
                    "currency": "USD",
                    "rationale": "Explicit test target",
                },
                "signals": {
                    name: {"value": "0.5", "rationale": "Subjective test signal"}
                    for name in (
                        "risk",
                        "competition",
                        "deadline",
                        "ai_suitability",
                        "historical_performance",
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    assert (
        cli.command(
            "opportunity",
            "score",
            "--opportunity",
            "op",
            "--evaluation",
            "evaluation",
            "--inputs",
            str(scoring),
        )[1]["opportunity_state"]
        == "SCORED"
    )
    code, data = cli.command(
        "opportunity",
        "plan",
        "--opportunity",
        "op",
        "--task",
        "task",
        "--description",
        "Normalize supplied names",
    )
    assert code == 0 and data["opportunity_state"] == "PLANNED"
    cli.world.request = replace(
        cli.world.request, expected_opportunity_revision=int(str(data["opportunity_revision"]))
    )
    assert cli.prepare()[0] == 0
    assert cli.execute()[0] == 0


@pytest.mark.parametrize(
    "reason", ["ineligible", "expired", "missing-economics", "missing-input-approval"]
)
def test_business_boundaries_do_not_create_fake_evidence(cli: CLI, reason: str) -> None:
    if reason == "expired":
        from datetime import timedelta

        cli.world.clock.instant += timedelta(days=3)
    elif reason == "ineligible":
        data = json.loads(cli.facts.read_text(encoding="utf-8"))
        data["facts"]["ai_policy"] = "prohibited"
        cli.facts.write_text(json.dumps(data), encoding="utf-8")
    elif reason == "missing-economics":
        from agentmine.infrastructure.sqlite.evaluations import SQLiteEvaluationRepository

        with patch.object(SQLiteEvaluationRepository, "get", return_value=None):
            assert cli.prepare()[0] != 0
        return
    else:
        code, data = cli.command(
            "work",
            "prepare",
            "--opportunity",
            "op",
            "--spec-id",
            "cli-spec",
            "--inputs",
            str(cli.manifest),
            "--input-root",
            str(cli.root),
            "--facts",
            str(cli.facts),
            "--minimum-time-seconds",
            "3600",
            "--evaluation",
            "evaluation",
        )
        assert code != 0 and data["code"] == "unsupported"
        return
    assert cli.prepare()[0] != 0
    assert cli.world.current().state.name == "PLANNED"


def test_export_conflict_does_not_overwrite_or_submit(cli: CLI) -> None:
    assert cli.prepare()[0] == 0 and cli.execute()[0] == 0
    cli.export.mkdir()
    (cli.export / "data.json").write_bytes(b"operator file")
    assert (
        cli.command("work", "export", "--execution-id", "cli-exec", "--directory", str(cli.export))[
            0
        ]
        != 0
    )
    assert (cli.export / "data.json").read_bytes() == b"operator file"
    assert not (cli.export / "manifest.json").exists()
    assert cli.world.current().submission is None


def test_no_mock_or_paid_provider_fallback(cli: CLI) -> None:
    from agentmine.infrastructure.llm.mock import MockLLMProvider

    with (
        patch.object(MockLLMProvider, "__init__", side_effect=AssertionError("no mock fallback")),
        patch(
            "agentmine.infrastructure.llm.bedrock.create_bedrock_client",
            side_effect=AssertionError("no paid provider"),
        ),
    ):
        assert cli.prepare()[0] == 0 and cli.execute()[0] == 0


def test_real_entrypoint_has_disabled_source_by_default(
    cli: CLI, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AGENTMINE_OPERATOR_ID", "operator")
    assert cli.prepare()[0] == 0
    arguments = [
        "--db",
        str(cli.world.database.path),
        "--ledger",
        "ledger",
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
        str(cli.world.request.expected_opportunity_revision),
        "--confirm",
    ]
    assert main(arguments) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["command_status"] == "BLOCKED" and data["reason"] == "SOURCE_UNAVAILABLE"


def test_wrong_ledger_rejected_before_reading_inputs(
    cli: CLI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentmine.infrastructure.local_data_inputs import LocalDataInputReader

    monkeypatch.setenv("AGENTMINE_OPERATOR_ID", "operator")
    with patch.object(
        LocalDataInputReader, "load", side_effect=AssertionError("wrong ledger must fail first")
    ):
        assert (
            main(
                [
                    "--db",
                    str(cli.world.database.path),
                    "--ledger",
                    "wrong",
                    "work",
                    "show",
                    "--spec-id",
                    "missing",
                ]
            )
            == 1
        )


def test_read_commands_have_no_source_or_worker_side_effect(cli: CLI) -> None:
    from fakes import FakeSource

    from agentmine.application.workers.data import DataWorker

    assert cli.prepare()[0] == 0 and cli.execute()[0] == 0
    with (
        patch.object(FakeSource, "refresh", side_effect=AssertionError("read-only")),
        patch.object(DataWorker, "execute", side_effect=AssertionError("read-only")),
    ):
        assert cli.command("work", "show", "--spec-id", "cli-spec")[0] == 0
        assert cli.command("work", "status", "--execution-id", "cli-exec")[0] == 0
        assert cli.command("opportunity", "show", "--opportunity", "op")[0] == 0


def test_manual_eligibility_requires_actual_review_reference(cli: CLI) -> None:
    folder = cli.root.parent / "manual-workspace"
    folder.mkdir()
    cli.world = build_world(folder, manual=True)
    facts = json.loads(cli.facts.read_text(encoding="utf-8"))
    facts["facts"]["submission"] = "manual"
    cli.facts.write_text(json.dumps(facts), encoding="utf-8")
    assert cli.prepare()[0] != 0
    assert cli.world.runtime().get_specification(Reference("cli-spec")) is None


def test_changed_terms_after_prepare_blocks_execution(cli: CLI) -> None:
    assert cli.prepare()[0] == 0
    cli.world.source.requirements = "New mandatory condition"
    code, outcome = cli.execute()
    assert code == 1 and outcome["command_status"] == "BLOCKED"
    assert outcome["opportunity_state"] == "PLANNED"


def test_duplicate_json_keys_and_boolean_counts_rejected(cli: CLI) -> None:
    cli.manifest.write_text('{"sources":[],"sources":[],"columns":[]}', encoding="utf-8")
    assert cli.prepare()[0] == 2
    data = {"sources": [], "columns": [], "min_records": True}
    cli.manifest.write_text(json.dumps(data), encoding="utf-8")
    assert cli.prepare()[0] == 2


def test_export_unsafe_destination_fails_without_writing(cli: CLI) -> None:
    from agentmine.application.errors import PortError
    from agentmine.infrastructure.local_artifact_export import LocalArtifactExporter

    assert cli.prepare()[0] == 0 and cli.execute()[0] == 0
    view = cli.world.runtime().inspect(Reference("cli-exec"))
    assert view is not None and view.result is not None
    destination = cli.root / "input.json"  # Existing input file is never a directory.
    before = destination.read_bytes()
    with pytest.raises(PortError):
        LocalArtifactExporter(destination).export(
            Reference("cli-exec"), view.run.plan.execution.reference, view.result.artifacts
        )
    assert destination.read_bytes() == before


def test_prepare_repeated_same_id_keeps_original_approval_time(cli: CLI) -> None:
    from datetime import timedelta

    assert cli.prepare()[0] == 0
    before = cli.world.runtime().get_specification(Reference("cli-spec"))
    cli.world.clock.instant += timedelta(minutes=1)
    assert cli.prepare()[0] == 0
    assert cli.world.runtime().get_specification(Reference("cli-spec")) == before


def test_linked_input_root_is_rejected_without_following_it(cli: CLI) -> None:
    import stat
    from types import SimpleNamespace

    with patch.object(
        Path, "lstat", return_value=SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
    ):
        assert cli.prepare()[0] != 0
