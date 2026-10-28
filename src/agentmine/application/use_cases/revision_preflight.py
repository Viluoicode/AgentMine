"""Live revision evidence checks; no lifecycle mutation or forecast replacement."""

from dataclasses import dataclass, replace

from agentmine.application.contracts.data_revision import DataRevisionRequest
from agentmine.application.contracts.opportunities import same_terms
from agentmine.application.contracts.worker_execution import WorkerExecutionReason
from agentmine.application.errors import ApplicationError, PortError
from agentmine.application.ports.repositories import EvaluationRepository, OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.domain.economics import EconomicAssessment
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.scoring import ScoringAssessment
from agentmine.domain.values import Reference
from agentmine.domain.work import EligibilityStatus


@dataclass(frozen=True, slots=True)
class RevisionPreflight:
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    source: OpportunitySource
    clock: Clock
    operator: Reference
    ledger_reference: Reference

    def check(
        self, request: DataRevisionRequest, opportunity: Opportunity
    ) -> WorkerExecutionReason | None:
        req = replace(request)
        spec = replace(req.specification)
        evidence = spec.execution_evidence
        if (
            spec.actor != self.operator
            or spec.ledger_reference != self.ledger_reference
            or spec.approved_at > self.clock.now()
        ):
            return WorkerExecutionReason.APPROVAL_DENIED
        if evidence is None or opportunity.task != spec.task:
            return WorkerExecutionReason.EVIDENCE_INVALID
        if self.evaluations.get(evidence.evaluation.reference) != evidence.evaluation:
            return WorkerExecutionReason.EVIDENCE_INVALID
        try:
            inspection = CheckEligibility(
                self.opportunities,
                self.source,
                self.clock,
                EligibilityEngine(evidence.eligibility_policy),
            ).inspect(evidence.eligibility_request)
        except (PortError, ApplicationError):
            return WorkerExecutionReason.SOURCE_UNAVAILABLE
        if not same_terms(spec.source_context, inspection.source):
            return WorkerExecutionReason.SOURCE_CHANGED
        if inspection.result.status != EligibilityStatus.ELIGIBLE:
            return WorkerExecutionReason.ELIGIBILITY_BLOCKED
        if inspection.result != evidence.evaluation.eligibility:
            return WorkerExecutionReason.EVIDENCE_INVALID
        assessment = evidence.evaluation.scoring_assessment
        economics = EconomicAssessment(opportunity.potential_reward, assessment.economics.inputs)
        calculated = ScoringAssessment(economics, assessment.signals, assessment.policy)
        if calculated != assessment or economics.inputs.estimated_cost.ai.amount != 0:
            return WorkerExecutionReason.EVIDENCE_INVALID
        return None
