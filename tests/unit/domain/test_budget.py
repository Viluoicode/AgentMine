from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest

from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import (
    AuthorizationStatus,
    BudgetReason,
    CostContext,
    OperationType,
    RecordingIssue,
)
from agentmine.domain.values import Reference


def money(amount: str | int) -> Money:
    return Money(Decimal(amount), "USD")


def policy() -> BudgetPolicy:
    return BudgetPolicy(money(100), money(20), money(10), money(5))


def context(
    operation: str = "operation-1",
    day: int = 13,
    *,
    task: str = "task-1",
) -> CostContext:
    return CostContext(
        Reference(operation),
        OperationType.TASK_EXECUTION,
        datetime(2026, 10, day, tzinfo=UTC),
        Reference(task),
        Reference("opportunity"),
    )


def test_normal_authorization_reserves_estimate_and_records_actual_separately() -> None:
    original = Budget(policy())
    decision = original.authorize(money(3), CostCategory.AI, context())
    assert decision.status == AuthorizationStatus.AUTHORIZED
    assert decision.mode == OperatingMode.FULL
    assert decision.authorization is not None
    assert decision.budget.ai_committed(context().occurred_at) == money(3)
    assert decision.budget.ai_spent(context().occurred_at) == money(0)
    assert decision.budget.records == ()
    assert original.authorizations == ()
    recording = decision.budget.record(money(2), CostCategory.AI, context())
    assert recording.record.estimated_cost == money(3)
    assert recording.record.actual_cost == money(2)
    assert recording.record.variance == money(-1)
    assert recording.issues == ()
    assert recording.budget.outstanding == ()
    assert recording.budget.ai_committed(context().occurred_at) == money(2)
    assert recording.budget.ai_spent(context().occurred_at) == money(2)


def test_per_task_limit_counts_all_categories_and_outstanding_estimates() -> None:
    budget = Budget(policy()).authorize(money(5), CostCategory.AI, context()).budget
    budget = budget.record(money(5), CostCategory.AI, context()).budget
    budget = budget.authorize(money(5), CostCategory.TOOL, context("second")).budget
    decision = budget.authorize(money("0.01"), CostCategory.TRANSACTION, context("third"))
    assert decision.status == AuthorizationStatus.DENIED
    assert decision.reason == BudgetReason.TASK_LIMIT
    assert decision.budget is budget
    assert (
        budget.authorize(money(1), CostCategory.AI, context("other", task="task-2")).status
        == AuthorizationStatus.AUTHORIZED
    )


def test_daily_limit_counts_estimates_and_actuals() -> None:
    settings = replace(
        policy(), max_cost_per_task=money(30), human_approval_cost_threshold=money(30)
    )
    budget = Budget(settings).authorize(money(12), CostCategory.AI, context()).budget
    decision = budget.authorize(money(9), CostCategory.AI, context("second", task="task-2"))
    assert decision.reason == BudgetReason.DAILY_LIMIT
    assert decision.status == AuthorizationStatus.DENIED
    exact = budget.authorize(money(8), CostCategory.AI, context("second", task="task-2"))
    assert exact.status == AuthorizationStatus.AUTHORIZED
    assert exact.budget.operating_mode(context().occurred_at) == OperatingMode.SCOUT_ONLY


def test_monthly_limit_survives_day_rollover() -> None:
    settings = replace(
        policy(),
        monthly_ai_budget=money(10),
        daily_ai_budget=money(20),
        human_approval_cost_threshold=money(10),
    )
    decision = Budget(settings).authorize(money(6), CostCategory.AI, context())
    budget = decision.budget.record(money(6), CostCategory.AI, context()).budget
    denied = budget.authorize(money(5), CostCategory.AI, context("second", day=14, task="task-2"))
    assert denied.status == AuthorizationStatus.DENIED
    assert denied.reason == BudgetReason.MONTHLY_LIMIT


