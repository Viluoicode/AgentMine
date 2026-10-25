"""Bounded local JSON-to-value-object parsing; no eligibility decisions."""

import json
from pathlib import Path

from agentmine.application.contracts.eligibility import EligibilityCheckRequest
from agentmine.domain.eligibility import (
    AIParticipationPolicy,
    CountryCode,
    EligibilityFacts,
    GeographicRestrictions,
    ParticipantProfile,
    PaymentRequirements,
    ProhibitedAction,
    Requirement,
    SubmissionSupport,
)
from agentmine.domain.values import Reference


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in items:
        if name in result:
            raise ValueError("Duplicate input field")
        result[name] = value
    return result


def _object(value: object, allowed: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or any(key not in allowed for key in value):
        raise ValueError("Invalid eligibility input fields")
    return {str(key): item for key, item in value.items()}


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonblank eligibility text required")
    return value


def _boolean(value: object) -> bool | None:
    if value is not None and type(value) is not bool:
        raise ValueError("Boolean or null required")
    return value


def _strings(value: object) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("List or null required")
    return frozenset(_text(item) for item in value)


def read_eligibility_request(path: Path, reference: Reference) -> EligibilityCheckRequest:
    with path.open("rb") as stream:
        raw = stream.read(64_001)
    if len(raw) > 64_000:
        raise ValueError("Eligibility input exceeds 64000 bytes")
    try:
        root = _object(json.loads(raw, object_pairs_hook=_pairs), {"facts", "profile"})
        facts = _object(
            root.get("facts"),
            {
                "ai_policy",
                "geography",
                "account",
                "identity",
                "physical_presence",
                "task_type",
                "required_skills",
                "submission",
                "payment",
                "prohibited_actions",
            },
        )
        profile = _object(
            root.get("profile", {}),
            {
                "country",
                "account_requirement_met",
                "identity_requirement_met",
                "will_disclose_ai",
                "skills",
            },
        )
        geography = None
        if facts.get("geography") is not None:
            geo = _object(facts["geography"], {"allowed", "excluded"})
            # Both sets must be explicit; omitted restrictions remain unknown.
            if set(geo) != {"allowed", "excluded"}:
                raise ValueError("Explicit geographic restrictions required")
            allowed, excluded = _strings(geo["allowed"]), _strings(geo["excluded"])
            if allowed is None or excluded is None:
                raise ValueError("Explicit geographic sets required")
            geography = GeographicRestrictions(
                frozenset(CountryCode(x) for x in allowed),
                frozenset(CountryCode(x) for x in excluded),
            )
        payment = _object(facts.get("payment", {}), {"upfront_fee", "secret_credentials"})
        actions = _strings(facts.get("prohibited_actions"))
        task_type = facts.get("task_type")
        return EligibilityCheckRequest(
            EligibilityFacts(
                reference,
                ai_policy=AIParticipationPolicy(_text(facts.get("ai_policy", "unknown"))),
                geography=geography,
                account=Requirement(_text(facts.get("account", "unknown"))),
                identity=Requirement(_text(facts.get("identity", "unknown"))),
                physical_presence=Requirement(_text(facts.get("physical_presence", "unknown"))),
                task_type=None if task_type is None else _text(task_type),
                required_skills=_strings(facts.get("required_skills")),
                submission=SubmissionSupport(_text(facts.get("submission", "unknown"))),
                payment=PaymentRequirements(
                    _boolean(payment.get("upfront_fee")),
                    _boolean(payment.get("secret_credentials")),
                ),
                prohibited_actions=None
                if actions is None
                else frozenset(ProhibitedAction(x) for x in actions),
            ),
            ParticipantProfile(
                None if profile.get("country") is None else CountryCode(_text(profile["country"])),
                _boolean(profile.get("account_requirement_met")),
                _boolean(profile.get("identity_requirement_met")),
                _boolean(profile.get("will_disclose_ai")),
                _strings(profile.get("skills")),
            ),
        )
    except (UnicodeError, RecursionError):
        raise ValueError("Invalid eligibility input encoding or nesting") from None
