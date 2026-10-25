"""Audited manual-channel eligibility resolution; no deliverable approval or spend."""

import logging
from dataclasses import dataclass

from agentmine.application.contracts.eligibility import (
    EligibilityCheckRequest,
    EligibilityReview,
    EligibilityReviewCommit,
    RecordedEligibilityReview,
)
from agentmine.application.contracts.records import OpportunitySave
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.eligibility_review import EligibilityReviewRepository
from agentmine.application.ports.repositories import OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.context import load, observe_status
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.eligibility_review import (
    EligibilityChoice,
    EligibilityResolution,
    ManualEligibilityEvidence,
)
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import EligibilityStatus


def conflict(message: str) -> PortError:
    return PortError(PortErrorCode.CONFLICT, "eligibility_review", message)


@dataclass(frozen=True, slots=True)
class PrepareEligibilityReview:
    opportunities: OpportunityRepository
    reviews: EligibilityReviewRepository
    source: OpportunitySource
    clock: Clock

    def execute(
        self, reference: Reference, request: EligibilityCheckRequest, policy: EligibilityPolicy
    ) -> EligibilityReview:
        existing = self.reviews.get_review(reference)
        if existing is not None:
            if (
                request.refreshed(existing.inspection.source) != existing.inspection.request
                or policy != existing.policy
            ):
                raise conflict("Review identity reused")
            return existing
        previous = load(self.opportunities, request.facts.opportunity_reference)
        if previous.value.state not in (
            OpportunityState.NORMALIZED,
            OpportunityState.ELIGIBILITY_CHECK,
        ):
            raise conflict("Normalized or pending opportunity required")
        inspection = CheckEligibility(
            self.opportunities, self.source, self.clock, EligibilityEngine(policy)
        ).inspect(request)
        checking = previous.value
        if checking.state == OpportunityState.NORMALIZED:
            checking = checking.check_eligibility()
        if checking.eligibility != inspection.result:
            checking = checking.assess_eligibility(inspection.result)
        # A new reviewed context invalidates older facts/profile/policy snapshots,
        # even when they happen to produce the same reason codes.
        previous = self.opportunities.save(OpportunitySave(checking, previous.revision))
        if inspection.result.status not in (
            EligibilityStatus.UNKNOWN,
            EligibilityStatus.REQUIRES_HUMAN_REVIEW,
        ):
            raise conflict("Deterministic eligibility recorded; no pending human review")
        review = EligibilityReview(reference, previous, inspection, policy)
        self.reviews.save_review(review)
        return review


@dataclass(frozen=True, slots=True)
class GetEligibilityReview:
    reviews: EligibilityReviewRepository

    def execute(self, reference: Reference) -> RecordedEligibilityReview:
        review = self.reviews.get_review(reference)
        if review is None:
            raise PortError(PortErrorCode.UNAVAILABLE, "eligibility_review", "Review missing")
        return RecordedEligibilityReview(review, self.reviews.get_resolution(reference))


@dataclass(frozen=True, slots=True)
class ResolveEligibilityReview:
    opportunities: OpportunityRepository
    reviews: EligibilityReviewRepository
    source: OpportunitySource
    clock: Clock
    operator: Reference

    def execute(
        self,
        reference: Reference,
        choice: EligibilityChoice,
        rationale: str,
        evidence: ManualEligibilityEvidence | None = None,
    ) -> EligibilityResolution:
        review = GetEligibilityReview(self.reviews).execute(reference)
        prior = review.resolution
        decision = EligibilityResolution(
            reference,
            self.operator,
            self.clock.now() if prior is None else prior.decided_at,
            choice,
            rationale,
            evidence,
        )
        if prior is not None:
            if prior != decision:
                raise conflict("Eligibility review already decided")
            return prior  # Readback, not a new grant; never rewrite a later lifecycle.
        snapshot = review.review.opportunity_snapshot
        if load(self.opportunities, snapshot.value.reference) != snapshot:
            raise conflict("Opportunity changed; prepare a new eligibility review")
        original = review.review.inspection
        fresh = observe_status(
            self.opportunities, self.source, self.clock, snapshot.value.reference
        )
        if (
            fresh.terms_reference is None
            or original.source.terms_reference is None
            or fresh.requirements is None
            or original.source.requirements is None
            or fresh.terms_reference != original.source.terms_reference
            or fresh.requirements != original.source.requirements
            or fresh.source_reference != original.source.source_reference
            or fresh.is_open != original.source.is_open
            or fresh.deadline_known != original.source.deadline_known
            or fresh.deadline != original.source.deadline
        ):
            raise conflict("Source context unknown or changed; prepare a fresh evidenced review")
        now = self.clock.now()
        decision = EligibilityResolution(reference, self.operator, now, choice, rationale, evidence)
        request = original.request.refreshed(fresh)
        recomputed = EligibilityEngine(review.review.policy).evaluate(
            request.facts, request.profile, now
        )
        resolved = decision.resolve(recomputed)
        commit = EligibilityReviewCommit(review.review, decision, resolved)
        self.reviews.resolve(commit)
        logging.getLogger(__name__).info(
            "eligibility_resolution_recorded",
            extra={
                "review_reference": reference.value,
                "actor": self.operator.value,
                "decision": choice.value,
            },
        )
        return decision
