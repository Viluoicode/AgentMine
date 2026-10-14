"""Conservative translation of verified fields; unrepresentable offers are retained."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import cast

from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.eligibility import (
    AIParticipationPolicy,
    Deadline,
    DeadlineKind,
    EligibilityFacts,
)
from agentmine.domain.finance import Reward
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference, require_aware_timestamp

type JSONObject = dict[str, object]


class NormalizationIssue(StrEnum):
    TITLE_UNKNOWN = "TITLE_UNKNOWN"
    AI_POLICY_UNKNOWN = "AI_POLICY_UNKNOWN"
    AI_PARTICIPATION_PROHIBITED = "AI_PARTICIPATION_PROHIBITED"
    REWARD_MODEL_UNKNOWN = "REWARD_MODEL_UNKNOWN"
    REWARD_MODEL_UNSUPPORTED = "REWARD_MODEL_UNSUPPORTED"
    REWARD_AMOUNT_UNKNOWN = "REWARD_AMOUNT_UNKNOWN"
    REWARD_ASSET_UNSUPPORTED = "REWARD_ASSET_UNSUPPORTED"
    REWARD_ASSET_UNKNOWN = "REWARD_ASSET_UNKNOWN"
    REQUIREMENTS_UNKNOWN = "REQUIREMENTS_UNKNOWN"


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    source_reference: Reference
    raw_reference: Reference
    facts: EligibilityFacts
    observation: OpportunityObservation | None
    issues: tuple[NormalizationIssue, ...]


def invalid_response() -> PortError:
    return PortError(PortErrorCode.INVALID_RESPONSE, "discovery", "Invalid source listing response")


def _pairs(pairs: list[tuple[str, object]]) -> JSONObject:
    result: JSONObject = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise ValueError("Non-JSON number")


def decode_json(body: bytes) -> object:
    try:
        return cast(
            object,
            json.loads(
                body.decode("utf-8"),
                parse_float=Decimal,
                parse_int=Decimal,
                parse_constant=_constant,
                object_pairs_hook=_pairs,
            ),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise invalid_response() from None


def listing_object(value: object) -> JSONObject:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise invalid_response()
    return cast(JSONObject, value)


def identity(data: JSONObject) -> tuple[str, str]:
    result = []
    for field in ("id", "slug"):
        value = data.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise invalid_response()
        result.append(value)
    return result[0], result[1]


def availability(data: JSONObject) -> tuple[bool | None, Deadline]:
    status = data.get("status")
    is_open = (
        True
        if status == "OPEN"
        else (False if status in ("REVIEW", "CLOSED", "VERIFYING", "VERIFY_FAIL") else None)
    )
    announced = data.get("isWinnersAnnounced")
    if announced is not None and type(announced) is not bool:
        raise invalid_response()
    if announced is True:
        is_open = False
    deadline = data.get("deadline")
    if deadline is None:
        return is_open, Deadline()
    if not isinstance(deadline, str):
        raise invalid_response()
    try:
        at = datetime.fromisoformat(deadline)
        require_aware_timestamp(at)
    except ValueError:
        raise invalid_response() from None
    return is_open, Deadline(DeadlineKind.AT, at.astimezone(UTC))


def agent_policy(data: JSONObject) -> AIParticipationPolicy:
    access = data.get("agentAccess")
    if access in ("AGENT_ALLOWED", "AGENT_ONLY"):
        return AIParticipationPolicy.ALLOWED
    if access == "HUMAN_ONLY":
        return AIParticipationPolicy.PROHIBITED
    return AIParticipationPolicy.UNKNOWN


def normalize_detail(
    data: JSONObject,
    observed_at: datetime,
    raw_reference: Reference,
) -> NormalizationResult:
    require_aware_timestamp(observed_at)
    item_id, slug = identity(data)
    reference = Reference(f"superteam:{item_id}")
    source = Reference(f"superteam:{slug}")
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        raise invalid_response()
    is_open, deadline = availability(data)
    policy = agent_policy(data)
    facts = EligibilityFacts(reference, is_open, deadline, policy)
    issues: list[NormalizationIssue] = []
    if title is None or not title.strip():
        issues.append(NormalizationIssue.TITLE_UNKNOWN)
    if policy == AIParticipationPolicy.UNKNOWN:
        issues.append(NormalizationIssue.AI_POLICY_UNKNOWN)
    elif policy == AIParticipationPolicy.PROHIBITED:
        issues.append(NormalizationIssue.AI_PARTICIPATION_PROHIBITED)
    text: list[str] = []
    for name in ("description", "requirements"):
        value = data.get(name)
        if value is not None and not isinstance(value, str):
            raise invalid_response()
        if isinstance(value, str) and value.strip():
            text.append(value)
    if not text:
        issues.append(NormalizationIssue.REQUIREMENTS_UNKNOWN)
    if data.get("type") is None or data.get("compensationType") is None:
        issues.append(NormalizationIssue.REWARD_MODEL_UNKNOWN)
    elif data.get("type") != "project" or data.get("compensationType") != "fixed":
        issues.append(NormalizationIssue.REWARD_MODEL_UNSUPPORTED)
    amount = data.get("rewardAmount")
    if amount is None:
        issues.append(NormalizationIssue.REWARD_AMOUNT_UNKNOWN)
    elif not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
        raise invalid_response()
    token = data.get("token")
    if token is None:
        issues.append(NormalizationIssue.REWARD_ASSET_UNKNOWN)
    elif not isinstance(token, str) or not re.fullmatch(r"[A-Z]{3}", token):
        issues.append(NormalizationIssue.REWARD_ASSET_UNSUPPORTED)
    observation = None
    if not issues:
        assert isinstance(amount, Decimal) and isinstance(token, str)
        assert isinstance(title, str)
        opportunity = Opportunity(
            reference, title, Reward(Money(amount, token), evidence=raw_reference)
        )
        observation = OpportunityObservation(
            opportunity,
            source,
            "\n\n".join(text),
            observed_at,
            is_open,
            deadline.at,
            deadline.kind != DeadlineKind.UNKNOWN,
        )
    return NormalizationResult(source, raw_reference, facts, observation, tuple(issues))