def test_saver_transition_and_stricter_ai_spending() -> None:
    settings = replace(policy(), daily_ai_budget=money(10), human_approval_cost_threshold=money(10))
    decision = Budget(settings).authorize(money(8), CostCategory.AI, context())
    budget = decision.budget.record(money(8), CostCategory.AI, context()).budget
    assert budget.operating_mode(context().occurred_at) == OperatingMode.SAVER
    assert budget.operating_mode(context().occurred_at).prefers_deterministic
    stricter = budget.with_requested_mode(OperatingMode.SAVER).with_policy(
        replace(settings, daily_ai_budget=money(20))
    )
    denied = stricter.authorize(money(6), CostCategory.AI, context("second", task="task-2"))
    assert denied.reason == BudgetReason.SAVER_LIMIT
    cheap = stricter.authorize(money(1), CostCategory.AI, context("cheap", task="task-2"))
    assert cheap.status == AuthorizationStatus.AUTHORIZED
    deterministic = stricter.authorize(money(0), CostCategory.TOOL, context("deterministic"))
    assert deterministic.status == AuthorizationStatus.AUTHORIZED


@pytest.mark.parametrize("category", list(CostCategory))
def test_exhaustion_denies_all_new_paid_operations(category: CostCategory) -> None:
    settings = replace(policy(), daily_ai_budget=money(5))
    first = Budget(settings).authorize(money(5), CostCategory.AI, context())
    budget = first.budget.record(money(5), CostCategory.AI, context()).budget
    decision = budget.authorize(money("0.01"), category, context("second", task="task-2"))
    assert decision.status == AuthorizationStatus.DENIED
    assert decision.mode == OperatingMode.SCOUT_ONLY


@pytest.mark.parametrize("operation", list(OperationType))
def test_free_operations_continue_when_ai_budget_is_zero(operation: OperationType) -> None:
    settings = replace(policy(), monthly_ai_budget=money(0), daily_ai_budget=money(0))
    request_context = replace(context(), operation=operation)
    decision = Budget(settings).authorize(money(0), CostCategory.TOOL, request_context)
    assert decision.status == AuthorizationStatus.AUTHORIZED
    assert decision.mode == OperatingMode.SCOUT_ONLY


def test_explicit_scout_mode_and_restore_to_full() -> None:
    budget = Budget(policy(), OperatingMode.SCOUT_ONLY)
    assert (
        budget.authorize(money(1), CostCategory.AI, context()).status == AuthorizationStatus.DENIED
    )
    assert (
        budget.with_requested_mode(OperatingMode.FULL)
        .authorize(money(1), CostCategory.AI, context())
        .status
        == AuthorizationStatus.AUTHORIZED
    )


def test_human_threshold_requires_approval_without_reserving_and_cannot_override_limits() -> None:
    budget = Budget(policy())
    decision = budget.authorize(money(6), CostCategory.AI, context())
    assert decision.status == AuthorizationStatus.REQUIRES_HUMAN_APPROVAL
    assert decision.budget is budget and budget.outstanding == ()
    approved_context = replace(context(), human_approval=Reference("human-approval"))
    assert (
        budget.authorize(money(6), CostCategory.AI, approved_context).status
        == AuthorizationStatus.AUTHORIZED
    )
    assert (
        budget.authorize(money(11), CostCategory.AI, approved_context).reason
        == BudgetReason.TASK_LIMIT
    )
    assert (
        budget.authorize(money(5), CostCategory.AI, context()).status
        == AuthorizationStatus.AUTHORIZED
    )


def test_actual_above_estimate_is_retained_and_flags_all_breached_limits() -> None:
    settings = replace(
        policy(), monthly_ai_budget=money(6), daily_ai_budget=money(5), max_cost_per_task=money(4)
    )
    decision = Budget(settings).authorize(money(3), CostCategory.AI, context())
    result = decision.budget.record(money(7), CostCategory.AI, context())
    assert result.record.actual_cost == money(7)
    assert result.record.estimated_cost == money(3)
    assert result.record.variance == money(4)
    assert set(result.issues) == {
        RecordingIssue.ESTIMATE_EXCEEDED,
        RecordingIssue.TASK_LIMIT_EXCEEDED,
        RecordingIssue.DAILY_LIMIT_EXCEEDED,
        RecordingIssue.MONTHLY_LIMIT_EXCEEDED,
    }
    assert result.budget.operating_mode(context().occurred_at) == OperatingMode.SCOUT_ONLY
    assert (
        result.budget.authorize(money(1), CostCategory.AI, context("next")).status
        == AuthorizationStatus.DENIED
    )
    assert (
        result.budget.authorize(money(0), CostCategory.TOOL, context("free")).status
        == AuthorizationStatus.AUTHORIZED
    )


