"""Explicit estimates, actual measurements and operation identities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import Cost, CostCategory
from agentmine.domain.money import Money
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference


class OperationType(StrEnum):
    INGESTION = "ingestion"
    NORMALIZATION = "normalization"
    ELIGIBILITY = "eligibility"
    SCORING = "scoring"
    OUTCOME_TRACKING = "outcome_tracking"
    TASK_EXECUTION = "task_execution"
    QA = "qa"


@dataclass(frozen=True, slots=True)
class CostContext:
    operation_reference: Reference
    operation: OperationType
    occurred_at: datetime
    task_reference: Reference | None = None
    opportunity_reference: Reference | None = None
    human_approval: Reference | None = None

    def __post_init__(self) -> None:
        require_reference(self.operation_reference, "operation_reference")
        require_aware_timestamp(self.occurred_at)
        if not isinstance(self.operation, OperationType):
            raise DomainError(ErrorCode.INVALID_VALUE, "operation", "Unknown operation")
        for name, reference in (
            ("task_reference", self.task_reference),
            ("opportunity_reference", self.opportunity_reference),
            ("human_approval", self.human_approval),
        ):
            if reference is not None:
                require_reference(reference, name)
        if self.operation in (OperationType.TASK_EXECUTION, OperationType.QA) and (
            self.task_reference is None or self.opportunity_reference is None
        ):
            raise DomainError(ErrorCode.INVALID_VALUE, "context", "Task and opportunity required")

    def matches_operation(self, other: CostContext) -> bool:
        """Measurement time may differ; identity, scope and approval must match."""
        return (
            self.operation_reference == other.operation_reference
            and self.operation == other.operation
            and self.task_reference == other.task_reference
            and self.opportunity_reference == other.opportunity_reference
            and self.human_approval == other.human_approval
        )


@dataclass(frozen=True, slots=True)
class SpendingRequest:
    estimated_cost: Money
    category: CostCategory
    context: CostContext

    def __post_init__(self) -> None:
        self.estimated_cost.require_nonnegative("estimated_cost")
        if not isinstance(self.category, CostCategory) or not isinstance(self.context, CostContext):
            raise DomainError(ErrorCode.INVALID_VALUE, "request", "Category and context required")


class AuthorizationStatus(StrEnum):
    AUTHORIZED = "authorized"
    DENIED = "denied"
    REQUIRES_HUMAN_APPROVAL = "requires_human_approval"


class BudgetReason(StrEnum):
    AUTHORIZED = "authorized"
    SCOUT_ONLY = "scout_only"
    DAILY_LIMIT = "daily_limit"
    MONTHLY_LIMIT = "monthly_limit"
    TASK_LIMIT = "task_limit"
    SAVER_LIMIT = "saver_limit"
    HUMAN_APPROVAL = "human_approval"


@dataclass(frozen=True, slots=True)
class CostRecord:
    """An actual cost, optionally linked to a prior estimate."""

    cost: Cost
    context: CostContext
    estimated_cost: Money | None

    def __post_init__(self) -> None:
        if self.cost.reference != self.context.operation_reference:
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "cost", "Operation identity mismatch")
        if self.estimated_cost is not None:
            self.estimated_cost.require_nonnegative("estimated_cost")
            self.cost.amount.require_same_currency(self.estimated_cost)

    @property
    def actual_cost(self) -> Money:
        return self.cost.amount

    @property
    def variance(self) -> Money | None:
        return None if self.estimated_cost is None else self.actual_cost - self.estimated_cost


class RecordingIssue(StrEnum):
    UNAUTHORIZED_COST = "unauthorized_cost"
    ESTIMATE_EXCEEDED = "estimate_exceeded"
    DAILY_LIMIT_EXCEEDED = "daily_limit_exceeded"
    MONTHLY_LIMIT_EXCEEDED = "monthly_limit_exceeded"
    TASK_LIMIT_EXCEEDED = "task_limit_exceeded"
