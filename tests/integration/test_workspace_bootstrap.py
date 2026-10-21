"""Workspace setup writes only explicit budget policy; ingestion uses public use cases."""

import io
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from test_use_cases import World, world

from agentmine.application.contracts.records import BudgetCommit
from agentmine.bootstrap.operator import UTCClock, compose_operator, main
from agentmine.domain.budget import Budget, BudgetPolicy
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.presentation.operator_cli import run_cli

__all__ = ["world"]


def usd(value: str) -> Money:
    return Money(Decimal(value), "USD")


class FixtureTransport:
    def __init__(self) -> None:
        self.routes: list[str] = []

    def get(self, route: str) -> bytes:
        self.routes.append(route)
        name = "live.json" if "live?" in route else "detail.json"
        return (Path(__file__).parents[1] / "contract/fixtures/superteam" / name).read_bytes()


def test_init_creates_only_configured_ledger_and_is_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "new" / "agentmine.sqlite3"
    args = [
        "--db",
        str(path),
        "--ledger",
        "local",
        "workspace",
        "init",
        "--currency",
        "USD",
        "--monthly-ai-budget",
        "20",
        "--daily-ai-budget",
        "5",
        "--max-cost-per-task",
        "4",
        "--human-approval-cost-threshold",
        "1",
    ]
    assert not path.parent.exists()
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "workspace_initialized"
    assert "verified_revenue" not in report  # Init never invents workspace-wide metrics.
    assert "discovered_opportunities" not in report
    assert SQLiteCostLedgerRepository(SQLiteDatabase(path)).count() == 1
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 1
    repo = SQLiteCostLedgerRepository(SQLiteDatabase(path))
    current = repo.get(Reference("local"))
    assert current is not None
    recorded = current.value.record(
        usd("2"),
        CostCategory.AI,
        CostContext(Reference("actual"), OperationType.SCORING, UTCClock().now()),
    )
    repo.commit(BudgetCommit(Reference("local"), recorded.budget, current.revision, recorded))
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 2
    preserved = repo.get(Reference("local"))
    assert preserved is not None and preserved.value.records == recorded.budget.records
    assert (
        main(
            [
                "--db",
                str(path),
                "--ledger",
                "local",
                "workspace",
                "init",
                "--currency",
                "USD",
                "--monthly-ai-budget",
                "21",
                "--daily-ai-budget",
                "5",
                "--max-cost-per-task",
                "4",
                "--human-approval-cost-threshold",
                "1",
            ]
        )
        == 1
    )

    different_id = ["other" if item == "local" else item for item in args]
    assert main(different_id) == 2
    assert repo.count() == 1 and repo.get(Reference("other")) is None


def test_bootstrap_superteam_contract_fixture_persists_raw_data_and_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "workspace.sqlite3"
    init = [
        "--db",
        str(path),
        "--ledger",
        "local",
        "workspace",
        "init",
        "--currency",
        "USD",
        "--monthly-ai-budget",
        "20",
        "--daily-ai-budget",
        "5",
        "--max-cost-per-task",
        "4",
        "--human-approval-cost-threshold",
        "1",
    ]
    assert main(init) == 0
    capsys.readouterr()
    monkeypatch.setenv("AGENTMINE_SUPERTEAM_API_KEY", "sk_fixture_only")
    transport = FixtureTransport()
    command = [
        "--db",
        str(path),
        "--ledger",
        "local",
        "workspace",
        "discover",
        "--source",
        "superteam",
        "--live",
        "--limit",
        "1",
    ]
    with patch("agentmine.bootstrap.operator.SuperteamHTTP", return_value=transport):
        assert main(command) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["observed"] == report["normalized_this_run"] == 1
        assert report["pagination_unverified"] is True
        assert main(command) == 0
        assert json.loads(capsys.readouterr().out)["normalized_this_run"] == 0
    repo = SQLiteOpportunityRepository(SQLiteDatabase(path))
    opportunity = repo.get(Reference("superteam:fixture-project-1"))
    assert opportunity is not None and opportunity.value.state == OpportunityState.NORMALIZED
    assert opportunity.revision == 2
    evidence = opportunity.value.potential_reward.evidence
    assert evidence is not None
    archive = RawArchive(Path(str(path) + ".raw.sqlite3"))
    capture = archive.get(evidence)
    assert (
        capture is not None
        and capture.body
        == (Path(__file__).parents[1] / "contract/fixtures/superteam/detail.json").read_bytes()
    )
    assert main(["--db", str(path), "--ledger", "local", "dashboard"]) == 0
    output = capsys.readouterr().out
    assert "Total discovered and retained: 1" in output
    assert "Verified Revenue: 0 SOL" in output and "Expected Value: UNKNOWN" in output
    assert "sk_fixture_only" not in output
    assert len(transport.routes) == 4


