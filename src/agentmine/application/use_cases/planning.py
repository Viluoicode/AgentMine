"""Free discovery-to-plan orchestration; supplied assessments avoid invented policy."""

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
from agentmine.domain.finance import ExpectedValue
from agentmine.domain.opportunity import Opportunity, OpportunityState
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
            if existing is not None:
                original = self.opportunities.get_observation(reference)
                if original is None or original.source_reference != observation.source_reference:
                    raise PortError(PortErrorCode.CONFLICT, "discover", "Source identity changed")
                continue  # Rediscovery must never downgrade an advanced aggregate.
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

    def execute(self, reference: Reference, expected_value: ExpectedValue) -> Opportunity:
        previous = load(self.opportunities, reference)
        if previous.value.expected_value == expected_value:
            return previous.value
        refresh(self.opportunities, self.source, self.clock, reference)
        return save(self.opportunities, previous, previous.value.evaluate(expected_value))


@dataclass(frozen=True, slots=True)
class ScoreOpportunity:
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    source: OpportunitySource
    clock: Clock

    def execute(self, request: ScoreRequest) -> Opportunity:
        previous = load(self.opportunities, request.opportunity_reference)
        existing = self.evaluations.get(request.evaluation_reference)
        if existing is not None and (
            existing.opportunity_reference != request.opportunity_reference
            or existing.score != request.score
            or existing.evidence != request.evidence
            or existing.eligibility != previous.value.eligibility
            or existing.expected_value != previous.value.expected_value
        ):
            raise PortError(PortErrorCode.CONFLICT, "score", "Assessment identity reused")
        if previous.value.score == request.score and existing is not None:
            return previous.value
        refresh(self.opportunities, self.source, self.clock, request.opportunity_reference)
        updated = previous.value.assign_score(request.score)
        if updated.eligibility is None or updated.expected_value is None:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_STATE, "score", "Assessment missing"
            )
        record = existing or EvaluationRecord(
            request.evaluation_reference,
            updated.reference,
            updated.eligibility,
            updated.expected_value,
            request.score,
            self.clock.now(),
            request.evidence,
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
