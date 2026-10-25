"""Normalized business facts plus participant context, never an asserted outcome."""

from dataclasses import dataclass, replace
from datetime import datetime

from agentmine.application.contracts.opportunities import OpportunityStatus
from agentmine.application.contracts.records import Versioned
from agentmine.domain.eligibility import (
    Deadline,
    DeadlineKind,
    EligibilityFacts,
    EligibilityPolicy,
    ParticipantProfile,
)
from agentmine.domain.eligibility_review import EligibilityResolution
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Eligibility


@dataclass(frozen=True, slots=True)
class EligibilityCheckRequest:
    facts: EligibilityFacts
    profile: ParticipantProfile

    def refreshed(self, status: OpportunityStatus) -> "EligibilityCheckRequest":
        deadline = (
            Deadline()
            if not status.deadline_known
            else Deadline(DeadlineKind.AT, status.deadline)
            if status.deadline is not None
            else Deadline(DeadlineKind.NONE)
        )
        return replace(self, facts=replace(self.facts, is_open=status.is_open, deadline=deadline))


@dataclass(frozen=True, slots=True)
class EligibilityInspection:
    request: EligibilityCheckRequest
    source: OpportunityStatus
    result: Eligibility
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class EligibilityReview:
    reference: Reference
    opportunity_snapshot: Versioned[Opportunity]
    inspection: EligibilityInspection
    policy: EligibilityPolicy
    rules_version: str = EligibilityEngine.VERSION

    def __post_init__(self) -> None:
        require_reference(self.reference, "eligibility_review")
        if self.rules_version != EligibilityEngine.VERSION:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "eligibility_rules", "Unsupported rules version"
            )
        require_aware_timestamp(self.inspection.checked_at)
        op = self.opportunity_snapshot.value
        result = EligibilityEngine(self.policy).evaluate(
            self.inspection.request.facts,
            self.inspection.request.profile,
            self.inspection.checked_at,
        )
        if (
            op.state != OpportunityState.ELIGIBILITY_CHECK
            or op.reference != self.inspection.request.facts.opportunity_reference
            or self.inspection.source.opportunity_reference != op.reference
            or self.inspection.result != result
            or op.eligibility != result
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "eligibility_review", "Matching pending facts required"
            )


@dataclass(frozen=True, slots=True)
class EligibilityReviewCommit:
    review: EligibilityReview
    resolution: EligibilityResolution
    result: Eligibility

    def __post_init__(self) -> None:
        inspection = self.review.inspection
        expected = self.resolution.resolve(
            EligibilityEngine(self.review.policy).evaluate(
                inspection.request.facts, inspection.request.profile, self.resolution.decided_at
            )
        )
        if (
            self.resolution.review_reference != self.review.reference
            or self.result != expected
            or self.resolution.decided_at < inspection.checked_at
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "eligibility_resolution", "Matching result required"
            )

    @property
    def opportunity(self) -> Opportunity:
        return self.review.opportunity_snapshot.value.assess_eligibility(self.result)


@dataclass(frozen=True, slots=True)
class RecordedEligibilityReview:
    review: EligibilityReview
    resolution: EligibilityResolution | None
