"""Operator policy consent and conservative budget recovery read models."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.runtime import RuntimeStatus
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.spending import CostRecord, SpendingRequest
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference


class PolicyConflictReason(StrEnum):
    NOT_FOUND = "not_found"
    IDENTITY_CONFLICT = "identity_conflict"
    STALE_REVISION = "stale_revision"
    ACTOR_MISMATCH = "actor_mismatch"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CURRENCY_FROZEN = "currency_frozen"
    TIMEZONE_FROZEN = "timezone_frozen"
    INVALID_PROPOSAL = "invalid_proposal"
    EVIDENCE_INVALID = "evidence_invalid"


class BudgetControlError(PortError):
    def __init__(self, reason: PolicyConflictReason) -> None:
        self.reason = reason
        super().__init__(PortErrorCode.CONFLICT, "budget_control", reason.value)


class BudgetRecoveryClassification(StrEnum):
    DETERMINISTIC_RUN = "deterministic_run"
    UNLINKED_OPERATION = "unlinked_operation"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    UNSUPPORTED_WAIT = "unsupported_wait"


@dataclass(frozen=True, slots=True)
class BudgetPolicyChange:
    reference: Reference
    ledger_reference: Reference
    actor: Reference
    prepared_at: datetime
    reason: str
    expected_revision: int
    before_policy: BudgetPolicy
    before_mode: OperatingMode
    proposed_policy: BudgetPolicy
    proposed_mode: OperatingMode

    def __post_init__(self) -> None:
        for name, value in (
            ("change", self.reference),
            ("ledger", self.ledger_reference),
            ("actor", self.actor),
        ):
            require_reference(value, name)
        require_aware_timestamp(self.prepared_at)
        if (
            type(self.expected_revision) is not int
            or self.expected_revision < 1
            or not isinstance(self.reason, str)
            or not self.reason.strip()
            or len(self.reason) > 4000
            or not isinstance(self.before_policy, BudgetPolicy)
            or not isinstance(self.proposed_policy, BudgetPolicy)
            or not isinstance(self.before_mode, OperatingMode)
            or not isinstance(self.proposed_mode, OperatingMode)
        ):
            raise BudgetControlError(PolicyConflictReason.INVALID_PROPOSAL)
        # Re-run Domain validation even when a caller supplies an existing object.
        replace(self.before_policy)
        replace(self.proposed_policy)
        if (
            self.before_policy.monthly_ai_budget.currency
            != self.proposed_policy.monthly_ai_budget.currency
        ):
            raise BudgetControlError(PolicyConflictReason.CURRENCY_FROZEN)
        old, new = self.before_policy.calendar_timezone, self.proposed_policy.calendar_timezone
        if type(old) is not type(new) or old != new or str(old) != str(new):
            raise BudgetControlError(PolicyConflictReason.TIMEZONE_FROZEN)

    def update(self, snapshot: Versioned[Budget]) -> Budget:
        if snapshot.revision != self.expected_revision:
            raise BudgetControlError(PolicyConflictReason.STALE_REVISION)
        if (
            snapshot.value.policy != self.before_policy
            or snapshot.value.requested_mode != self.before_mode
        ):
            raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
        return snapshot.value.with_policy(self.proposed_policy).with_requested_mode(
            self.proposed_mode
        )


@dataclass(frozen=True, slots=True)
class BudgetPolicyDecision:
    change_reference: Reference
    actor: Reference
    approved_at: datetime

    def __post_init__(self) -> None:
        require_reference(self.change_reference, "change")
        require_reference(self.actor, "actor")
        require_aware_timestamp(self.approved_at)


@dataclass(frozen=True, slots=True)
class BudgetPolicyChangeReceipt:
    change: BudgetPolicyChange
    decision: BudgetPolicyDecision
    resulting_revision: int

    def __post_init__(self) -> None:
        if (
            self.decision.change_reference != self.change.reference
            or self.decision.actor != self.change.actor
            or self.decision.approved_at < self.change.prepared_at
            or type(self.resulting_revision) is not int
            or self.resulting_revision != self.change.expected_revision + 1
        ):
            raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)


@dataclass(frozen=True, slots=True)
class BudgetPolicyApplication:
    """Internal commit command; never deserialize a Budget from operator input."""

    change: BudgetPolicyChange
    decision: BudgetPolicyDecision
    snapshot: Versioned[Budget]

    def __post_init__(self) -> None:
        _ = self.updated
        _ = self.receipt

    @property
    def updated(self) -> Budget:
        return self.change.update(self.snapshot)

    @property
    def receipt(self) -> BudgetPolicyChangeReceipt:
        return BudgetPolicyChangeReceipt(self.change, self.decision, self.snapshot.revision + 1)


@dataclass(frozen=True, slots=True)
class BudgetControlSnapshot:
    ledger: Versioned[Budget]
    opportunities: tuple[Opportunity, ...]
    runs: tuple[RuntimeStatus, ...]
    paid_evidence_operations: tuple[Reference, ...]


@dataclass(frozen=True, slots=True)
class BudgetRecoveryItem:
    operation_reference: Reference
    classification: BudgetRecoveryClassification
    request: SpendingRequest | None
    execution_reference: Reference | None
    opportunity_reference: Reference | None
    actual_cost: Money | None = None


@dataclass(frozen=True, slots=True)
class BudgetRecoveryView:
    ledger_reference: Reference
    revision: int
    observed_at: datetime
    policy: BudgetPolicy
    requested_mode: OperatingMode
    derived_mode: OperatingMode
    monthly_spent: Money
    daily_spent: Money
    reserved_ai: Money
    monthly_remaining: Money
    daily_remaining: Money
    actuals: tuple[CostRecord, ...]
    released_operations: tuple[Reference, ...]
    recovery: tuple[BudgetRecoveryItem, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BudgetPolicyChangeView:
    change: BudgetPolicyChange
    receipt: BudgetPolicyChangeReceipt | None
    current_revision: int
    stale: bool
    current: BudgetRecoveryView
    projected_mode: OperatingMode | None
    projected_monthly_remaining: Money | None
    projected_daily_remaining: Money | None
    projected_warnings: tuple[str, ...]
