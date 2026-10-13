"""Budget authorization and actual accounting without I/O or a global clock."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, tzinfo
from decimal import Decimal, localcontext
from enum import StrEnum

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import Cost, CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import (
    AuthorizationStatus,
    BudgetReason,
    CostContext,
    CostRecord,
    RecordingIssue,
    SpendingRequest,
)
from agentmine.domain.values import Reference, require_aware_timestamp


class OperatingMode(StrEnum):
    FULL = "full"
    SAVER = "saver"
    SCOUT_ONLY = "scout_only"

    @property
    def prefers_deterministic(self) -> bool:
        return self != OperatingMode.FULL


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    monthly_ai_budget: Money
    daily_ai_budget: Money
    max_cost_per_task: Money
    human_approval_cost_threshold: Money
    saver_remaining_ratio: Decimal = Decimal("0.2")
    saver_ai_cost_factor: Decimal = Decimal("0.5")
    calendar_timezone: tzinfo = UTC

    def __post_init__(self) -> None:
        for name in (
            "monthly_ai_budget",
            "daily_ai_budget",
            "max_cost_per_task",
            "human_approval_cost_threshold",
        ):
            amount: Money = getattr(self, name)
            if not isinstance(amount, Money):
                raise DomainError(ErrorCode.INVALID_VALUE, name, "Money value required")
            amount.require_nonnegative(name)
            self.monthly_ai_budget.require_same_currency(amount)
        for name, ratio in (
            ("saver_remaining_ratio", self.saver_remaining_ratio),
            ("saver_ai_cost_factor", self.saver_ai_cost_factor),
        ):
            if not isinstance(ratio, Decimal) or not ratio.is_finite() or not 0 < ratio < 1:
                raise DomainError(
                    ErrorCode.INVALID_VALUE, name, "Ratio must be between zero and one"
                )
        if not isinstance(self.calendar_timezone, tzinfo):
            raise DomainError(ErrorCode.INVALID_VALUE, "calendar_timezone", "Timezone required")

    def scaled_amount(self, amount: Money, ratio: Decimal) -> Money:
        """Policy multiplication is independent of ambient Decimal precision."""
        with localcontext() as context:
            context.prec = len(amount.amount.as_tuple().digits) + len(ratio.as_tuple().digits) + 2
            return Money(amount.amount * ratio, amount.currency)


@dataclass(frozen=True, slots=True)
class BudgetAuthorization:
    request: SpendingRequest
    mode: OperatingMode
    policy: BudgetPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.request, SpendingRequest) or not isinstance(
            self.mode, OperatingMode
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "authorization", "Request and operating mode required"
            )
        self.policy.monthly_ai_budget.require_same_currency(self.request.estimated_cost)
        if self.mode == OperatingMode.SCOUT_ONLY and self.request.estimated_cost.amount > 0:
            raise DomainError(
                ErrorCode.EXECUTION_FORBIDDEN, "authorization", "SCOUT_ONLY forbids paid work"
            )


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    request: SpendingRequest
    status: AuthorizationStatus
    reason: BudgetReason
    mode: OperatingMode
    budget: Budget
    authorization: BudgetAuthorization | None = None


@dataclass(frozen=True, slots=True)
class CostRecording:
    budget: Budget
    record: CostRecord
    issues: tuple[RecordingIssue, ...]


@dataclass(frozen=True, slots=True)
class Budget:
    policy: BudgetPolicy
    requested_mode: OperatingMode = OperatingMode.FULL
    authorizations: tuple[BudgetAuthorization, ...] = field(default=(), init=False)
    records: tuple[CostRecord, ...] = field(default=(), init=False)
    released_operations: tuple[Reference, ...] = field(default=(), init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, BudgetPolicy) or not isinstance(
            self.requested_mode, OperatingMode
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "budget", "Policy and operating mode required"
            )

    @property
    def outstanding(self) -> tuple[BudgetAuthorization, ...]:
        settled = {record.context.operation_reference for record in self.records}
        return tuple(
            authorization
            for authorization in self.authorizations
            if authorization.request.context.operation_reference not in settled
            and authorization.request.context.operation_reference not in self.released_operations
        )

    def _total(
        self,
        *,
        category: CostCategory | None = None,
        at: datetime | None = None,
        monthly: bool = False,
        task: Reference | None = None,
        include_estimates: bool = True,
    ) -> Money:
        total = Money(Decimal(0), self.policy.monthly_ai_budget.currency)
        for record in self.records:
            if category is not None and record.cost.category != category:
                continue
            if task is not None and record.context.task_reference != task:
                continue
            if at is not None:
                local = record.context.occurred_at.astimezone(self.policy.calendar_timezone)
                current = at.astimezone(self.policy.calendar_timezone)
                if (local.year, local.month) != (current.year, current.month):
                    continue
                if not monthly and local.date() != current.date():
                    continue
            total = total + record.actual_cost
        if include_estimates:
            # Outstanding commitments carry across periods until settled/released.
            for authorization in self.outstanding:
                request = authorization.request
                if category is not None and request.category != category:
                    continue
                if task is not None and request.context.task_reference != task:
                    continue
                total = total + request.estimated_cost
        return total

    def ai_committed(self, at: datetime, *, monthly: bool = False) -> Money:
        require_aware_timestamp(at)
        return self._total(category=CostCategory.AI, at=at, monthly=monthly)

    def ai_spent(self, at: datetime, *, monthly: bool = False) -> Money:
        require_aware_timestamp(at)
        return self._total(
            category=CostCategory.AI, at=at, monthly=monthly, include_estimates=False
        )

    def operating_mode(self, at: datetime) -> OperatingMode:
        require_aware_timestamp(at)
        if self.requested_mode == OperatingMode.SCOUT_ONLY:
            return OperatingMode.SCOUT_ONLY
        constrained = False
        for limit, monthly in (
            (self.policy.daily_ai_budget, False),
            (self.policy.monthly_ai_budget, True),
        ):
            remaining = limit - self.ai_committed(at, monthly=monthly)
            if remaining.amount <= 0:
                return OperatingMode.SCOUT_ONLY
            if (
                remaining.amount
                <= self.policy.scaled_amount(limit, self.policy.saver_remaining_ratio).amount
            ):
                constrained = True
        return (
            OperatingMode.SAVER
            if constrained or self.requested_mode == OperatingMode.SAVER
            else OperatingMode.FULL
        )

    def authorize(
        self,
        estimated_cost: Money,
        category: CostCategory,
        context: CostContext,
    ) -> AuthorizationDecision:
        request = SpendingRequest(estimated_cost, category, context)
        self.policy.monthly_ai_budget.require_same_currency(estimated_cost)
        previous = next(
            (
                item
                for item in self.authorizations
                if item.request.context.operation_reference == context.operation_reference
            ),
            None,
        )
        if previous is not None:
            if (
                previous.request.estimated_cost != estimated_cost
                or previous.request.category != category
                or not previous.request.context.matches_operation(context)
            ):
                raise DomainError(
                    ErrorCode.DUPLICATE_REFERENCE, "operation", "Conflicting authorization"
                )
            if previous not in self.outstanding:
                raise DomainError(
                    ErrorCode.INVALID_TRANSITION, "operation", "Operation already settled/released"
                )
            if estimated_cost.amount > 0 and (
                self.requested_mode == OperatingMode.SCOUT_ONLY
                or self.ai_committed(context.occurred_at).amount
                > self.policy.daily_ai_budget.amount
                or self.ai_committed(context.occurred_at, monthly=True).amount
                > self.policy.monthly_ai_budget.amount
            ):
                return AuthorizationDecision(
                    request,
                    AuthorizationStatus.DENIED,
                    BudgetReason.SCOUT_ONLY,
                    OperatingMode.SCOUT_ONLY,
                    self,
                )
            return AuthorizationDecision(
                previous.request,
                AuthorizationStatus.AUTHORIZED,
                BudgetReason.AUTHORIZED,
                previous.mode,
                self,
                previous,
            )
        if any(
            record.context.operation_reference == context.operation_reference
            for record in self.records
        ):
            raise DomainError(
                ErrorCode.INVALID_TRANSITION, "operation", "Operation already recorded"
            )
        mode = self.operating_mode(context.occurred_at)
        reason: BudgetReason | None = None
        if estimated_cost.amount > 0:
            if mode == OperatingMode.SCOUT_ONLY:
                reason = BudgetReason.SCOUT_ONLY
            elif (
                context.task_reference is not None
                and (self._total(task=context.task_reference) + estimated_cost).amount
                > self.policy.max_cost_per_task.amount
            ):
                reason = BudgetReason.TASK_LIMIT
            elif category == CostCategory.AI:
                for limit, monthly, candidate in (
                    (self.policy.daily_ai_budget, False, BudgetReason.DAILY_LIMIT),
                    (self.policy.monthly_ai_budget, True, BudgetReason.MONTHLY_LIMIT),
                ):
                    if (
                        self.ai_committed(context.occurred_at, monthly=monthly) + estimated_cost
                    ).amount > limit.amount:
                        reason = candidate
                        break
                if (
                    reason is None
                    and mode == OperatingMode.SAVER
                    and estimated_cost.amount
                    > self.policy.scaled_amount(
                        self.policy.max_cost_per_task, self.policy.saver_ai_cost_factor
                    ).amount
                ):
                    reason = BudgetReason.SAVER_LIMIT
        if reason is not None:
            return AuthorizationDecision(request, AuthorizationStatus.DENIED, reason, mode, self)
        if (
            estimated_cost.amount > self.policy.human_approval_cost_threshold.amount
            and context.human_approval is None
        ):
            return AuthorizationDecision(
                request,
                AuthorizationStatus.REQUIRES_HUMAN_APPROVAL,
                BudgetReason.HUMAN_APPROVAL,
                mode,
                self,
            )
        authorization = BudgetAuthorization(request, mode, self.policy)
        updated = copy(self)
        object.__setattr__(updated, "authorizations", (*self.authorizations, authorization))
        return AuthorizationDecision(
            request,
            AuthorizationStatus.AUTHORIZED,
            BudgetReason.AUTHORIZED,
            mode,
            updated,
            authorization,
        )

    def release(self, operation_reference: Reference) -> Budget:
        if operation_reference in self.released_operations:
            return self
        if not any(
            item.request.context.operation_reference == operation_reference
            for item in self.outstanding
        ):
            raise DomainError(
                ErrorCode.INVALID_TRANSITION, "operation", "No outstanding authorization"
            )
        updated = copy(self)
        object.__setattr__(
            updated, "released_operations", (*self.released_operations, operation_reference)
        )
        return updated

    def with_policy(self, policy: BudgetPolicy) -> Budget:
        self.policy.monthly_ai_budget.require_same_currency(policy.monthly_ai_budget)
        return replace(self, policy=policy)._with_history(self)

    def with_requested_mode(self, mode: OperatingMode) -> Budget:
        return replace(self, requested_mode=mode)._with_history(self)

    def _with_history(self, original: Budget) -> Budget:
        object.__setattr__(self, "authorizations", original.authorizations)
        object.__setattr__(self, "records", original.records)
        object.__setattr__(self, "released_operations", original.released_operations)
        return self

    def record(
        self, actual_cost: Money, category: CostCategory, context: CostContext
    ) -> CostRecording:
        cost = Cost(context.operation_reference, actual_cost, category)
        self.policy.monthly_ai_budget.require_same_currency(actual_cost)
        previous = next(
            (item for item in self.records if item.cost.reference == cost.reference), None
        )
        if previous is not None:
            if previous.cost != cost or previous.context != context:
                raise DomainError(
                    ErrorCode.DUPLICATE_REFERENCE, "operation", "Conflicting actual cost"
                )
            return CostRecording(self, previous, self._recording_issues(previous))
        authorization = next(
            (
                item
                for item in self.authorizations
                if item.request.context.operation_reference == context.operation_reference
            ),
            None,
        )
        if authorization is not None and (
            authorization.request.category != category
            or not authorization.request.context.matches_operation(context)
            or context.occurred_at < authorization.request.context.occurred_at
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "context", "Actual cost scope/time mismatch"
            )
        estimate = None if authorization is None else authorization.request.estimated_cost
        record = CostRecord(cost, context, estimate)
        updated = copy(self)
        object.__setattr__(updated, "records", (*self.records, record))
        return CostRecording(updated, record, updated._recording_issues(record))

    def _recording_issues(self, record: CostRecord) -> tuple[RecordingIssue, ...]:
        issues: list[RecordingIssue] = []
        if record.actual_cost.amount > 0 and (
            record.estimated_cost is None or record.cost.reference in self.released_operations
        ):
            issues.append(RecordingIssue.UNAUTHORIZED_COST)
        if record.variance is not None and record.variance.amount > 0:
            issues.append(RecordingIssue.ESTIMATE_EXCEEDED)
        for limit, monthly, issue in (
            (self.policy.daily_ai_budget, False, RecordingIssue.DAILY_LIMIT_EXCEEDED),
            (self.policy.monthly_ai_budget, True, RecordingIssue.MONTHLY_LIMIT_EXCEEDED),
        ):
            if self.ai_committed(record.context.occurred_at, monthly=monthly).amount > limit.amount:
                issues.append(issue)
        if (
            record.context.task_reference is not None
            and self._total(task=record.context.task_reference).amount
            > self.policy.max_cost_per_task.amount
        ):
            issues.append(RecordingIssue.TASK_LIMIT_EXCEEDED)
        return tuple(issues)
