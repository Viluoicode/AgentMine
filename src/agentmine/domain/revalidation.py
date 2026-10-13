"""Caller-supplied fresh facts required to resume work after a budget wait."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import ExpectedValue
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Eligibility


@dataclass(frozen=True, slots=True)
class ResumeAssessment:
    opportunity_reference: Reference
    refreshed_at: datetime
    is_open: bool
    deadline: datetime | None
    eligibility: Eligibility | None = None
    expected_value: ExpectedValue | None = None
    score: Decimal | None = None
    human_approval: Reference | None = None

    def __post_init__(self) -> None:
        require_reference(self.opportunity_reference, "opportunity_reference")
        require_aware_timestamp(self.refreshed_at)
        if self.human_approval is not None:
            require_reference(self.human_approval, "human_approval")
        if self.deadline is not None:
            require_aware_timestamp(self.deadline)
        if type(self.is_open) is not bool:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "is_open", "Explicit refreshed status required"
            )
        if self.score is not None and (
            not isinstance(self.score, Decimal) or not self.score.is_finite() or self.score < 0
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "score", "Score must be finite and nonnegative"
            )
