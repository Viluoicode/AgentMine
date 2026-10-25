"""Discovery facts are observations, not eligibility or economic decisions."""

from dataclasses import dataclass
from datetime import datetime

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    limit: int
    continuation: Reference | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or self.limit < 1:
            raise DomainError(ErrorCode.INVALID_VALUE, "limit", "Positive batch limit required")


@dataclass(frozen=True, slots=True)
class OpportunityObservation:
    opportunity: Opportunity
    source_reference: Reference
    requirements: str
    observed_at: datetime
    is_open: bool | None
    deadline: datetime | None
    deadline_known: bool = True

    def __post_init__(self) -> None:
        require_aware_timestamp(self.observed_at)
        _validate_status(self.is_open, self.deadline, self.deadline_known)
        if self.deadline is not None:
            require_aware_timestamp(self.deadline)


@dataclass(frozen=True, slots=True)
class OpportunityBatch:
    observations: tuple[OpportunityObservation, ...]
    continuation: Reference | None = None


@dataclass(frozen=True, slots=True)
class RefreshOpportunityRequest:
    opportunity_reference: Reference
    source_reference: Reference


@dataclass(frozen=True, slots=True)
class OpportunityStatus:
    opportunity_reference: Reference
    source_reference: Reference
    observed_at: datetime
    is_open: bool | None
    deadline: datetime | None
    deadline_known: bool = True
    terms_reference: Reference | None = None
    requirements: str | None = None

    def __post_init__(self) -> None:
        require_aware_timestamp(self.observed_at)
        if self.terms_reference is not None:
            require_reference(self.terms_reference, "source_terms")
        if self.requirements is not None and (
            not isinstance(self.requirements, str) or not self.requirements.strip()
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "requirements", "Source text or unknown required"
            )
        _validate_status(self.is_open, self.deadline, self.deadline_known)
        if self.deadline is not None:
            require_aware_timestamp(self.deadline)


def _validate_status(is_open: bool | None, deadline: datetime | None, deadline_known: bool) -> None:
    if (is_open is not None and type(is_open) is not bool) or type(deadline_known) is not bool:
        raise DomainError(ErrorCode.INVALID_VALUE, "status", "Explicit status knowledge required")
    if not deadline_known and deadline is not None:
        raise DomainError(
            ErrorCode.INVALID_VALUE, "deadline", "Unknown deadline cannot carry a date"
        )
