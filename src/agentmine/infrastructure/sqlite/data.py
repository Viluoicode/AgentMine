"""Data execution snapshots and atomic AI ownership on local SQLite."""

from dataclasses import dataclass

from agentmine.application.contracts.ai import AIResponse, DeliverableDraft
from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class SQLiteDataJournal:
    database: SQLiteDatabase

    def save_plan(self, plan: DataPlan) -> None:
        self.database.immutable("data_plan", plan.execution.reference.value, plan)

    def claim_ai(self, plan: DataPlan) -> bool:
        return self.database.immutable(
            "data_ai_claim",
            plan.execution.authorization.request.context.operation_reference.value,
            plan,
        )

    def get_response(self, execution: Reference) -> AIResponse[DeliverableDraft] | None:
        item = self.database.get("data_response", execution.value, AIResponse)
        if item is None:
            return None
        response = item.value
        if not isinstance(response.result, DeliverableDraft):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "data", "Invalid cached draft")
        return AIResponse(
            response.operation_reference, response.result, response.actual_cost, response.evidence
        )

    def save_response(self, execution: Reference, response: AIResponse[DeliverableDraft]) -> None:
        self.database.immutable("data_response", execution.value, response)

    def get_result(self, execution: Reference) -> DataResult | None:
        item = self.database.get("data_result", execution.value, DataResult)
        return None if item is None else item.value

    def save_result(self, result: DataResult) -> None:
        self.database.immutable("data_result", result.execution_reference.value, result)
