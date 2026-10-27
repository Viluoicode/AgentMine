"""Financial history, races and transaction faults on real SQLite; no paid calls."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

import pytest
from test_budget_control import apply, prepare
from test_runtime_operator_cli import CLI, cli

from agentmine.application.contracts.budget_control import (
    BudgetControlError,
    BudgetControlSnapshot,
    BudgetPolicyApplication,
    BudgetPolicyChangeReceipt,
    BudgetPolicyDecision,
    PolicyConflictReason,
)
from agentmine.application.contracts.records import BudgetCommit, OpportunitySave
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.budget_control import (
    ApplyBudgetPolicyChange,
    PrepareBudgetPolicyChange,
)
from agentmine.application.workers.data import DataWorker
from agentmine.domain.money import Money
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.budget_control import SQLiteBudgetControlRepository
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

__all__ = ["cli"]


def repository(cli: CLI) -> SQLiteBudgetControlRepository:
    return SQLiteBudgetControlRepository(SQLiteDatabase(cli.world.database.path))


def application(cli: CLI, actor: str = "operator") -> ApplyBudgetPolicyChange:
    return ApplyBudgetPolicyChange(
        repository(cli), Reference("ledger"), Reference(actor), cli.world.clock
    )


def rows(cli: CLI) -> tuple[tuple[object, ...], ...]:
    with cli.world.database.transaction() as connection:
        return tuple(
            tuple(row) for row in connection.execute("SELECT * FROM snapshots ORDER BY kind,id")
        )


def test_history_preserved_unknown_cost_visible_and_lower_limits_do_not_release(cli: CLI) -> None:
    manager = cli.world.budget()
    zero = Money(Decimal("0"), "USD")
    one = Money(Decimal("1"), "USD")

    def context(name: str) -> CostContext:
        return CostContext(Reference(name), OperationType.SCORING, cli.world.clock.now())

    outstanding = manager.authorize(one, context("unknown-paid"))
    measured = manager.authorize(one, context("measured"))
    released = manager.authorize(zero, context("abandoned"))
    assert outstanding.authorization and measured.authorization and released.authorization
    manager.record(measured.authorization, one, cli.world.clock.now())
    snapshot = manager.ledger.get(Reference("ledger"))
    assert snapshot is not None
    manager.ledger.commit(
        BudgetCommit(
            Reference("ledger"),
            snapshot.value.release(Reference("abandoned")),
            snapshot.revision,
            None,
        )
    )
    before = manager.ledger.get(Reference("ledger"))
    assert prepare(cli, monthly="0")[0] == 0
    assert apply(cli)[0] == 0
    after = manager.ledger.get(Reference("ledger"))
    assert before is not None and after is not None
    assert after.value.authorizations == before.value.authorizations
    assert after.value.records == before.value.records
    assert after.value.released_operations == before.value.released_operations
    code, view = cli.command("budget", "show")
    assert code == 0 and isinstance(view["warnings"], list)
    assert "budget_overcommitted" in view["warnings"]
    assert view["monthly_remaining"] == {"amount": "-2", "currency": "USD"}
    recovery = view["recovery"]
    assert isinstance(recovery, list)
    assert recovery[0]["actual_cost"] is None
    assert recovery[0]["classification"] == "reconciliation_required"
    assert cli.world.current().state == OpportunityState.PLANNED
    assert cli.world.current().verified_revenue.amount == 0


def test_actor_scope_reason_and_revision_durable(cli: CLI) -> None:
    assert prepare(cli)[0] == 0
    repo = repository(cli)
    proposal = repo.get_change(Reference("change-1"))
    assert proposal is not None
    before = rows(cli)
    with pytest.raises(BudgetControlError) as error:
        application(cli, "other").execute(proposal.reference, confirm=True)
    assert error.value.reason == PolicyConflictReason.ACTOR_MISMATCH
    assert rows(cli) == before
    result = application(cli).execute(proposal.reference, confirm=True)
    assert result.change == proposal and result.change.actor == Reference("operator")
    assert result.change.reason == "Operator reviewed local budget limits"
    assert result.decision.actor == proposal.actor
    assert result.decision.approved_at == cli.world.clock.now()
    assert result.resulting_revision == proposal.expected_revision + 1
    assert repository(cli).get_receipt(proposal.reference) == result


def test_same_id_changed_payload_and_stale_proposals_fail(cli: CLI) -> None:
    assert prepare(cli)[0] == 0
    before = rows(cli)
    assert prepare(cli, monthly="31")[0] != 0
    assert rows(cli) == before
    assert prepare(cli, "change-2", "40")[0] == 0
    assert apply(cli)[0] == 0
    after = rows(cli)
    code, failure = apply(cli, "change-2")
    assert code != 0 and failure["reason"] == "stale_revision"
    assert rows(cli) == after
    code, stale = cli.command("budget", "policy", "show", "--change-id", "change-2")
    assert code == 0 and stale["stale"] is True


@pytest.mark.parametrize(
    "kind", ["budget", "budget_audit", "budget_policy_decision", "budget_policy_receipt"]
)
def test_crash_after_each_write_rolls_back_then_original_change_recovers(
    cli: CLI, kind: str
) -> None:
    assert prepare(cli)[0] == 0
    before = rows(cli)
    original = SQLiteDatabase.write

    def fault(database: SQLiteDatabase, *args: object, **kwargs: object) -> None:
        original(database, *args, **kwargs)  # type: ignore[arg-type]
        if args[1] == kind:
            raise sqlite3.OperationalError("test-only interrupted policy transaction")

    with patch.object(SQLiteDatabase, "write", fault):
        assert apply(cli)[0] != 0
    assert rows(cli) == before
    assert repository(cli).get_receipt(Reference("change-1")) is None
    assert apply(cli)[0] == 0


def test_lost_acknowledgement_returns_original_receipt_without_reapplying(cli: CLI) -> None:
    assert prepare(cli)[0] == 0
    original = SQLiteBudgetControlRepository.apply

    def lose_ack(
        repo: SQLiteBudgetControlRepository, command: BudgetPolicyApplication
    ) -> BudgetPolicyChangeReceipt:
        original(repo, command)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "policy", "Test acknowledgement lost")

    with patch.object(SQLiteBudgetControlRepository, "apply", lose_ack):
        assert apply(cli)[0] != 0
    receipt = repository(cli).get_receipt(Reference("change-1"))
    assert receipt is not None
    before = rows(cli)
    assert application(cli).execute(Reference("change-1"), confirm=True) == receipt
    assert rows(cli) == before


@pytest.mark.parametrize("same_id", [True, False])
def test_concurrent_apply_has_one_ledger_commit(cli: CLI, same_id: bool) -> None:
    assert prepare(cli)[0] == 0
    if not same_id:
        assert prepare(cli, "change-2", "40")[0] == 0
    repo = repository(cli)
    snapshot = repo.read(Reference("ledger")).ledger
    commands = []
    for identity in ("change-1", "change-1" if same_id else "change-2"):
        change = repo.get_change(Reference(identity))
        assert change is not None
        commands.append(
            BudgetPolicyApplication(
                change,
                BudgetPolicyDecision(change.reference, change.actor, cli.world.clock.now()),
                snapshot,
            )
        )
    ready = Barrier(2)

    def attempt(
        command: BudgetPolicyApplication,
    ) -> BudgetPolicyChangeReceipt | PolicyConflictReason:
        ready.wait(timeout=10)
        try:
            return repository(cli).apply(command)
        except BudgetControlError as error:
            return error.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, commands))
    after = repo.read(Reference("ledger")).ledger
    assert after.revision == snapshot.revision + 1
    if same_id:
        assert results[0] == results[1] and isinstance(results[0], BudgetPolicyChangeReceipt)
    else:
        assert sum(isinstance(result, BudgetPolicyChangeReceipt) for result in results) == 1
        assert PolicyConflictReason.STALE_REVISION in results


@pytest.mark.parametrize("change", ["currency", "timezone"])
def test_application_freezes_currency_and_timezone(cli: CLI, change: str) -> None:
    repo = repository(cli)
    snapshot = repo.read(Reference("ledger")).ledger
    policy = snapshot.value.policy
    if change == "timezone":
        proposed = replace(policy, calendar_timezone=timezone(timedelta(hours=7)))
    else:
        proposed = replace(
            policy,
            monthly_ai_budget=Money(policy.monthly_ai_budget.amount, "EUR"),
            daily_ai_budget=Money(policy.daily_ai_budget.amount, "EUR"),
            max_cost_per_task=Money(policy.max_cost_per_task.amount, "EUR"),
            human_approval_cost_threshold=Money(policy.human_approval_cost_threshold.amount, "EUR"),
        )
    before = rows(cli)
    with pytest.raises(BudgetControlError) as error:
        PrepareBudgetPolicyChange(
            repo, Reference("ledger"), Reference("operator"), cli.world.clock
        ).execute(
            Reference("frozen"),
            proposed,
            snapshot.value.requested_mode,
            snapshot.revision,
            "review",
        )
    assert error.value.reason == (
        PolicyConflictReason.CURRENCY_FROZEN
        if change == "currency"
        else PolicyConflictReason.TIMEZONE_FROZEN
    )
    assert rows(cli) == before


def test_legacy_wait_is_inspect_only_and_unknown_stays_unknown(cli: CLI) -> None:
    assert prepare(cli, monthly="0")[0] == 0 and apply(cli)[0] == 0
    manager = cli.world.budget()
    context = CostContext(
        Reference("legacy-wait"),
        OperationType.TASK_EXECUTION,
        cli.world.clock.now(),
        cli.world.specification.task.reference,
        Reference("op"),
    )
    decision = manager.authorize(Money(Decimal("1"), "USD"), context)
    opportunities = SQLiteOpportunityRepository(cli.world.database)
    previous = opportunities.get(Reference("op"))
    assert previous is not None
    # Explicit synthetic legacy record; no positive-cost production worker is introduced.
    opportunities.save(OpportunitySave(previous.value.wait_for_budget(decision), previous.revision))
    before = rows(cli)
    code, view = cli.command("budget", "show")
    assert code == 0
    assert isinstance(view["recovery"], list)
    assert view["recovery"][0]["classification"] == "unsupported_wait"
    assert view["recovery"][0]["actual_cost"] is None
    assert rows(cli) == before
    assert prepare(cli, "restore", "30")[0] == 0 and apply(cli, "restore")[0] == 0
    assert cli.world.current().state == OpportunityState.WAITING_FOR_BUDGET
    assert not cli.world.runtime().incomplete()
    assert cli.world.current().verified_revenue.amount == 0


def test_ambiguous_claim_and_unlinked_zero_commitment_are_never_released(cli: CLI) -> None:
    assert cli.prepare()[0] == 0
    with patch.object(
        DataWorker, "execute", side_effect=RuntimeError("test failure before result")
    ):
        assert cli.execute()[0] != 0
    run = cli.world.runtime().get_run(Reference("cli-exec"))
    assert run is not None
    SQLiteDataJournal(cli.world.database).claim_ai(
        run.plan
    )  # Explicit injected ambiguous evidence.
    manager = cli.world.budget()
    manager.authorize(
        Money(Decimal(0), "USD"),
        CostContext(Reference("unlinked"), OperationType.SCORING, cli.world.clock.now()),
    )
    before = rows(cli)
    code, view = cli.command("budget", "show")
    assert code == 0 and isinstance(view["recovery"], list)
    classifications = {item["operation_reference"]["value"]: item for item in view["recovery"]}
    assert classifications["cli-op"]["classification"] == "reconciliation_required"
    assert classifications["cli-op"]["actual_cost"] is None
    assert classifications["unlinked"]["classification"] == "unlinked_operation"
    assert rows(cli) == before
    assert prepare(cli)[0] == 0 and apply(cli)[0] == 0
    assert cli.world.current().state == OpportunityState.IN_PROGRESS
    ledger = cli.world.budget().ledger.get(Reference("ledger"))
    assert ledger is not None and not ledger.value.records
    assert cli.command("work", "recover", "--execution-id", "cli-exec", "--confirm")[0] != 0


@pytest.mark.parametrize("corruption", ["missing_ledger", "checksum", "missing_audit"])
def test_missing_or_corrupt_budget_authority_fails_closed(cli: CLI, corruption: str) -> None:
    with cli.world.database.transaction(write=True) as connection:
        if corruption == "missing_ledger":
            connection.execute("DELETE FROM snapshots WHERE kind='budget'")
        elif corruption == "checksum":
            connection.execute("UPDATE snapshots SET digest='broken' WHERE kind='budget'")
        else:
            connection.execute("DELETE FROM snapshots WHERE kind='budget_audit'")
    before = rows(cli)
    assert cli.command("budget", "show")[0] != 0
    assert rows(cli) == before


def test_same_id_preparation_preserves_original_time_and_exact_proposal(cli: CLI) -> None:
    assert prepare(cli)[0] == 0
    before = rows(cli)
    cli.world.clock.instant += timedelta(seconds=1)
    assert prepare(cli)[0] == 0
    assert rows(cli) == before


def test_noop_policy_is_audited_once_and_keeps_history(cli: CLI) -> None:
    assert prepare(cli, monthly="10")[0] == 0
    before = repository(cli).read(Reference("ledger")).ledger
    receipt = application(cli).execute(Reference("change-1"), confirm=True)
    after = repository(cli).read(Reference("ledger")).ledger
    assert before.value == after.value and after.revision == before.revision + 1
    assert application(cli).execute(Reference("change-1"), confirm=True) == receipt
    assert repository(cli).read(Reference("ledger")).ledger == after


def test_changed_internal_delta_cannot_replace_retained_proposal(cli: CLI) -> None:
    assert prepare(cli)[0] == 0
    repo = repository(cli)
    change = repo.get_change(Reference("change-1"))
    assert change is not None
    altered = replace(change, reason="different consent")
    command = BudgetPolicyApplication(
        altered,
        BudgetPolicyDecision(altered.reference, altered.actor, cli.world.clock.now()),
        repo.read(Reference("ledger")).ledger,
    )
    before = rows(cli)
    with pytest.raises(BudgetControlError) as error:
        repo.apply(command)
    assert error.value.reason == PolicyConflictReason.IDENTITY_CONFLICT
    assert rows(cli) == before


def test_calendar_rollover_keeps_commitments_and_frozen_timezone(cli: CLI) -> None:
    manager = cli.world.budget()
    snapshot = manager.ledger.get(Reference("ledger"))
    assert snapshot is not None
    zone = timezone(timedelta(hours=7))
    budget = snapshot.value.with_policy(replace(snapshot.value.policy, calendar_timezone=zone))
    manager.ledger.commit(BudgetCommit(Reference("ledger"), budget, snapshot.revision, None))
    cli.world.clock.instant = datetime(2026, 10, 31, 16, 59, tzinfo=UTC)
    one = Money(Decimal(1), "USD")
    measured = manager.authorize(
        one, CostContext(Reference("month-actual"), OperationType.SCORING, manager.clock.now())
    )
    assert measured.authorization is not None
    manager.record(measured.authorization, one, manager.clock.now())
    manager.authorize(
        one, CostContext(Reference("month-unknown"), OperationType.SCORING, manager.clock.now())
    )
    before = manager.ledger.get(Reference("ledger"))
    cli.world.clock.instant += timedelta(minutes=2)
    code, view = cli.command("budget", "show")
    assert code == 0 and view["monthly_spent"] == {"amount": "0", "currency": "USD"}
    assert view["reserved_ai"] == {"amount": "1", "currency": "USD"}
    assert manager.ledger.get(Reference("ledger")) == before
    assert prepare(cli)[0] == 0 and apply(cli)[0] == 0
    after = manager.ledger.get(Reference("ledger"))
    assert before is not None and after is not None
    assert after.value.policy.calendar_timezone == zone
    assert after.value.authorizations == before.value.authorizations
    assert after.value.records == before.value.records


def test_policy_consent_never_grants_spending_submission_or_task_progress(cli: CLI) -> None:
    from fakes import FakeSource

    from agentmine.application.use_cases.settlement import SubmitTask, VerifyPayment

    before = rows(cli)
    with (
        patch.object(FakeSource, "refresh", side_effect=AssertionError("no source IO")),
        patch.object(DataWorker, "execute", side_effect=AssertionError("no execution")),
        patch.object(SubmitTask, "execute", side_effect=AssertionError("no submission")),
        patch.object(VerifyPayment, "execute", side_effect=AssertionError("no verification")),
    ):
        assert prepare(cli)[0] == 0 and apply(cli)[0] == 0
    after = rows(cli)
    allowed = {
        "budget",
        "budget_audit",
        "budget_policy_change",
        "budget_policy_decision",
        "budget_policy_receipt",
    }
    assert tuple(row for row in before if row[0] not in allowed) == tuple(
        row for row in after if row[0] not in allowed
    )
    assert cli.world.current().state == OpportunityState.PLANNED
    assert cli.world.current().verified_revenue.amount == 0


def test_lowered_policy_projection_warns_before_approval(cli: CLI) -> None:
    manager = cli.world.budget()
    manager.authorize(
        Money(Decimal(1), "USD"),
        CostContext(Reference("unknown"), OperationType.SCORING, manager.clock.now()),
    )
    assert prepare(cli, monthly="0")[0] == 0
    code, view = cli.command("budget", "policy", "show", "--change-id", "change-1")
    assert code == 0 and view["projected_warnings"] == ["budget_overcommitted"]
    assert view["receipt"] is None and view["projected_mode"] == "scout_only"
    assert view["projected_monthly_remaining"] == {"amount": "-1", "currency": "USD"}


def test_concurrent_commit_between_receipt_read_and_snapshot_returns_original(cli: CLI) -> None:
    assert prepare(cli)[0] == 0
    repo = repository(cli)
    change = repo.get_change(Reference("change-1"))
    assert change is not None
    snapshot = repo.read(Reference("ledger")).ledger
    command = BudgetPolicyApplication(
        change,
        BudgetPolicyDecision(change.reference, change.actor, cli.world.clock.now()),
        snapshot,
    )
    original = SQLiteBudgetControlRepository.read

    def raced_read(
        store: SQLiteBudgetControlRepository, ledger: Reference
    ) -> BudgetControlSnapshot:
        repository(cli).apply(command)  # Simulate a competing process after caller saw no receipt.
        return original(store, ledger)

    with patch.object(SQLiteBudgetControlRepository, "read", raced_read):
        receipt = application(cli).execute(change.reference, confirm=True)
    assert receipt == command.receipt
    assert repo.read(Reference("ledger")).ledger.revision == snapshot.revision + 1
