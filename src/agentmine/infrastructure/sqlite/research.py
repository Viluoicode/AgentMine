"""Durable research checkpoints using existing immutable SQLite snapshots."""

from dataclasses import dataclass

from agentmine.application.contracts.ai import AIResponse, DeliverableDraft
from agentmine.application.contracts.research import ResearchClaim, ResearchObservation, TaskPlan
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class SQLiteResearchJournal:
    database: SQLiteDatabase

    def save_plan(self, plan: TaskPlan) -> None:
        self.database.immutable("research_plan", plan.execution.reference.value, plan)

    def claim(self, claim: ResearchClaim) -> bool:
        return self.database.immutable("research_claim", claim.operation_reference.value, claim)

    def get_observation(self, operation: Reference) -> ResearchObservation | None:
        result = self.database.get("research_observation", operation.value, ResearchObservation)
        return None if result is None else result.value

    def save_observation(self, observation: ResearchObservation) -> None:
        self.database.immutable(
            "research_observation", observation.request.step.operation_reference.value, observation
        )

    def get_response(self, execution: Reference) -> AIResponse[DeliverableDraft] | None:
        result = self.database.get("research_response", execution.value, AIResponse)
        if result is None:
            return None
        response = result.value
        if not isinstance(response.result, DeliverableDraft):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "research", "Invalid cached model result"
            )
        return AIResponse(
            response.operation_reference, response.result, response.actual_cost, response.evidence
        )

    def save_response(self, execution: Reference, response: AIResponse[DeliverableDraft]) -> None:
        self.database.immutable("research_response", execution.value, response)
