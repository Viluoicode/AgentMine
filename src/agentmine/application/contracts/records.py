"""Application audit records and optimistic-write contracts, without storage schemas."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from agentmine.domain.budget import AuthorizationDecision, Budget, CostRecording
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import ExpectedValue
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.domain.work import Eligibility


@dataclass(frozen=True, slots=True)
class Versioned[T]:
    value: T
    revision: int

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision < 1:
            raise DomainError(ErrorCode.INVALID_VALUE, "revision", "Positive revision required")


def _validate_expected_revision(revision: int | None) -> None:
    if revision is not None and (type(revision) is not int or revision < 1):
        raise DomainError(ErrorCode.INVALID_VALUE, "revision", "Positive revision or None required")


@dataclass(frozen=True, slots=True)
class OpportunitySave:
    opportunity: Opportunity
    expected_revision: int | None

    def __post_init__(self) -> None:
        _validate_expected_revision(self.expected_revision)


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """Final application assessment; AI advice alone is not a persisted decision."""

    reference: Reference
    opportunity_reference: Reference
    eligibility: Eligibility
    expected_value: ExpectedValue
    score: Decimal
    evaluated_at: datetime
    evidence: tuple[Reference, ...]

    def __post_init__(self) -> None:
        require_aware_timestamp(self.evaluated_at)
        if not isinstance(self.score, Decimal) or not self.score.is_finite() or self.score < 0:
            raise DomainError(ErrorCode.INVALID_VALUE, "score", "Finite nonnegative score required")


@dataclass(frozen=True, slots=True)
class BudgetCommit:
    """Commit a full budget snapshot and its decision/measurement audit atomically."""

    ledger_reference: Reference
    budget: Budget
    expected_revision: int | None
    audit_event: AuthorizationDecision | CostRecording | None

    def __post_init__(self) -> None:
        _validate_expected_revision(self.expected_revision)
        if self.audit_event is not None and self.audit_event.budget != self.budget:
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "budget", "Audit snapshot mismatch")