def test_unestimated_actual_cost_is_recorded_as_unauthorized() -> None:
    result = Budget(policy()).record(money(2), CostCategory.AI, context())
    assert result.record.estimated_cost is None
    assert result.record.variance is None
    assert result.issues == (RecordingIssue.UNAUTHORIZED_COST,)


def test_daily_and_monthly_budget_restoration_preserves_history() -> None:
    settings = replace(policy(), daily_ai_budget=money(5), monthly_ai_budget=money(5))
    budget = Budget(settings).authorize(money(5), CostCategory.AI, context()).budget
    budget = budget.record(money(5), CostCategory.AI, context()).budget
    tomorrow = context().occurred_at + timedelta(days=1)
    assert (
        budget.operating_mode(tomorrow) == OperatingMode.SCOUT_ONLY
    )  # Monthly budget still exhausted.
    next_month = datetime(2026, 11, 1, tzinfo=UTC)
    assert budget.operating_mode(next_month) == OperatingMode.FULL
    restored = budget.with_policy(
        replace(settings, daily_ai_budget=money(20), monthly_ai_budget=money(100))
    )
    assert restored.records == budget.records
    assert restored.operating_mode(context().occurred_at) == OperatingMode.FULL
    assert (
        restored.authorize(money(1), CostCategory.AI, context("next", task="task-2")).status
        == AuthorizationStatus.AUTHORIZED
    )


def test_daily_reset_does_not_reset_lifetime_task_limit() -> None:
    budget = Budget(policy()).authorize(money(5), CostCategory.AI, context()).budget
    budget = budget.record(money(5), CostCategory.AI, context()).budget
    assert budget.ai_committed(context(day=14).occurred_at) == money(0)
    approved = replace(context("next", day=14), human_approval=Reference("approval"))
    assert budget.authorize(money(6), CostCategory.AI, approved).reason == BudgetReason.TASK_LIMIT


def test_outstanding_commitments_carry_across_periods_and_can_be_released() -> None:
    budget = Budget(policy()).authorize(money(5), CostCategory.AI, context()).budget
    next_month = datetime(2026, 11, 1, tzinfo=UTC)
    assert budget.ai_committed(next_month) == money(5)
    released = budget.release(context().operation_reference)
    assert released.ai_committed(next_month) == money(0)
    assert released.release(context().operation_reference) is released
    with pytest.raises(DomainError):
        released.authorize(money(5), CostCategory.AI, context())
    assert released.record(money(2), CostCategory.AI, context()).issues == (
        RecordingIssue.UNAUTHORIZED_COST,
    )


def test_authorization_and_recording_are_idempotent_and_reject_conflicts() -> None:
    decision = Budget(policy()).authorize(money(3), CostCategory.AI, context())
    retry = decision.budget.authorize(money(3), CostCategory.AI, context())
    assert retry.budget is decision.budget
    assert len(retry.budget.outstanding) == 1
    with pytest.raises(DomainError) as error:
        retry.budget.authorize(money(4), CostCategory.AI, context())
    assert error.value.code == ErrorCode.DUPLICATE_REFERENCE
    recorded = retry.budget.record(money(2), CostCategory.AI, context())
    assert recorded.budget.record(money(2), CostCategory.AI, context()).budget is recorded.budget
    with pytest.raises(DomainError):
        recorded.budget.record(money(3), CostCategory.AI, context())
    with pytest.raises(DomainError):
        recorded.budget.authorize(money(3), CostCategory.AI, context())
    with pytest.raises(DomainError):
        decision.budget.record(money(2), CostCategory.TOOL, context())
    with pytest.raises(DomainError):
        decision.budget.record(money(2), CostCategory.AI, context(task="other"))


