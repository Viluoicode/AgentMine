"""Bounded declarative JSON decoding for local operator runtime commands."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from agentmine.application.contracts.data import (
    Comparison,
    DataColumn,
    DataFormat,
    LookupEntry,
    RowConstraint,
    TextCase,
    ValueKind,
)
from agentmine.application.contracts.eligibility import EligibilityCheckRequest
from agentmine.application.contracts.local_runtime import ApprovedDataInput, PrepareDataRequest
from agentmine.application.contracts.qa import (
    ArtifactFormat,
    CoverageKind,
    DataAcceptanceCriteria,
    QARequirement,
    RequiredArtifact,
)
from agentmine.domain.economics import EconomicInputs, EstimatedCosts, SignalEstimate
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.money import Money
from agentmine.domain.scoring import ScoringPolicy, ScoringSignals
from agentmine.domain.values import Reference


def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate input field")
        result[key] = value
    return result


def fields(value: object, allowed: set[str], required: set[str] | None = None) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) - allowed or (required or set()) - set(value):
        raise ValueError("Missing or unsupported input fields")
    return {str(key): item for key, item in value.items()}


def read_json(path: Path) -> object:
    with path.open("rb") as stream:
        raw = stream.read(64_001)
    if len(raw) > 64_000:
        raise ValueError("Input manifest exceeds 64000 bytes")
    return json.loads(raw, object_pairs_hook=pairs)


def text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Nonblank string required")
    return value


def items(value: object, maximum: int = 1000) -> list[object]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Bounded list required")
    return list(value)


def integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Integer required")
    return value


def boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("Boolean required")
    return value


def signal(value: object) -> SignalEstimate:
    obj = fields(value, {"value", "rationale", "evidence"}, {"value", "rationale"})
    return SignalEstimate(
        None if obj["value"] is None else Decimal(text(obj["value"])),
        text(obj["rationale"]),
        tuple(Reference(text(item)) for item in items(obj.get("evidence", []))),
    )


def read_economics(path: Path) -> EconomicInputs:
    obj = fields(
        read_json(path),
        {
            "currency",
            "predicted_success_probability",
            "estimated_cost",
            "cost_rationale",
            "cost_evidence",
        },
        {"currency", "predicted_success_probability", "estimated_cost", "cost_rationale"},
    )
    costs = fields(
        obj["estimated_cost"],
        {"ai", "tool", "infrastructure", "transaction"},
        {"ai", "tool", "infrastructure", "transaction"},
    )
    currency = text(obj["currency"])
    return EconomicInputs(
        signal(obj["predicted_success_probability"]),
        EstimatedCosts(
            *(
                Money(Decimal(text(costs[key])), currency)
                for key in ("ai", "tool", "infrastructure", "transaction")
            )
        ),
        text(obj["cost_rationale"]),
        tuple(Reference(text(item)) for item in items(obj.get("cost_evidence", []))),
    )


def read_scoring(path: Path) -> tuple[ScoringPolicy, ScoringSignals]:
    obj = fields(read_json(path), {"policy", "signals"}, {"policy", "signals"})
    policy = fields(
        obj["policy"],
        {"version", "net_value_target", "currency", "rationale"},
        {"version", "net_value_target", "currency", "rationale"},
    )
    names = ("risk", "competition", "deadline", "ai_suitability", "historical_performance")
    signals = fields(obj["signals"], set(names), set(names))
    return ScoringPolicy(
        text(policy["version"]),
        Money(Decimal(text(policy["net_value_target"])), text(policy["currency"])),
        text(policy["rationale"]),
    ), ScoringSignals(*(signal(signals[name]) for name in names))


def column(value: object) -> DataColumn:
    obj = fields(
        value,
        {
            "name",
            "path",
            "kind",
            "required",
            "case",
            "allowed_values",
            "minimum",
            "maximum",
            "max_length",
            "lookup",
            "lookup_evidence",
        },
        {"name", "path"},
    )
    lookup: list[LookupEntry] = []
    for entry in items(obj.get("lookup", [])):
        pair = fields(entry, {"key", "value"}, {"key", "value"})
        lookup.append(LookupEntry(text(pair["key"]), text(pair["value"])))
    return DataColumn(
        text(obj["name"]),
        tuple(text(item) for item in items(obj["path"], 10)),
        ValueKind(text(obj.get("kind", "text"))),
        boolean(obj.get("required", True)),
        TextCase(text(obj.get("case", "keep"))),
        tuple(lookup),
        None if obj.get("lookup_evidence") is None else Reference(text(obj["lookup_evidence"])),
        tuple(text(item) for item in items(obj.get("allowed_values", []))),
        None if obj.get("minimum") is None else Decimal(text(obj["minimum"])),
        None if obj.get("maximum") is None else Decimal(text(obj["maximum"])),
        integer(obj.get("max_length", 32_000)),
    )


def read_prepare(
    path: Path,
    reference: Reference,
    opportunity: Reference,
    evaluation: Reference,
    eligibility: EligibilityCheckRequest,
    policy: EligibilityPolicy,
    review: Reference | None,
) -> PrepareDataRequest:
    obj = fields(
        read_json(path),
        {
            "sources",
            "columns",
            "unique_by",
            "min_records",
            "max_records",
            "constraints",
            "acceptance",
        },
        {"sources", "columns"},
    )
    inputs: list[ApprovedDataInput] = []
    for source in items(obj["sources"], 10):
        names = {"id", "path", "sha256", "format", "locator", "collected_at"}
        entry = fields(source, names, names)
        inputs.append(
            ApprovedDataInput(
                Reference(text(entry["id"])),
                text(entry["path"]),
                DataFormat(text(entry["format"])),
                text(entry["locator"]),
                datetime.fromisoformat(text(entry["collected_at"])),
                Reference("sha256:" + text(entry["sha256"])),
            )
        )
    constraints: list[RowConstraint] = []
    for constraint in items(obj.get("constraints", []), 50):
        entry = fields(constraint, {"left", "comparison", "right"}, {"left", "comparison", "right"})
        constraints.append(
            RowConstraint(
                text(entry["left"]), Comparison(text(entry["comparison"])), text(entry["right"])
            )
        )
    return PrepareDataRequest(
        reference,
        opportunity,
        evaluation,
        eligibility,
        policy,
        tuple(inputs),
        tuple(column(item) for item in items(obj["columns"], 50)),
        tuple(text(item) for item in items(obj.get("unique_by", []), 50)),
        integer(obj.get("min_records", 1)),
        integer(obj.get("max_records", 1000)),
        tuple(constraints),
        review,
        None if obj.get("acceptance") is None else acceptance(obj["acceptance"]),
    )


def acceptance(value: object) -> DataAcceptanceCriteria:
    obj = fields(value, {"formats", "requirements"}, {"formats", "requirements"})
    formats: list[RequiredArtifact] = []
    for item in items(obj["formats"], 20):
        entry = fields(item, {"name", "format"}, {"name", "format"})
        formats.append(RequiredArtifact(text(entry["name"]), ArtifactFormat(text(entry["format"]))))
    requirements: list[QARequirement] = []
    for item in items(obj["requirements"], 50):
        entry = fields(
            item, {"id", "artifact", "kind", "criterion"}, {"id", "artifact", "kind", "criterion"}
        )
        requirements.append(
            QARequirement(
                Reference(text(entry["id"])),
                text(entry["artifact"]),
                CoverageKind(text(entry["kind"])),
                text(entry["criterion"]),
            )
        )
    return DataAcceptanceCriteria(tuple(formats), tuple(requirements))
