"""Execution journal and versioned work evidence."""

from dataclasses import dataclass

from agentmine.application.contracts.ai import AIResponse, DeliverableDraft, ReferencedText
from agentmine.application.contracts.workflow import ExecuteTaskRequest
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable, Execution, QAResult
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key


@dataclass(frozen=True, slots=True)
class SQLiteExecutionRepository:
    database: SQLiteDatabase

    def save(self, execution: Execution) -> None:
        self.database.immutable(
            "execution",
            execution.reference.value,
            execution,
            IndexValues(
                parent=execution.task.opportunity_reference.value, occurred_at=execution.started_at
            ),
        )

    def get(self, reference: Reference) -> Execution | None:
        result = self.database.get("execution", reference.value, Execution)
        return None if result is None else result.value

    def for_opportunity(self, reference: Reference) -> tuple[Execution, ...]:
        return tuple(
            item.value
            for item in self.database.find("execution", Execution, parent=reference.value)
        )

    def save_deliverable(self, deliverable: Deliverable) -> None:
        self.database.immutable(
            "deliverable",
            composite_key(deliverable.reference.value, deliverable.version),
            deliverable,
        )

    def get_deliverable(self, reference: Reference, version: int) -> Deliverable | None:
        result = self.database.get(
            "deliverable", composite_key(reference.value, version), Deliverable
        )
        return None if result is None else result.value

    def save_qa(self, result: QAResult) -> None:
        self.database.immutable(
            "qa",
            composite_key(result.deliverable.reference.value, result.deliverable.version),
            result,
        )

    def get_qa(self, deliverable_reference: Reference, version: int) -> QAResult | None:
        result = self.database.get(
            "qa", composite_key(deliverable_reference.value, version), QAResult
        )
        return None if result is None else result.value

    def save_content(self, content: ReferencedText) -> None:
        self.database.immutable("content", content.reference.value, content)

    def get_content(self, reference: Reference) -> ReferencedText | None:
        result = self.database.get("content", reference.value, ReferencedText)
        return None if result is None else result.value

    def save_work_request(self, request: ExecuteTaskRequest) -> None:
        self.database.immutable("work_request", request.execution_reference.value, request)

    def get_work_request(self, execution_reference: Reference) -> ExecuteTaskRequest | None:
        result = self.database.get("work_request", execution_reference.value, ExecuteTaskRequest)
        return None if result is None else result.value

    def save_work_response(
        self, execution_reference: Reference, response: AIResponse[DeliverableDraft]
    ) -> None:
        self.database.immutable("work_response", execution_reference.value, response)

    def get_work_response(
        self, execution_reference: Reference
    ) -> AIResponse[DeliverableDraft] | None:
        result = self.database.get("work_response", execution_reference.value, AIResponse)
        if result is None:
            return None
        response = result.value
        if not isinstance(response.result, DeliverableDraft):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "read", "Invalid work response")
        return AIResponse(
            response.operation_reference, response.result, response.actual_cost, response.evidence
        )
