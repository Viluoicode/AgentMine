"""Narrow semantic patching: models can fill only explicitly designated fields."""

import json
from dataclasses import replace

from agentmine.application.contracts.ai import AIResponse, DeliverableDraft, ReferencedText
from agentmine.application.contracts.data import DataPlan, DataRecord
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.workers.data_transform import normalize, strict_json
from agentmine.domain.values import Reference


def semantic_inputs(plan: DataPlan, records: tuple[DataRecord, ...]) -> tuple[ReferencedText, ...]:
    columns = {column.name: column for column in plan.semantic_columns}
    inputs: list[ReferencedText] = []
    for record in records:
        fields = {
            cell.name: {
                "source_text": cell.value,
                "interpretation_required": columns[cell.name].semantic_reason,
                "allowed_values": columns[cell.name].allowed_values,
            }
            for cell in record.cells
            if cell.name in columns and cell.value is not None
        }
        if fields:
            inputs.append(
                ReferencedText(
                    Reference(f"data:{plan.execution.reference.value}:{record.row_id}"),
                    json.dumps(
                        {
                            "row_id": record.row_id,
                            "fields": fields,
                            "output_contract": (
                                "Return row_id and these exact fields as string/null. "
                                "Do not add rows or other columns."
                            ),
                        },
                        ensure_ascii=True,
                    ),
                )
            )
    if sum(len(item.text.encode("utf-8")) for item in inputs) > 50_000:
        raise PortError(
            PortErrorCode.UNSUPPORTED, "data", "Semantic batch too large; explicitly replan"
        )
    return tuple(inputs)


def apply_semantics(
    plan: DataPlan,
    records: tuple[DataRecord, ...],
    inputs: tuple[ReferencedText, ...],
    response: AIResponse[DeliverableDraft],
) -> tuple[DataRecord, ...]:
    def invalid() -> PortError:
        return PortError(
            PortErrorCode.INVALID_RESPONSE, "data_schema", "Invalid semantic field response"
        )

    if len(response.result.content) > 64_000:
        raise invalid()
    try:
        parsed = strict_json(response.result.content, numeric_as_text=False)
    except (ValueError, RecursionError):
        raise invalid() from None
    if not isinstance(parsed, dict) or set(parsed) != {"plan", "rows", "evidence"}:
        raise invalid()
    steps, rows, evidence = parsed["plan"], parsed["rows"], parsed["evidence"]
    if (
        not isinstance(steps, list)
        or not 1 <= len(steps) <= 20
        or any(not isinstance(step, str) or not step.strip() for step in steps)
        or not isinstance(rows, list)
        or not isinstance(evidence, list)
    ):
        raise invalid()
    aliases = {f"source-{index}": item.reference for index, item in enumerate(inputs)}
    if any(not isinstance(alias, str) or alias not in aliases for alias in evidence):
        raise invalid()
    if (
        len(set(evidence)) != len(evidence)
        or tuple(aliases[alias] for alias in evidence) != response.result.evidence
    ):
        raise invalid()
    columns = {column.name: column for column in plan.semantic_columns}
    expected = {
        record.row_id: {
            cell.name for cell in record.cells if cell.name in columns and cell.value is not None
        }
        for record in records
    }
    expected = {key: fields for key, fields in expected.items() if fields}
    if len(rows) != len(expected):
        raise invalid()
    patches: dict[str, dict[str, str | None]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("row_id"), str):
            raise invalid()
        identity = row["row_id"]
        if (
            identity not in expected
            or identity in patches
            or set(row) != {"row_id", *expected[identity]}
        ):
            raise invalid()
        patch: dict[str, str | None] = {}
        for key in expected[identity]:
            value = row[key]
            if value is not None and not isinstance(value, str):
                raise invalid()
            try:
                if value is not None:
                    value.encode("utf-8")
                patch[key] = normalize(value, columns[key], lookup=False)
            except (ValueError, UnicodeError):
                raise invalid() from None
        patches[identity] = patch
    return tuple(
        replace(
            record,
            cells=tuple(
                replace(
                    cell,
                    value=patches[record.row_id][cell.name],
                    semantic_evidence=response.evidence,
                )
                if record.row_id in patches and cell.name in patches[record.row_id]
                else cell
                for cell in record.cells
            ),
        )
        for record in records
    )
