"""Deterministic structured collection, field extraction, mapping and validation."""

import csv
import io
import json
import re
from datetime import date
from decimal import Decimal
from typing import cast

from agentmine.application.contracts.data import (
    Comparison,
    DataCell,
    DataColumn,
    DataFormat,
    DataIssue,
    DataIssueCode,
    DataPlan,
    DataRecord,
    DataSource,
    TextCase,
    ValueKind,
)


def strict_json(content: str, *, numeric_as_text: bool = True) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in items:
            if key in output:
                raise ValueError("Duplicate JSON key")
            output[key] = value
        return output

    def constant(value: str) -> object:
        raise ValueError("Nonfinite JSON number")

    return json.loads(
        content,
        object_pairs_hook=pairs,
        parse_float=str if numeric_as_text else float,
        parse_int=str if numeric_as_text else int,
        parse_constant=constant,
    )


def collect_source(source: DataSource) -> list[dict[str, object]]:
    if source.format == DataFormat.JSON:
        parsed = strict_json(source.content)
        if not isinstance(parsed, list) or any(not isinstance(row, dict) for row in parsed):
            raise ValueError("JSON array of records required")
        return cast(list[dict[str, object]], parsed)
    reader = csv.reader(io.StringIO(source.content, newline=""), strict=True)
    header = next(reader, [])
    if not header or any(not name.strip() for name in header) or len(header) != len(set(header)):
        raise ValueError("Unique nonempty CSV header required")
    rows: list[dict[str, object]] = []
    for values in reader:
        if len(values) != len(header):
            raise ValueError("CSV row width mismatch")
        rows.append(dict(zip(header, values, strict=True)))
    return rows


def extract(row: dict[str, object], path: tuple[str, ...]) -> tuple[bool, object]:
    value: object = row
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def normalize(raw: object, column: DataColumn, *, lookup: bool = True) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        value = "true" if raw else "false"
    elif isinstance(raw, str):
        value = raw.strip()
    else:
        raise ValueError("Scalar string/number/boolean required")
    value.encode("utf-8")
    if not value:
        return None
    if column.case == TextCase.LOWER:
        value = value.lower()
    elif column.case == TextCase.UPPER:
        value = value.upper()
    if lookup and column.lookup:
        mapping = {entry.key: entry.value for entry in column.lookup}
        if value not in mapping:
            raise ValueError("Unknown lookup key")
        value = mapping[value]
    if column.kind in (ValueKind.DECIMAL, ValueKind.INTEGER):
        pattern = r"-?[0-9]+" if column.kind == ValueKind.INTEGER else r"-?[0-9]+(?:\.[0-9]+)?"
        if len(value) > 1000 or re.fullmatch(pattern, value) is None:
            raise ValueError("Invalid numeric value")
        number = Decimal(value)
        value = format(number, "f")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        if number == 0:
            value = "0"
    elif column.kind == ValueKind.BOOLEAN:
        value = value.lower()
        if value not in ("true", "false"):
            raise ValueError("Invalid boolean")
    elif column.kind == ValueKind.DATE:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("ISO date required")
        value = date.fromisoformat(value).isoformat()
    return value


def transform(plan: DataPlan) -> tuple[tuple[DataRecord, ...], tuple[DataIssue, ...]]:
    records: list[DataRecord] = []
    issues: list[DataIssue] = []
    for source in plan.sources:
        try:
            rows = collect_source(source)
            if source.format == DataFormat.CSV:
                header = next(csv.reader(io.StringIO(source.content, newline=""), strict=True))
                for column in plan.columns:
                    if column.required and (len(column.path) != 1 or column.path[0] not in header):
                        issues.append(
                            DataIssue(
                                DataIssueCode.MISSING_COLUMN, source.reference, column=column.name
                            )
                        )
        except (ValueError, csv.Error, RecursionError):
            issues.append(DataIssue(DataIssueCode.MALFORMED_SOURCE, source.reference))
            continue
        if len(rows) + len(records) > 1000:
            # No truncation presented as successful collection.
            return (), (DataIssue(DataIssueCode.RECORD_COUNT),)
        for position, row in enumerate(rows, start=1):
            cells: list[DataCell] = []
            for column in plan.columns:
                found, raw = extract(row, column.path)
                if not found and column.required:
                    issues.append(
                        DataIssue(
                            DataIssueCode.MISSING_COLUMN, source.reference, position, column.name
                        )
                    )
                try:
                    # Semantic input is preserved, not classified by deterministic rules.
                    value = normalize(raw, column)
                except ValueError:
                    value = None
                    issues.append(
                        DataIssue(
                            DataIssueCode.INVALID_VALUE, source.reference, position, column.name
                        )
                    )
                cells.append(DataCell(column.name, value, column.path, column.lookup_evidence))
            records.append(
                DataRecord(
                    f"row-{len(records) + 1}",
                    source.reference,
                    source.locator,
                    source.collected_at,
                    source.digest,
                    position,
                    tuple(cells),
                )
            )
    return tuple(records), tuple(issues)


def validate(
    plan: DataPlan, records: tuple[DataRecord, ...], *, before_ai: bool = False
) -> tuple[DataIssue, ...]:
    issues: list[DataIssue] = []
    if not plan.min_records <= len(records) <= plan.max_records:
        issues.append(DataIssue(DataIssueCode.RECORD_COUNT))
    seen: set[tuple[str | None, ...]] = set()
    semantic = {column.name for column in plan.semantic_columns}
    unique = plan.unique_by or tuple(column.name for column in plan.columns)
    for record in records:
        values = {cell.name: cell.value for cell in record.cells}
        for column in plan.columns:
            value = values[column.name]
            code: DataIssueCode | None = None
            if value is None:
                if column.required:
                    code = DataIssueCode.MISSING_VALUE
            elif not (before_ai and column.name in semantic):
                if len(value) > column.max_length or (
                    column.allowed_values and value not in column.allowed_values
                ):
                    code = DataIssueCode.INVALID_VALUE
                if column.kind in (ValueKind.INTEGER, ValueKind.DECIMAL):
                    number = Decimal(value)
                    if (column.minimum is not None and number < column.minimum) or (
                        column.maximum is not None and number > column.maximum
                    ):
                        code = DataIssueCode.INVALID_VALUE
            if code is not None:
                issues.append(DataIssue(code, record.source, record.row, column.name))
        if not before_ai or not semantic.intersection(unique):
            key = tuple(values[name] for name in unique)
            if key in seen:
                issues.append(DataIssue(DataIssueCode.DUPLICATE, record.source, record.row))
            seen.add(key)
        for constraint in plan.constraints:
            if before_ai and semantic.intersection((constraint.left, constraint.right)):
                continue
            left, right = values[constraint.left], values[constraint.right]
            valid = left is not None and right is not None
            if valid:
                assert left is not None and right is not None
                valid = (
                    left == right
                    if constraint.comparison == Comparison.EQUAL
                    else Decimal(left) <= Decimal(right)
                )
            if not valid:
                issues.append(
                    DataIssue(DataIssueCode.CONSTRAINT, record.source, record.row, constraint.left)
                )
    return tuple(issues)
