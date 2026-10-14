"""Amazon Bedrock Converse adapter; AWS imports and client construction stay here."""

import hashlib
import importlib
import json
import logging
from dataclasses import dataclass, field
from typing import Protocol, cast

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import (
    AIResponse,
    DeliverableDraft,
    EvaluationAdvice,
    EvaluationRequest,
    QAAdvice,
    QARequest,
    WorkRequest,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.values import Reference
from agentmine.infrastructure.llm.journal import LLMJournal
from agentmine.infrastructure.llm.operations import (
    PreparedCall,
    Result,
    decode,
    invalid,
    object_value,
    prepare,
    text_value,
)
from agentmine.infrastructure.llm.pricing import BedrockSettings, measured_tokens
from agentmine.infrastructure.llm.security import ContentSafety


class ConverseClient(Protocol):
    """Infrastructure-only SDK seam for a stubbed Converse client."""

    def converse(self, **kwargs: object) -> object: ...


def create_bedrock_client(settings: BedrockSettings) -> ConverseClient:
    """Explicit opt-in; uses AWS's credential chain, never copies credentials to prompts."""
    try:
        boto3 = importlib.import_module("boto3")
        config = importlib.import_module("botocore.config").Config(
            retries={"total_max_attempts": 1, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
        )
        return cast(
            ConverseClient,
            boto3.Session().client(
                "bedrock-runtime",
                region_name=settings.region,
                config=config,
            ),
        )
    except Exception:
        raise PortError(
            PortErrorCode.UNAVAILABLE, "llm_setup", "Bedrock client unavailable"
        ) from None


def response_text(response: dict[str, object]) -> str:
    if response.get("stopReason") != "end_turn":
        raise invalid()
    message = object_value(object_value(response.get("output")).get("message"))
    blocks = message.get("content")
    if message.get("role") != "assistant" or not isinstance(blocks, list) or len(blocks) != 1:
        raise invalid()
    block = object_value(blocks[0])
    if set(block) != {"text"}:
        raise invalid()
    return text_value(block["text"])


@dataclass(frozen=True, slots=True)
class BedrockLLMProvider:
    client: ConverseClient = field(repr=False)
    settings: BedrockSettings
    budget: BudgetManager = field(repr=False)
    journal: LLMJournal
    safety: ContentSafety = field(default_factory=ContentSafety, repr=False)

    def _invoke(self, call: PreparedCall) -> AIResponse[Result]:
        auth = call.authorization
        operation = auth.request.context.operation_reference
        self.budget.require_authorized(auth, self.settings.estimate())
        request: dict[str, object] = {
            "modelId": self.settings.model_id,
            "system": [{"text": call.system}],
            "messages": [{"role": "user", "content": [{"text": call.user_data}]}],
            "inferenceConfig": {"maxTokens": self.settings.max_output_tokens},
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "request": request,
                    "settings": repr(self.settings),
                    "ledger": self.budget.ledger_reference.value,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        self.journal.claim(operation.value, fingerprint)
        try:
            response = object_value(self.client.converse(**request))
        except Exception:
            # A timeout/service failure can be billable. Keep reservation and dispatch claim.
            raise PortError(
                PortErrorCode.OUTCOME_UNKNOWN, "llm_dispatch", "Model call outcome unknown"
            ) from None
        at = self.budget.clock.now()
        tokens = measured_tokens(response)
        actual = None if tokens is None else self.settings.pricing.cost(*tokens)
        self.journal.record(
            operation.value,
            {
                "observed_at": at.isoformat(),
                "model": self.settings.model_id,
                "region": self.settings.region,
                "tariff": self.settings.pricing.evidence,
                "input_rate": str(self.settings.pricing.input_per_million.amount),
                "output_rate": str(self.settings.pricing.output_per_million.amount),
                "estimated_cost": str(auth.request.estimated_cost.amount),
                "input_tokens": None if tokens is None else tokens[0],
                "output_tokens": None if tokens is None else tokens[1],
                "usage_cost": None if actual is None else str(actual.amount),
                "currency": auth.request.estimated_cost.currency,
            },
        )
        measurement = None if actual is None else self.budget.record(auth, actual, at)
        # Billable usage is accounted even if output is truncated, unsafe or schema-invalid.
        result = decode(call, response_text(response), self.safety)
        logging.getLogger(__name__).info(
            "llm_result_validated",
            extra={
                "operation_kind": call.kind,
                "usage_known": tokens is not None,
            },
        )
        return AIResponse(operation, result, measurement, Reference("llm:sha256:" + fingerprint))

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
