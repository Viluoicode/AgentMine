"""Free discovery-to-plan orchestration using explicit domain policies."""

from dataclasses import dataclass

from agentmine.application.contracts.opportunities import DiscoveryRequest, OpportunityBatch
from agentmine.application.contracts.records import EvaluationRecord, OpportunitySave
from agentmine.application.contracts.workflow import PlanTaskRequest, ScoreRequest
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.ports.repositories import EvaluationRepository, OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.context import load, refresh, save
from agentmine.application.use_cases.eligibility import CheckEligibility as CheckEligibility
from agentmine.domain.economics import EconomicAssessment, EconomicInputs
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.scoring import ScoringAssessment, ScoringPolicy
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.domain.work import Task, TaskType


@dataclass(frozen=True, slots=True)
class DiscoverOpportunities:
    source: OpportunitySource
    opportunities: OpportunityRepository
    clock: Clock

    def execute(self, request: DiscoveryRequest) -> OpportunityBatch:
        batch = self.source.discover(request)
        now = self.clock.now()
        require_aware_timestamp(now)
        if len(batch.observations) > request.limit:
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "discover", "Batch exceeds requested limit"
            )
        for observation in batch.observations:
            if (
                observation.opportunity.state != OpportunityState.DISCOVERED
                or observation.observed_at > now
            ):
                raise PortError(
                    PortErrorCode.INVALID_RESPONSE, "discover", "Invalid source snapshot"
                )
        for observation in batch.observations:
            reference = observation.opportunity.reference
            existing = self.opportunities.get(reference)
            original = self.opportunities.get_observation(reference)
            if original is not None and original.source_reference != observation.source_reference:
                raise PortError(PortErrorCode.CONFLICT, "discover", "Source identity changed")
            if existing is not None:
                if original is None:
                    raise PortError(PortErrorCode.CONFLICT, "discover", "Source identity changed")
                continue  # Rediscovery must never downgrade an advanced aggregate.
            if original is not None:
                # An earlier attempt may have persisted provenance but not the aggregate.
                # Complete that write using the retained snapshot, not a changed rediscovery.
                self.opportunities.save(OpportunitySave(original.opportunity, None))
                continue
            self.opportunities.save_observation(observation)
            self.opportunities.save(OpportunitySave(observation.opportunity, None))
        return batch


@dataclass(frozen=True, slots=True)
class NormalizeOpportunity:
    opportunities: OpportunityRepository

    def execute(self, reference: Reference) -> Opportunity:
        previous = load(self.opportunities, reference)
        if previous.value.state == OpportunityState.NORMALIZED:
            return previous.value
        return save(self.opportunities, previous, previous.value.normalize())


@dataclass(frozen=True, slots=True)
class EvaluateOpportunity:
    opportunities: OpportunityRepository
    source: OpportunitySource
    clock: Clock

    def execute(self, reference: Reference, inputs: EconomicInputs) -> Opportunity:
        previous = load(self.opportunities, reference)
        assessment = EconomicAssessment(previous.value.potential_reward, inputs)
        if previous.value.economic_assessment == assessment:
            return previous.value
        refresh(self.opportunities, self.source, self.clock, reference)
        return save(self.opportunities, previous, previous.value.evaluate(assessment))


@dataclass(frozen=True, slots=True)
class ScoreOpportunity:
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    source: OpportunitySource
    clock: Clock
    policy: ScoringPolicy

    def execute(self, request: ScoreRequest) -> Opportunity:
        previous = load(self.opportunities, request.opportunity_reference)
        economics = previous.value.economic_assessment
        if economics is None or previous.value.eligibility is None:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_STATE, "score", "Calculated economics required"
            )
        assessment = ScoringAssessment(economics, request.signals, self.policy)
        existing = self.evaluations.get(request.evaluation_reference)
        if existing is not None and (
            existing.opportunity_reference != request.opportunity_reference
            or existing.scoring_assessment != assessment
            or existing.evidence != request.evidence
            or existing.eligibility != previous.value.eligibility
        ):
            raise PortError(PortErrorCode.CONFLICT, "score", "Assessment identity reused")
        if previous.value.scoring_assessment == assessment and existing is not None:
            return previous.value
        refresh(self.opportunities, self.source, self.clock, request.opportunity_reference)
        updated = previous.value.assign_score(assessment)
        record = existing or EvaluationRecord(
            request.evaluation_reference,
            updated.reference,
            previous.value.eligibility,
            economics.expected_net_value,
            assessment.score,
            self.clock.now(),
            request.evidence,
            assessment,
        )
        self.evaluations.save(record)
        return save(self.opportunities, previous, updated)


@dataclass(frozen=True, slots=True)
class PlanTask:
    opportunities: OpportunityRepository
    source: OpportunitySource
    clock: Clock

    def execute(self, request: PlanTaskRequest) -> Opportunity:
        try:
            task_type = TaskType(request.task_type)
        except ValueError as error:
            raise ApplicationError(
                ApplicationErrorCode.UNSUPPORTED_TASK,
                "plan",
                "Only Research/Data Processing supported",
            ) from error
        previous = load(self.opportunities, request.opportunity_reference)
        status = refresh(self.opportunities, self.source, self.clock, request.opportunity_reference)
        task = Task(
            request.task_reference,
            previous.value.reference,
            task_type,
            request.description,
            status.deadline,
        )
        if previous.value.task == task:
            return previous.value
        return save(self.opportunities, previous, previous.value.plan(task))
