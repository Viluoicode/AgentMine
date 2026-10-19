"""Versioned transport inputs; no lifecycle or financial decisions."""

import re
from dataclasses import dataclass
from enum import StrEnum

from agentmine.application.contracts.opportunities import DiscoveryRequest
from agentmine.domain.values import Reference


class Workflow(StrEnum):
    DISCOVER = "discover"
    NORMALIZE = "normalize"
    TRACK_OUTCOME = "track_outcome"
    VERIFY_PAYMENT = "verify_payment"


class InvalidEvent(ValueError):
    """Transport validation failure with no untrusted payload in the message."""

    def __init__(self) -> None:
        super().__init__("Invalid AgentMine runtime event")


def safe_identifier(value: object) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        return value
    return None


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    correlation_id: str | None
    request: DiscoveryRequest | Reference


def parse_event(event: object, workflow: Workflow) -> RuntimeEvent:
    if not isinstance(event, dict) or any(not isinstance(key, str) for key in event):
        raise InvalidEvent()
    envelope_id: str | None = None
    if "detail" in event:
        if (
            event.get("source") != "agentmine"
            or event.get("detail-type") != "agentmine." + workflow.value
        ):
            raise InvalidEvent()
        envelope_id = safe_identifier(event.get("id"))
        event = event["detail"]
        if not isinstance(event, dict) or any(not isinstance(key, str) for key in event):
            raise InvalidEvent()
    if type(event.get("schema_version")) is not int or event["schema_version"] != 1:
        raise InvalidEvent()
    correlation = event.get("correlation_id", envelope_id)
    if correlation is not None and safe_identifier(correlation) is None:
        raise InvalidEvent()
    common = {"schema_version", "correlation_id"}
    request: DiscoveryRequest | Reference
    if workflow == Workflow.DISCOVER:
        if set(event) - (common | {"limit", "continuation"}):
            raise InvalidEvent()
        limit = event.get("limit", 20)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise InvalidEvent()
        continuation = event.get("continuation")
        if continuation is not None and (
            not isinstance(continuation, str)
            or not continuation.strip()
            or len(continuation) > 2048
        ):
            raise InvalidEvent()
        request = DiscoveryRequest(limit, None if continuation is None else Reference(continuation))
    else:
        if set(event) - (common | {"opportunity_id"}):
            raise InvalidEvent()
        identifier = event.get("opportunity_id")
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 2048:
            raise InvalidEvent()
        request = Reference(identifier)
    return RuntimeEvent(safe_identifier(correlation), request)
