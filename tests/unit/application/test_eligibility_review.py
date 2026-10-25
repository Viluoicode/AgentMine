"""Human eligibility review is distinct from deliverable/submission approval."""

from dataclasses import dataclass, field, replace

import pytest
from fakes import FakeOpportunities
from test_eligibility_use_case import Case, case

from agentmine.application.contracts.eligibility import EligibilityReview, EligibilityReviewCommit
from agentmine.application.contracts.records import OpportunitySave
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.eligibility_review import (
    PrepareEligibilityReview,
    ResolveEligibilityReview,
)
from agentmine.domain.eligibility import SubmissionSupport
from agentmine.domain.eligibility_review import (
    EligibilityChoice,
    EligibilityResolution,
    ManualEligibilityEvidence,
)
from agentmine.domain.errors import DomainError
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import EligibilityReason, EligibilityStatus

__all__ = ["case"]


@dataclass
class MemoryReviews:
    opportunities: FakeOpportunities
    reviews: dict[Reference, EligibilityReview] = field(default_factory=dict)
    decisions: dict[Reference, EligibilityResolution] = field(default_factory=dict)

    def save_review(self, review: EligibilityReview) -> None:
        if review.reference in self.reviews and self.reviews[review.reference] != review:
            raise PortError(PortErrorCode.CONFLICT, "review", "Identity changed")
        self.reviews[review.reference] = review

    def get_review(self, reference: Reference) -> EligibilityReview | None:
        return self.reviews.get(reference)

    def get_resolution(self, reference: Reference) -> EligibilityResolution | None:
        return self.decisions.get(reference)

    def resolve(self, commit: EligibilityReviewCommit) -> None:
        prior = self.decisions.get(commit.review.reference)
        if prior is not None:
            if prior != commit.resolution:
                raise PortError(PortErrorCode.CONFLICT, "review", "Already decided")
            return
        snapshot = commit.review.opportunity_snapshot
        if self.opportunities.get(snapshot.value.reference) != snapshot:
            raise PortError(PortErrorCode.CONFLICT, "review", "Stale snapshot")
        self.opportunities.save(OpportunitySave(commit.opportunity, snapshot.revision))
        self.decisions[commit.review.reference] = commit.resolution


def test_manual_pending_has_supported_application_resolution(case: Case) -> None:
    request = replace(
        case.request, facts=replace(case.request.facts, submission=SubmissionSupport.MANUAL)
    )
    for _ in range(2):
        pending = case.checker.execute(request)
        assert pending.state == OpportunityState.ELIGIBILITY_CHECK
        assert pending.eligibility is not None
        assert pending.eligibility.status == EligibilityStatus.REQUIRES_HUMAN_REVIEW
        assert pending.eligibility.reasons == (EligibilityReason.MANUAL_SUBMISSION_REQUIRED,)
    case.source.terms_reference = Reference("source:terms-1")
    case.source.requirements = "Documented manual report submission"
    reviews = MemoryReviews(case.repository)
    review = PrepareEligibilityReview(case.repository, reviews, case.source, case.clock).execute(
        Reference("review"), request, case.checker.engine.policy
    )
    evidence = ManualEligibilityEvidence(
        Reference("manual:target"),
        Reference("instructions:proof"),
        Reference("access:proof"),
        Reference("requirements:proof"),
        True,
    )
    decision = ResolveEligibilityReview(
        case.repository, reviews, case.source, case.clock, Reference("operator")
    ).execute(review.reference, EligibilityChoice.APPROVE, "Manual requirements checked", evidence)
    op = case.repository.get(request.facts.opportunity_reference)
    assert op is not None and op.value.state == OpportunityState.ELIGIBLE
    assert op.value.approval is None and op.value.submission is None
    assert decision.evidence == evidence and decision.actor == Reference("operator")


@pytest.mark.parametrize("satisfied", [False, None, 1])
def test_manual_readiness_cannot_guess_satisfaction(satisfied: object) -> None:
    with pytest.raises(DomainError):
        ManualEligibilityEvidence(
            Reference("target"),
            Reference("instructions"),
            Reference("access"),
            Reference("requirements"),
            satisfied,  # type: ignore[arg-type]
        )
