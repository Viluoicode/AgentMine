"""Escaped operator data views shared by first-version and revision commands."""

from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal
from enum import Enum

from agentmine.application.contracts.runtime import WorkSpecification


def encode(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (Decimal, tzinfo)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (tuple, list, frozenset)):
        return [encode(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    raise TypeError("Unsupported operator display type")


def specification_view(spec: WorkSpecification) -> dict[str, object]:
    return {
        "specification_id": spec.reference.value,
        "task": encode(spec.task),
        "actor": spec.actor.value,
        "approved_at": spec.approved_at.isoformat(),
        "ledger": spec.ledger_reference.value,
        "source_context": encode(spec.source_context),
        "inputs": [
            {
                "id": item.reference.value,
                "locator": item.locator,
                "format": item.format.value,
                "sha256": item.digest,
                "collected_at": item.collected_at.isoformat(),
                "bytes": len(item.content.encode("utf-8")),
            }
            for item in spec.sources
        ],
        "columns": encode(spec.columns),
        "constraints": encode(spec.constraints),
        "unique_by": list(spec.unique_by),
        "min_records": spec.min_records,
        "max_records": spec.max_records,
        "eligibility_and_economic_forecast_evidence": encode(spec.execution_evidence),
        "approved_acceptance_criteria": encode(spec.acceptance),
        "preparation_dispatches_work": False,
        "specification_grants_submission_approval": False,
    }
