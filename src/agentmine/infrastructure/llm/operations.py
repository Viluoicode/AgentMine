"""Explicit input allowlists and strict local output schemas for three business ports."""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import cast

from agentmine.application.contracts.ai import (
    DeliverableDraft,
    EvaluationAdvice,
    EvaluationRequest,
    QAAdvice,
    QARequest,
    WorkRequest,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.budget import BudgetAuthorization
from agentmine.domain.finance import ExpectedValue
from agentmine.domain.money import Money
from agentmine.domain.values import Reference
from agentmine.domain.work import QAStatus, TaskType
from agentmine.infrastructure.llm.security import SYSTEM_POLICY, ContentSafety

type Result = EvaluationAdvice | DeliverableDraft | QAAdvice
type Request = EvaluationRequest | WorkRequest | QARequest


def invalid() -> PortError:
    return PortError(PortErrorCode.INVALID_RESPONSE, "ai_schema", "Invalid structured model result")


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise invalid()
    return cast(dict[str, object], value)


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise invalid()
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise invalid()


def text_value(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid()
    return value


@dataclass(frozen=True, slots=True)
class PreparedCall:
    kind: str
    authorization: BudgetAuthorization
    user_data: str
    schema: str
    sources: dict[str, Reference]
    currency: str

    @property
    def system(self) -> str:
        return SYSTEM_POLICY + "\nOperation: " + self.kind + "\nJSON schema: " + self.schema


def prepare(request: Request, safety: ContentSafety) -> PreparedCall:
    sources: dict[str, Reference] = {}
    data: dict[str, object]
    if isinstance(request, EvaluationRequest):
        kind, auth = "evaluation", request.authorization
        currency = request.opportunity.potential_reward.amount.currency
        data = {
            "title": request.opportunity.title,
            "requirements": request.requirements,
            "potential_reward": str(request.opportunity.potential_reward.amount.amount),
            "currency": currency,
            "source": "listing",
        }
        sources = {"listing": request.opportunity.reference}
        schema = '{"expected_net_value":"decimal string","rationale":"nonempty string","evidence":["listing"]}'
    elif isinstance(request, WorkRequest):
        task = request.execution.task
        if task.task_type not in (TaskType.RESEARCH, TaskType.DATA_PROCESSING):
            raise PortError(PortErrorCode.UNSUPPORTED, "work", "Unsupported work type")
        kind, auth = task.task_type.value, request.execution.authorization
        currency = auth.request.estimated_cost.currency
        inputs = []
        for index, item in enumerate(request.inputs):
            alias = f"source-{index}"
            sources[alias] = item.reference
            inputs.append({"source": alias, "text": item.text})
        data = {"description": task.description, "inputs": inputs}
        schema = (
            '{"plan":["nonempty step"],"content":"nonempty research report","evidence":["source-0"]}'
            if task.task_type == TaskType.RESEARCH
            else '{"plan":["nonempty step"],"rows":[{"field":"string or null"}],"evidence":["source-0"]}'
        )
    else:
        if not request.deterministic_insufficient:
            raise PortError(
                PortErrorCode.UNSUPPORTED, "qa", "Deterministic QA must be insufficient"
            )
        kind, auth = "qa", request.authorization
        currency = auth.request.estimated_cost.currency
        data = {"content": request.content.text, "criteria": request.criteria}
        schema = '{"recommendation":"passed or failed","findings":"nonempty string"}'
    # Marketplace strings never become roles, system text, tool definitions or SDK arguments.
    safety.check_values(data)
    user = json.dumps({"untrusted_data": data}, ensure_ascii=False)
    safety.check(user)
    return PreparedCall(kind, auth, user, schema, sources, currency)


def decode(call: PreparedCall, text: str, safety: ContentSafety) -> Result:
    safety.check(text, output=True)
    try:
        obj = object_value(json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant))
    except (ValueError, RecursionError):
        raise invalid() from None
    expected = {
        "evaluation": {"expected_net_value", "rationale", "evidence"},
        "research": {"plan", "content", "evidence"},
        "data_processing": {"plan", "rows", "evidence"},
        "qa": {"recommendation", "findings"},
    }[call.kind]
    if set(obj) != expected:
        raise invalid()
    # Also inspect decoded strings: JSON escapes must not bypass content checks.
    safety.check_values(obj, output=True)
    if call.kind == "qa":
        if obj["recommendation"] not in ("passed", "failed"):
            raise invalid()
        return QAAdvice(QAStatus(str(obj["recommendation"])), text_value(obj["findings"]))
    evidence = obj["evidence"]
    if not isinstance(evidence, list) or any(
        not isinstance(item, str) or item not in call.sources for item in evidence
    ):
        raise invalid()
    aliases = cast(list[str], evidence)
    if len(set(aliases)) != len(aliases):
        raise invalid()
    refs = tuple(call.sources[item] for item in aliases)
    if call.kind == "evaluation":
        number = text_value(obj["expected_net_value"])
        if len(number) > 64 or not re.fullmatch(r"-?\d+(?:\.\d+)?", number):
            raise invalid()
        try:
            amount = Decimal(number)
        except InvalidOperation:
            raise invalid() from None
        rationale = text_value(obj["rationale"])
        return EvaluationAdvice(
            ExpectedValue(Money(amount, call.currency), rationale), rationale, refs
        )
    plan = obj["plan"]
    if not isinstance(plan, list) or not 1 <= len(plan) <= 20:
        raise invalid()
    for step in plan:
        text_value(step)
    if call.kind == "research":
        text_value(obj["content"])
    else:
        rows = obj["rows"]
        if not isinstance(rows, list) or len(rows) > 1000:
            raise invalid()
        for row in rows:
            fields = object_value(row)
            if (
                not fields
                or any(not key.strip() for key in fields)
                or any(
                    value is not None and not isinstance(value, str) for value in fields.values()
                )
            ):
                raise invalid()
    return DeliverableDraft(json.dumps(obj, ensure_ascii=False, sort_keys=True), refs)
