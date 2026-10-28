"""Real operator CLI/SQLite/worker/QA; source and clock are explicitly test-only."""

import json
from pathlib import Path

import pytest
from test_operational_deliverable_qa import execute_data, operator_command, qa
from test_runtime_operator_cli import CLI, cli

__all__ = ["cli"]


def files(cli: CLI, *, missing: bool = False) -> tuple[Path, Path]:
    manifest = json.loads(cli.manifest.read_text(encoding="utf-8"))
    if missing and not any(item["name"] == "absent" for item in manifest["columns"]):
        manifest["columns"].append({"name": "absent", "path": ["name"]})
        cli.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    economics = cli.root.parent / "revision-economics.json"
    economics.write_text(
        json.dumps(
            {
                "currency": "USD",
                "predicted_success_probability": {
                    "value": "0.5",
                    "rationale": "Explicit subjective fixture estimate",
                },
                "estimated_cost": {
                    "ai": "0",
                    "tool": "0",
                    "infrastructure": "0",
                    "transaction": "0",
                },
                "cost_rationale": "Offline forecast, not actual billing",
            }
        ),
        encoding="utf-8",
    )
    scoring = cli.root.parent / "revision-score.json"
    scoring.write_text(
        json.dumps(
            {
                "policy": {
                    "version": "fixture-v2",
                    "net_value_target": "10",
                    "currency": "USD",
                    "rationale": "Fixture target",
                },
                "signals": {
                    name: {"value": "0.5", "rationale": "Subjective fixture signal"}
                    for name in [
                        "risk",
                        "competition",
                        "deadline",
                        "ai_suitability",
                        "historical_performance",
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return economics, scoring


def prepare(
    cli: CLI,
    *,
    number: int = 2,
    parent: str = "cli-exec",
    trigger: str = "qa",
    trigger_id: str = "qa-001",
    missing: bool = False,
) -> tuple[int, dict[str, object]]:
    economics, scoring = files(cli, missing=missing)
    return cli.command(
        "work",
        "revision",
        "prepare",
        "--revision-id",
        f"revision-{number}",
        "--parent-execution",
        parent,
        "--trigger",
        trigger,
        "--trigger-id",
        trigger_id,
        "--spec-id",
        f"revision-{number}-spec",
        "--evaluation",
        f"revision-{number}-eval",
        "--inputs",
        str(cli.manifest),
        "--input-root",
        str(cli.root),
        "--facts",
        str(cli.facts),
        "--minimum-time-seconds",
        "3600",
        "--economics",
        str(economics),
        "--scoring",
        str(scoring),
        "--forecast-evidence",
        f"operator:forecast-{number}",
        "--reason",
        "Repair the approved local data",
    )


def approve(cli: CLI, number: int = 2) -> tuple[int, dict[str, object]]:
    return cli.command(
        "work",
        "revision",
        "approve",
        "--revision-id",
        f"revision-{number}",
        "--execution-id",
        f"revision-{number}-exec",
        "--operation-id",
        f"revision-{number}-cost",
        "--approve-inputs",
        "--confirm",
    )


def execute(cli: CLI, number: int = 2) -> tuple[int, dict[str, object]]:
    return cli.command(
        "work", "revision", "execute", "--revision-id", f"revision-{number}", "--confirm"
    )


@pytest.mark.parametrize("mode", ["needs_revision", "fail", "operator"])
def test_revision_cli_ends_in_real_qa_and_separate_human_review(cli: CLI, mode: str) -> None:
    if mode == "fail":
        from test_operational_deliverable_qa import (
            test_real_qa_engine_detects_coherently_corrupted_values_as_fail,
        )

        test_real_qa_engine_detects_coherently_corrupted_values_as_fail(cli)
    else:
        execute_data(cli, missing=mode == "needs_revision")
        qa(cli)
        if mode == "operator":
            assert (
                operator_command(
                    cli,
                    "review",
                    "--opportunity",
                    "op",
                    "--review-id",
                    "review-v1",
                    "--destination",
                    "operator:fixture",
                )
                == 0
            )
            assert (
                operator_command(
                    cli, "decide", "--review-id", "review-v1", "--decision", "REQUEST_REVISION"
                )
                == 0
            )
    assert (
        prepare(
            cli,
            trigger="operator" if mode == "operator" else "qa",
            trigger_id="review-v1" if mode == "operator" else "qa-001",
            missing=mode == "needs_revision",
        )[0]
        == 0
    )
    assert cli.command("work", "revision", "show", "--revision-id", "revision-2")[0] == 0
    assert approve(cli)[0] == 0
    assert execute(cli)[1]["opportunity_state"] == "QA_PENDING"
    code, report = cli.command(
        "work", "qa", "--execution-id", "revision-2-exec", "--inspection-id", "qa-v2", "--confirm"
    )
    assert code == 0 and report["qa_outcome"] == "PASS"
    assert cli.world.current().approval is None and cli.world.current().submission is None
    assert cli.world.current().verified_revenue.amount == 0
    assert (
        cli.command("work", "status", "--execution-id", "cli-exec")[1][
            "requested_execution_is_current"
        ]
        is False
    )
    status = cli.command("work", "status", "--execution-id", "revision-2-exec")[1]
    deliverable = status["deliverable"]
    assert isinstance(deliverable, dict) and deliverable["version"] == 2


def test_revision_export_manifest_has_exact_version_and_no_clobber(cli: CLI) -> None:
    execute_data(cli, missing=True)
    qa(cli)
    assert prepare(cli, missing=True)[0] == 0 and approve(cli)[0] == 0 and execute(cli)[0] == 0
    assert (
        cli.command(
            "work", "export", "--execution-id", "revision-2-exec", "--directory", str(cli.export)
        )[0]
        == 0
    )
    manifest = json.loads((cli.export / "manifest.json").read_text())
    assert (
        manifest["deliverable"]["version"] == 2
        and manifest["deliverable"]["lineage"] == "cli-deliverable"
    )
    assert manifest["external_submission"] is False
    assert (
        cli.command("work", "export", "--execution-id", "cli-exec", "--directory", str(cli.export))[
            0
        ]
        != 0
    )


def test_revision_requires_explicit_consent_and_live_refresh(cli: CLI) -> None:
    execute_data(cli, missing=True)
    qa(cli)
    assert prepare(cli, missing=True)[0] == 0
    assert execute(cli)[0] != 0
    assert (
        cli.command(
            "work",
            "revision",
            "approve",
            "--revision-id",
            "revision-2",
            "--execution-id",
            "revision-2-exec",
            "--operation-id",
            "revision-2-cost",
            "--confirm",
        )[0]
        != 0
    )


def ready(cli: CLI) -> None:
    execute_data(cli, missing=True)
    assert qa(cli)[1]["qa_outcome"] == "NEEDS_REVISION"
    assert prepare(cli, missing=True)[0] == 0 and approve(cli)[0] == 0


@pytest.mark.parametrize("case", ["unavailable", "terms", "expired"])
def test_source_preflight_remains_mandatory(cli: CLI, case: str) -> None:
    from datetime import timedelta
    from unittest.mock import patch

    from agentmine.application.workers.data import DataWorker

    ready(cli)
    if case == "unavailable":
        cli.world.source.is_open = None
    elif case == "terms":
        cli.world.source.requirements = "changed requirements"
    else:
        cli.world.clock.instant += timedelta(days=3)
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no stale work")):
        assert execute(cli)[0] != 0


def test_strict_input_and_changed_bytes(cli: CLI) -> None:
    execute_data(cli, missing=True)
    qa(cli)
    files(cli, missing=True)
    original = cli.manifest.read_text(encoding="utf-8")
    data = json.loads(original)
    data["version"] = 2
    cli.manifest.write_text(json.dumps(data), encoding="utf-8")
    assert prepare(cli)[0] != 0
    cli.manifest.write_text(original, encoding="utf-8")
    (cli.root / "input.json").write_text("tampered", encoding="utf-8")
    assert prepare(cli)[0] != 0


def test_same_hash_cannot_transfer_qa_or_submission_consent(cli: CLI) -> None:
    execute_data(cli)
    assert qa(cli)[1]["qa_outcome"] == "PASS"
    original = cli.world.current().deliverable
    assert original is not None
    for review in ("old-undecided", "request-rework"):
        assert (
            operator_command(
                cli,
                "review",
                "--opportunity",
                "op",
                "--review-id",
                review,
                "--destination",
                "operator:fixture",
            )
            == 0
        )
    assert (
        operator_command(
            cli, "decide", "--review-id", "request-rework", "--decision", "REQUEST_REVISION"
        )
        == 0
    )
    assert prepare(cli, trigger="operator", trigger_id="request-rework")[0] == 0
    assert approve(cli)[0] == 0 and execute(cli)[0] == 0
    revised = cli.world.current().deliverable
    assert revised is not None and revised.content_reference == original.content_reference
    assert (
        revised != original
        and cli.world.current().qa is None
        and cli.world.current().approval is None
    )
    assert (
        cli.command(
            "work",
            "qa",
            "--execution-id",
            "revision-2-exec",
            "--inspection-id",
            "qa-001",
            "--confirm",
        )[0]
        != 0
    )
    assert (
        cli.command(
            "work",
            "qa",
            "--execution-id",
            "revision-2-exec",
            "--inspection-id",
            "new-qa-v2",
            "--confirm",
        )[1]["qa_outcome"]
        == "PASS"
    )
    assert (
        operator_command(cli, "decide", "--review-id", "old-undecided", "--decision", "APPROVE")
        != 0
    )
    assert (
        operator_command(
            cli,
            "review",
            "--opportunity",
            "op",
            "--review-id",
            "old-undecided",
            "--destination",
            "operator:fixture",
        )
        != 0
    )
    assert (
        operator_command(
            cli,
            "review",
            "--opportunity",
            "op",
            "--review-id",
            "new-review-v2",
            "--destination",
            "operator:fixture",
        )
        == 0
    )
    assert (
        operator_command(cli, "decide", "--review-id", "new-review-v2", "--decision", "APPROVE")
        == 0
    )
    assert cli.world.current().submission is None and cli.world.current().payment is None
    # Historical report readback cannot rewind the approved child.
    before = cli.world.current()
    assert qa(cli)[1]["qa_outcome"] == "PASS"
    assert cli.world.current() == before


def corrupt_revision(cli: CLI, identity: str) -> None:
    """Test-only coherent corruption, followed by the real QA engine."""
    from dataclasses import replace

    from agentmine.application.contracts.qa import bundle_content
    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.workers.data_artifacts import artifacts
    from agentmine.domain.values import Reference
    from agentmine.domain.work import Deliverable
    from agentmine.infrastructure.sqlite.data_revision import SQLiteRevisionRuntimeRepository
    from agentmine.infrastructure.sqlite.database import IndexValues, composite_key
    from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    view = SQLiteRevisionRuntimeRepository(cli.world.database).inspect(Reference(identity))
    assert (
        view is not None
        and view.run is not None
        and view.result is not None
        and view.deliverable is not None
    )
    run = view.run
    result = view.result.result
    records = list(result.records)
    cells = list(records[0].cells)
    cells[0] = replace(cells[0], value="unsupported changed value")
    records[0] = replace(records[0], cells=tuple(cells))
    result = replace(
        result, records=tuple(records), artifacts=artifacts(run.worker.plan, tuple(records), ())
    )
    content = bundle_content(result)
    deliverable = Deliverable(
        view.deliverable.reference,
        view.deliverable.execution_reference,
        view.deliverable.version,
        content.reference,
    )
    SQLiteExecutionRepository(cli.world.database).save_content(content)
    with cli.world.database.transaction(write=True) as connection:
        for kind, key, value in (
            ("data_result", deliverable.execution_reference.value, result),
            (
                "deliverable",
                composite_key(deliverable.reference.value, deliverable.version),
                deliverable,
            ),
            ("revision_finish", deliverable.execution_reference.value, deliverable),
        ):
            cli.world.database.write(connection, kind, key, value, 1, IndexValues())
    current = SQLiteOpportunityRepository(cli.world.database).get(
        run.worker.specification.task.opportunity_reference
    )
    assert current is not None
    SQLiteOpportunityRepository(cli.world.database).save(
        OpportunitySave(run.started_snapshot.value.finish(deliverable), current.revision)
    )


def test_v2_fail_then_v3_pass_and_historical_qa_readback(cli: CLI) -> None:
    ready(cli)
    assert execute(cli)[0] == 0
    corrupt_revision(cli, "revision-2")
    assert (
        cli.command(
            "work",
            "qa",
            "--execution-id",
            "revision-2-exec",
            "--inspection-id",
            "qa-v2",
            "--confirm",
        )[1]["qa_outcome"]
        == "FAIL"
    )
    assert prepare(cli, number=3, parent="revision-2-exec", trigger_id="qa-v2")[0] == 0
    assert approve(cli, 3)[0] == 0 and execute(cli, 3)[0] == 0
    assert (
        cli.command(
            "work",
            "qa",
            "--execution-id",
            "revision-3-exec",
            "--inspection-id",
            "qa-v3",
            "--confirm",
        )[1]["qa_outcome"]
        == "PASS"
    )
    before = cli.world.current()
    assert (
        cli.command(
            "work",
            "qa",
            "--execution-id",
            "revision-2-exec",
            "--inspection-id",
            "qa-v2",
            "--confirm",
        )[1]["qa_outcome"]
        == "FAIL"
    )
    assert cli.world.current() == before
    assert before.deliverable is not None and before.deliverable.version == 3


def test_reopen_recover_uses_original_allocation_without_worker(cli: CLI) -> None:
    from unittest.mock import patch

    from agentmine.application.errors import PortError, PortErrorCode
    from agentmine.application.workers.data import DataWorker
    from agentmine.infrastructure.sqlite.data_revision import SQLiteRevisionRuntimeRepository

    ready(cli)
    with patch.object(
        SQLiteRevisionRuntimeRepository,
        "finish",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "finish", "injected"),
    ):
        assert execute(cli)[1]["command_status"] == "RECOVERABLE"
    allocation = cli.command("work", "revision", "show", "--revision-id", "revision-2")[1][
        "allocation"
    ]
    pending = cli.command("work", "status", "--execution-id", "revision-2-exec")[1]
    assert (
        pending["recovery_reason"] == "FINISH_PENDING"
        and pending["execution_control"] == "RECOVERABLE"
    )
    with patch.object(DataWorker, "execute", side_effect=AssertionError("reuse retained result")):
        assert (
            cli.command("work", "revision", "recover", "--revision-id", "revision-2", "--confirm")[
                0
            ]
            == 0
        )
    assert (
        cli.command("work", "revision", "show", "--revision-id", "revision-2")[1]["allocation"]
        == allocation
    )


def test_concurrent_cli_retries_have_one_cost_and_version(cli: CLI) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from agentmine.domain.values import Reference

    ready(cli)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: execute(cli), range(2)))
    assert (
        cli.command("work", "revision", "recover", "--revision-id", "revision-2", "--confirm")[0]
        == 0
    )
    ledger = cli.world.budget().ledger.get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.records) == 2
    assert cli.world.current().deliverable is not None


def test_real_budget_cli_scout_only_continues_revision(cli: CLI) -> None:
    ready(cli)
    before = cli.command("budget", "show")[1]
    path = cli.root.parent / "policy.json"
    path.write_text(
        json.dumps(
            {
                "monthly_ai_budget": "0",
                "daily_ai_budget": "0",
                "max_cost_per_task": "3",
                "human_approval_cost_threshold": "1",
                "saver_remaining_ratio": "0.2",
                "saver_ai_cost_factor": "0.5",
                "requested_mode": "scout_only",
            }
        ),
        encoding="utf-8",
    )
    assert (
        cli.command(
            "budget",
            "policy",
            "prepare",
            "--change-id",
            "scout",
            "--inputs",
            str(path),
            "--expected-revision",
            str(before["revision"]),
            "--reason",
            "Explicit fixture policy",
        )[0]
        == 0
    )
    assert cli.command("budget", "policy", "apply", "--change-id", "scout", "--confirm")[0] == 0
    assert execute(cli)[0] == 0


def test_entrypoint_actor_ledger_and_live_source_opt_in(
    cli: CLI, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from unittest.mock import patch

    from agentmine.bootstrap.operator import main

    ready(cli)
    base = ["--db", str(cli.world.database.path), "--ledger", "ledger"]
    command = ["work", "revision", "execute", "--revision-id", "revision-2", "--confirm"]
    monkeypatch.setenv("AGENTMINE_OPERATOR_ID", "operator")
    monkeypatch.delenv("AGENTMINE_SUPERTEAM_API_KEY", raising=False)
    with patch(
        "agentmine.bootstrap.operator.SuperteamHTTP", side_effect=AssertionError("no live client")
    ):
        assert main([*base, *command]) == 1
        assert json.loads(capsys.readouterr().out)["reason"] == "SOURCE_UNAVAILABLE"
        assert main([*base, "--live-superteam-refresh", *command]) == 2
        capsys.readouterr()
    monkeypatch.setenv("AGENTMINE_OPERATOR_ID", "other")
    assert main([*base, *command]) != 0
    capsys.readouterr()
    monkeypatch.setenv("AGENTMINE_OPERATOR_ID", "operator")
    assert main(["--db", str(cli.world.database.path), "--ledger", "wrong", *command]) != 0
    capsys.readouterr()
    monkeypatch.delenv("AGENTMINE_OPERATOR_ID", raising=False)
    assert main([*base, *command]) == 2


def test_v2_stale_unapplied_inspection_cannot_rebase(cli: CLI) -> None:
    from unittest.mock import patch

    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.errors import PortError, PortErrorCode
    from agentmine.domain.values import Reference
    from agentmine.infrastructure.sqlite.operational_qa import SQLiteOperationalQARepository
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    ready(cli)
    assert execute(cli)[0] == 0
    args = (
        "work",
        "qa",
        "--execution-id",
        "revision-2-exec",
        "--inspection-id",
        "pending-qa-v2",
        "--confirm",
    )
    with patch.object(
        SQLiteOperationalQARepository,
        "complete",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "complete", "injected"),
    ):
        assert cli.command(*args)[0] != 0
    repository = SQLiteOpportunityRepository(cli.world.database)
    current = repository.get(Reference("op"))
    assert current is not None
    repository.save(OpportunitySave(current.value, current.revision))
    assert cli.command(*args)[0] != 0
    assert cli.world.current().qa is None


def test_historical_export_and_retry(cli: CLI) -> None:
    ready(cli)
    assert execute(cli)[0] == 0
    before = cli.world.current()
    for execution, version in (("cli-exec", 1), ("revision-2-exec", 2)):
        cli.export = cli.root.parent / f"export-{version}"
        args = ("work", "export", "--execution-id", execution, "--directory", str(cli.export))
        assert cli.command(*args)[0] == 0 and cli.command(*args)[0] == 0
        manifest = json.loads((cli.export / "manifest.json").read_text())
        assert manifest["deliverable"]["version"] == version
    assert cli.world.current() == before


def test_version_cannot_be_selected_by_cli(cli: CLI) -> None:
    with pytest.raises(SystemExit):
        cli.command(
            "work",
            "revision",
            "execute",
            "--revision-id",
            "revision-2",
            "--version",
            "99",
            "--confirm",
        )


def test_revision_human_qa_stays_pending(cli: CLI) -> None:
    execute_data(cli, missing=True)
    qa(cli)
    files(cli, missing=True)
    manifest = json.loads(cli.manifest.read_text(encoding="utf-8"))
    manifest["acceptance"]["requirements"].append(
        {
            "id": "semantic-review",
            "artifact": "data.csv",
            "kind": "semantic",
            "criterion": "Interpret this approved dataset",
        }
    )
    cli.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    assert prepare(cli)[0] == 0 and approve(cli)[0] == 0 and execute(cli)[0] == 0
    assert (
        cli.command(
            "work",
            "qa",
            "--execution-id",
            "revision-2-exec",
            "--inspection-id",
            "human-v2",
            "--confirm",
        )[1]["qa_outcome"]
        == "REQUIRES_HUMAN_REVIEW"
    )
    assert cli.world.current().qa is None and cli.world.current().approval is None
    assert prepare(cli, number=3, parent="revision-2-exec", trigger_id="human-v2")[0] != 0


@pytest.mark.parametrize("case", ["duplicate", "oversize", "constant"])
def test_revision_manifest_is_bounded_strict_json(cli: CLI, case: str) -> None:
    execute_data(cli, missing=True)
    qa(cli)
    files(cli, missing=True)
    raw = cli.manifest.read_text(encoding="utf-8")
    if case == "duplicate":
        raw = raw.replace('"columns":', '"columns":[],"columns":', 1)
    elif case == "oversize":
        raw = " " * 64001 + raw
    else:
        raw = raw.replace('"min_records": 2', '"min_records": NaN')
    cli.manifest.write_text(raw, encoding="utf-8")
    assert prepare(cli)[0] != 0


def test_active_revision_status_preserves_parent_qa_and_checks_revision(cli: CLI) -> None:
    from unittest.mock import patch

    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.workers.data import DataWorker
    from agentmine.domain.values import Reference
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    ready(cli)
    with patch.object(DataWorker, "execute", side_effect=RuntimeError("interrupted")):
        assert execute(cli)[1]["command_status"] == "RECOVERABLE"
    assert (
        cli.command("work", "status", "--execution-id", "revision-2-exec")[1]["recovery_reason"]
        == "RESULT_MISSING"
    )
    repository = SQLiteOpportunityRepository(cli.world.database)
    current = repository.get(Reference("op"))
    assert current is not None
    repository.save(OpportunitySave(current.value, current.revision))
    status = cli.command("work", "status", "--execution-id", "revision-2-exec")[1]
    assert status["recovery_reason"] == "STATE_CHANGED" and status["execution_control"] == "BLOCKED"
    assert (
        cli.command("work", "revision", "recover", "--revision-id", "revision-2", "--confirm")[0]
        != 0
    )