def test_calendar_timezone_controls_daily_cutover() -> None:
    settings = replace(policy(), calendar_timezone=timezone(timedelta(hours=7)))
    before = replace(context(), occurred_at=datetime(2026, 10, 13, 16, 59, tzinfo=UTC))
    budget = Budget(settings).authorize(money(2), CostCategory.AI, before).budget
    budget = budget.record(money(2), CostCategory.AI, before).budget
    after = datetime(2026, 10, 13, 17, 0, tzinfo=UTC)
    assert budget.ai_committed(after) == money(0)
    assert budget.ai_committed(after, monthly=True) == money(2)


@pytest.mark.parametrize(
    "field",
    ["monthly_ai_budget", "daily_ai_budget", "max_cost_per_task", "human_approval_cost_threshold"],
)
def test_policy_limits_cannot_be_negative_or_mixed_currency(field: str) -> None:
    changes: dict[str, Callable[[Money], BudgetPolicy]] = {
        "monthly_ai_budget": lambda value: replace(policy(), monthly_ai_budget=value),
        "daily_ai_budget": lambda value: replace(policy(), daily_ai_budget=value),
        "max_cost_per_task": lambda value: replace(policy(), max_cost_per_task=value),
        "human_approval_cost_threshold": lambda value: replace(
            policy(), human_approval_cost_threshold=value
        ),
    }
    with pytest.raises(DomainError):
        changes[field](money(-1))
    with pytest.raises(DomainError):
        changes[field](Money(Decimal(1), "EUR"))


@pytest.mark.parametrize("ratio", ["0", "1", "-1", "NaN", "Infinity"])
def test_invalid_saver_ratios(ratio: str) -> None:
    with pytest.raises(DomainError):
        replace(policy(), saver_remaining_ratio=Decimal(ratio))
    with pytest.raises(DomainError):
        replace(policy(), saver_ai_cost_factor=Decimal(ratio))


def test_invalid_input_cannot_bypass_domain_rules() -> None:
    budget = Budget(policy())
    with pytest.raises(DomainError):
        budget.authorize(money(-1), CostCategory.AI, context())
    with pytest.raises(DomainError):
        budget.record(money(-1), CostCategory.AI, context())
    with pytest.raises(DomainError):
        budget.authorize(Money(Decimal(1), "EUR"), CostCategory.AI, context())
    with pytest.raises(DomainError):
        budget.record(Money(Decimal(1), "EUR"), CostCategory.AI, context())
    with pytest.raises(DomainError):
        Budget(policy(), cast(OperatingMode, "full"))
    with pytest.raises(DomainError):
        replace(context(), occurred_at=datetime(2026, 10, 13))
    with pytest.raises(DomainError):
        replace(context(), task_reference=None)
    with pytest.raises((ValueError, TypeError)):
        replace(budget, records=())


def test_pending_authorization_cannot_bypass_manual_scout_or_actual_overrun() -> None:
    first = Budget(policy()).authorize(money(3), CostCategory.AI, context())
    second_context = context("second", task="task-2")
    budget = first.budget.authorize(money(3), CostCategory.AI, second_context).budget
    manual = budget.with_requested_mode(OperatingMode.SCOUT_ONLY)
    assert (
        manual.authorize(money(3), CostCategory.AI, second_context).status
        == AuthorizationStatus.DENIED
    )
    overdrawn = budget.record(money(21), CostCategory.AI, context()).budget
    assert (
        overdrawn.authorize(money(3), CostCategory.AI, second_context).status
        == AuthorizationStatus.DENIED
    )
    restored = overdrawn.with_policy(replace(policy(), daily_ai_budget=money(30)))
    retry = restored.authorize(money(3), CostCategory.AI, second_context)
    assert retry.status == AuthorizationStatus.AUTHORIZED
    assert len(retry.budget.outstanding) == 1