def test_discovery_without_initialized_ledger_does_not_contact_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "workspace.sqlite3"
    SQLiteDatabase(path)
    monkeypatch.setenv("AGENTMINE_SUPERTEAM_API_KEY", "sk_fixture_only")
    transport = FixtureTransport()
    with patch("agentmine.bootstrap.operator.SuperteamHTTP", return_value=transport):
        assert (
            main(
                [
                    "--db",
                    str(path),
                    "--ledger",
                    "local",
                    "workspace",
                    "discover",
                    "--source",
                    "superteam",
                    "--live",
                    "--limit",
                    "1",
                ]
            )
            == 1
        )
    assert transport.routes == []


def test_workspace_discovery_ingests_and_normalizes_without_scoring_or_earnings(
    tmp_path: Path, world: World
) -> None:
    path = tmp_path / "workspace.sqlite3"
    database = SQLiteDatabase(path)
    ledger = SQLiteCostLedgerRepository(database)
    ledger.commit(
        BudgetCommit(
            Reference("local"),
            Budget(
                BudgetPolicy(
                    usd("1"),
                    usd("1"),
                    usd("1"),
                    usd("0"),
                )
            ),
            None,
            None,
        )
    )
    services = compose_operator(
        path, Reference("local"), Reference("read-only"), world.clock, world.source
    )
    output = io.StringIO()
    result = run_cli(
        [
            "--db",
            "ignored",
            "--ledger",
            "local",
            "workspace",
            "discover",
            "--source",
            "superteam",
            "--live",
            "--limit",
            "1",
        ],
        services,
        output,
    )
    report = json.loads(output.getvalue())
    assert result == 0 and report["observed"] == 1 and report["normalized_this_run"] == 1
    assert report["verified_revenue_created"] is False
    opportunity = SQLiteOpportunityRepository(database).get(world.reference)
    assert opportunity is not None and opportunity.value.state == OpportunityState.NORMALIZED
    assert opportunity.value.score is None and opportunity.value.payment is None
    assert ledger.get(Reference("local")) is not None

    repeated = io.StringIO()
    assert (
        run_cli(
            [
                "--db",
                "ignored",
                "--ledger",
                "local",
                "workspace",
                "discover",
                "--source",
                "superteam",
                "--live",
                "--limit",
                "1",
            ],
            services,
            repeated,
        )
        == 0
    )
    retry = json.loads(repeated.getvalue())
    assert retry["normalized_this_run"] == 0
    persisted = SQLiteOpportunityRepository(database).get(world.reference)
    assert persisted is not None and persisted.value.state == OpportunityState.NORMALIZED


def test_no_live_marketplace_access_without_opt_in_or_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "workspace.sqlite3"
    SQLiteDatabase(path)
    monkeypatch.delenv("AGENTMINE_SUPERTEAM_API_KEY", raising=False)
    args = [
        "--db",
        str(path),
        "--ledger",
        "local",
        "workspace",
        "discover",
        "--source",
        "superteam",
    ]
    assert main(args) == 2
    assert "--live" in capsys.readouterr().out
    assert main([*args, "--live"]) == 2
    output = capsys.readouterr().out
    assert "AGENTMINE_SUPERTEAM_API_KEY" in output
    assert "sk_" not in output


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", "not-a-number"])
def test_invalid_budget_inputs_do_not_initialize_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], amount: str
) -> None:
    path = tmp_path / "invalid.sqlite3"
    code = main(
        [
            "--db",
            str(path),
            "--ledger",
            "local",
            "workspace",
            "init",
            "--currency",
            "USD",
            "--monthly-ai-budget",
            amount,
            "--daily-ai-budget",
            "5",
            "--max-cost-per-task",
            "4",
            "--human-approval-cost-threshold",
            "1",
        ]
    )
    assert code in (1, 2)
    assert not path.exists()
