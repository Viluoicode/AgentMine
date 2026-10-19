"""Immutable QA inspections/reports and optional AI review checkpoints."""

from dataclasses import dataclass

from agentmine.application.contracts.ai import AIResponse, QAAdvice
from agentmine.application.contracts.qa import QAInspection
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.qa import QAReport
from agentmine.domain.values import Reference
from agentmine.infrastructure.dynamodb.store import DynamoStore


@dataclass(frozen=True, slots=True)
class DynamoDBQAJournal:
    database: DynamoStore

    def save_inspection(self, inspection: QAInspection) -> None:
        self.database.immutable("qa_inspection", inspection.reference.value, inspection)

    def claim_ai(self, inspection: QAInspection) -> bool:
        if inspection.ai_authorization is None:
            raise PortError(PortErrorCode.CONFLICT, "qa", "AI authorization missing")
        operation = inspection.ai_authorization.request.context.operation_reference
        return self.database.immutable("qa_ai_claim", operation.value, inspection)

    def get_response(self, reference: Reference) -> AIResponse[QAAdvice] | None:
        item = self.database.get("qa_ai_response", reference.value, AIResponse)
        if item is None:
            return None
        response = item.value
        if not isinstance(response.result, QAAdvice):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "qa", "Invalid cached QA advice")
        return AIResponse(
            response.operation_reference, response.result, response.actual_cost, response.evidence
        )

    def save_response(self, reference: Reference, response: AIResponse[QAAdvice]) -> None:
        self.database.immutable("qa_ai_response", reference.value, response)

    def get_report(self, reference: Reference) -> QAReport | None:
        item = self.database.get("qa_report", reference.value, QAReport)
        return None if item is None else item.value

    def save_report(self, report: QAReport) -> None:
        self.database.immutable("qa_report", report.reference.value, report)
