"""Zero-cost deterministic implementation of the same validated AI contracts."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from agentmine.application.contracts.ai import (
    AIResponse,
    DeliverableDraft,
    EvaluationAdvice,
    EvaluationRequest,
    QAAdvice,
    QARequest,
    WorkRequest,
)
from agentmine.domain.finance import Cost, CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference
from agentmine.infrastructure.llm.operations import PreparedCall, Result, decode, prepare
from agentmine.infrastructure.llm.security import ContentSafety


@dataclass(frozen=True, slots=True)
class MockLLMProvider:
    responses: Mapping[str, str] = field(default_factory=dict, repr=False)
    safety: ContentSafety = field(default_factory=ContentSafety, repr=False)

    def _invoke(self, call: PreparedCall) -> AIResponse[Result]:
        defaults: dict[str, object] = {
            "evaluation": {
                "expected_net_value": "0",
                "rationale": "Mock estimate, not a forecast",
                "evidence": [],
            },
            "research": {
                "plan": ["Review supplied sources"],
                "content": "Mock research draft",
                "evidence": [],
            },
            "data_processing": {"plan": ["Extract supplied records"], "rows": [], "evidence": []},
            "qa": {"recommendation": "failed", "findings": "Mock QA requires human review"},
        }
        text = self.responses.get(call.kind, json.dumps(defaults[call.kind]))
        result = decode(call, text, self.safety)
        spending = call.authorization.request
        operation = spending.context.operation_reference
        measurement = CostRecord(
            Cost(operation, Money(Decimal(0), spending.estimated_cost.currency), CostCategory.AI),
            spending.context,
            spending.estimated_cost,
        )
        return AIResponse(operation, result, measurement, Reference("mock:" + operation.value))

    def evaluate_opportunity(self, request: EvaluationRequest) -> AIResponse[EvaluationAdvice]:
        response = self._invoke(prepare(request, self.safety))
        assert isinstance(response.result, EvaluationAdvice)
        return AIResponse(
            response.operation_reference, response.result, response.actual_cost, response.evidence
        )

    def perform_work(self, request: WorkRequest) -> AIResponse[DeliverableDraft]:
        response = self._invoke(prepare(request, self.safety))
        assert isinstance(response.result, DeliverableDraft)
        return AIResponse(
            response.operation_reference, response.result, response.actual_cost, response.evidence
        )

    def review_deliverable(self, request: QARequest) -> AIResponse[QAAdvice]:
        response = self._invoke(prepare(request, self.safety))
        assert isinstance(response.result, QAAdvice)
        return AIResponse(
            response.operation_reference, response.result, response.actual_cost, response.evidence
        )
