"""Fresh deterministic runtime checks without mutating a planned/active lifecycle."""

from dataclasses import dataclass, replace

from agentmine.application.contracts.eligibility import EligibilityCheckRequest
from agentmine.application.contracts.opportunities import same_terms as same_terms
from agentmine.application.contracts.runtime import WorkSpecification
from agentmine.application.contracts.worker_execution import WorkerExecutionReason
from agentmine.application.errors import ApplicationError, PortError
from agentmine.application.ports.eligibility_review import EligibilityReviewRepository
from agentmine.application.ports.repositories import EvaluationRepository, OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.domain.economics import EconomicAssessment
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.eligibility_review import EligibilityChoice
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.scoring import ScoringAssessment
from agentmine.domain.values import Reference
from agentmine.domain.work import Eligibility, EligibilityStatus


@dataclass(frozen=True, slots=True)
class WorkerPreflight:
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    source: OpportunitySource
    clock: Clock
    operator: Reference
    eligibility_reviews: EligibilityReviewRepository | None = None

    def check(
        self, specification: WorkSpecification, opportunity: Opportunity
    ) -> WorkerExecutionReason | None:
        # Revalidate even a misbehaving in-memory port's frozen input objects.
        spec = replace(specification)
        evidence = spec.execution_evidence
        if spec.actor != self.operator or spec.approved_at > self.clock.now():
            return WorkerExecutionReason.APPROVAL_DENIED
        if evidence is None:
            return WorkerExecutionReason.EVIDENCE_INVALID
        request = evidence.eligibility_request
        evaluation = evidence.evaluation
        if (
            opportunity.task != spec.task
            or opportunity.reference != spec.task.opportunity_reference
            or request.facts.opportunity_reference != opportunity.reference
            or request.facts.task_type != spec.task.task_type
            or evaluation.opportunity_reference != opportunity.reference
            or evaluation.evaluated_at > spec.approved_at
            or self.evaluations.get(evaluation.reference) != evaluation
        ):
            return WorkerExecutionReason.EVIDENCE_INVALID
        engine = EligibilityEngine(evidence.eligibility_policy)
        try:
            inspection = CheckEligibility(
                self.opportunities, self.source, self.clock, engine
            ).inspect(request)
        except (PortError, ApplicationError):
            return WorkerExecutionReason.SOURCE_UNAVAILABLE
        if not same_terms(spec.source_context, inspection.source):
            return WorkerExecutionReason.SOURCE_CHANGED
        computed_eligibility = inspection.result
        eligibility: Eligibility | None = (
            self._manual(spec, request, evidence.eligibility_policy, computed_eligibility)
            if computed_eligibility.status == EligibilityStatus.REQUIRES_HUMAN_REVIEW
            else computed_eligibility
        )
        if eligibility is None or eligibility.status != EligibilityStatus.ELIGIBLE:
            return WorkerExecutionReason.ELIGIBILITY_BLOCKED
        if eligibility != evaluation.eligibility or eligibility != opportunity.eligibility:
            return WorkerExecutionReason.EVIDENCE_INVALID
        economic = evaluation.scoring_assessment.economics
        computed = EconomicAssessment(opportunity.potential_reward, economic.inputs)
        scoring = ScoringAssessment(
            computed, evaluation.scoring_assessment.signals, evaluation.scoring_assessment.policy
        )
        if (
            computed != economic
            or opportunity.economic_assessment != computed
            or opportunity.expected_value != computed.expected_net_value
            or opportunity.scoring_assessment != scoring
            or evaluation.scoring_assessment != scoring
            or opportunity.score != scoring.score
            or computed.inputs.estimated_cost.ai.amount != 0
        ):
            return WorkerExecutionReason.EVIDENCE_INVALID
        return None

    def _manual(
        self,
        spec: WorkSpecification,
        request: EligibilityCheckRequest,
        policy: EligibilityPolicy,
        current: Eligibility,
    ) -> Eligibility | None:
        evidence = spec.execution_evidence
        assert evidence is not None
        reference = evidence.eligibility_review_reference
        if reference is None or self.eligibility_reviews is None:
            return None
        review = self.eligibility_reviews.get_review(reference)
        resolution = self.eligibility_reviews.get_resolution(reference)
        if (
            review is None
            or resolution is None
            or resolution.choice != EligibilityChoice.APPROVE
            or review.reference != reference
            or resolution.review_reference != reference
            or resolution.actor != spec.actor
            or resolution.decided_at > spec.approved_at
            or review.policy != policy
            or not same_terms(review.inspection.source, spec.source_context)
            or review.inspection.request.refreshed(spec.source_context)
            != request.refreshed(spec.source_context)
        ):
            return None
        # Only the existing narrow MANUAL domain policy can produce ELIGIBLE here.
        return resolution.resolve(current)
