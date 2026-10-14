"""Bounded declarative data processing contracts; no executable task expressions."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from agentmine.application.contracts.ai import WorkRequest
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Execution, TaskType


def invalid(field: str) -> DomainError:
    return DomainError(ErrorCode.INVALID_VALUE, field, "Invalid data processing contract")


def text(value: str, field: str, maximum: int = 2000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise invalid(field)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise invalid(field) from None


class DataFormat(StrEnum):
    CSV = "csv"
    JSON = "json"


class ValueKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"


class TextCase(StrEnum):
    KEEP = "keep"
    LOWER = "lower"
    UPPER = "upper"


@dataclass(frozen=True, slots=True)
class DataSource:
    reference: Reference
    locator: str
    collected_at: datetime
    format: DataFormat
    content: str

    def __post_init__(self) -> None:
        require_reference(self.reference, "source")
        text(self.locator, "locator")
        require_aware_timestamp(self.collected_at)
        if not isinstance(self.format, DataFormat) or not isinstance(self.content, str):
            raise invalid("source")
        try:
            if len(self.content.encode("utf-8")) > 1_000_000:
                raise invalid("source_size")
        except UnicodeError:
            raise invalid("source_encoding") from None

    @property
    def digest(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LookupEntry:
    key: str
    value: str

    def __post_init__(self) -> None:
        text(self.key, "lookup_key")
        text(self.value, "lookup_value")


@dataclass(frozen=True, slots=True)
class DataColumn:
    name: str
    path: tuple[str, ...]
    kind: ValueKind = ValueKind.TEXT
    required: bool = True
    case: TextCase = TextCase.KEEP
    lookup: tuple[LookupEntry, ...] = ()
    lookup_evidence: Reference | None = None
    allowed_values: tuple[str, ...] = ()
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    max_length: int = 32_000
    semantic_reason: str | None = None

    def __post_init__(self) -> None:
        text(self.name, "column", 100)
        if not self.name.isidentifier() or self.name.startswith("_") or self.name == "row_id":
            raise invalid("reserved_column")
        if not isinstance(self.path, tuple) or not 1 <= len(self.path) <= 10:
            raise invalid("path")
        for part in self.path:
            text(part, "path_part", 100)
        if not isinstance(self.kind, ValueKind) or not isinstance(self.case, TextCase):
            raise invalid("column_type")
        if (
            type(self.required) is not bool
            or type(self.max_length) is not int
            or not 1 <= self.max_length <= 32_000
        ):
            raise invalid("column_constraint")
        if (
            not isinstance(self.lookup, tuple)
            or len(self.lookup) > 1000
            or any(not isinstance(entry, LookupEntry) for entry in self.lookup)
        ):
            raise invalid("lookup")
        if len({entry.key for entry in self.lookup}) != len(self.lookup):
            raise invalid("lookup_duplicates")
        if self.lookup:
            if self.lookup_evidence is None:
                raise invalid("lookup_evidence")
            require_reference(self.lookup_evidence, "lookup_evidence")
        if not isinstance(self.allowed_values, tuple) or len(self.allowed_values) > 1000:
            raise invalid("allowed_values")
        for value in self.allowed_values:
            text(value, "allowed_value", 32_000)
        for bound in (self.minimum, self.maximum):
            if bound is not None and (not isinstance(bound, Decimal) or not bound.is_finite()):
                raise invalid("numeric_bound")
        if (self.minimum is not None or self.maximum is not None) and self.kind not in (
            ValueKind.INTEGER,
            ValueKind.DECIMAL,
        ):
            raise invalid("numeric_constraint_type")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise invalid("numeric_range")
        if self.semantic_reason is not None:
            text(self.semantic_reason, "semantic_reason")
            if self.kind != ValueKind.TEXT or self.lookup:
                raise invalid("semantic_field")


class Comparison(StrEnum):
    EQUAL = "equal"
    LESS_OR_EQUAL = "less_or_equal"


@dataclass(frozen=True, slots=True)
class RowConstraint:
    left: str
    comparison: Comparison
    right: str

    def __post_init__(self) -> None:
        text(self.left, "left")
        text(self.right, "right")
        if not isinstance(self.comparison, Comparison):
            raise invalid("comparison")


@dataclass(frozen=True, slots=True)
class DataPlan:
    execution: Execution
    sources: tuple[DataSource, ...]
    columns: tuple[DataColumn, ...]
    unique_by: tuple[str, ...] = ()
    min_records: int = 1
    max_records: int = 1000
    constraints: tuple[RowConstraint, ...] = ()

    def __post_init__(self) -> None:
        WorkRequest(self.execution, ())
        if self.execution.task.task_type != TaskType.DATA_PROCESSING:
            raise invalid("task_type")
        if (
            not isinstance(self.sources, tuple)
            or not 1 <= len(self.sources) <= 10
            or any(not isinstance(source, DataSource) for source in self.sources)
        ):
            raise invalid("sources")
        if len({source.reference for source in self.sources}) != len(self.sources):
            raise invalid("duplicate_source")
        if (
            not isinstance(self.columns, tuple)
            or not 1 <= len(self.columns) <= 50
            or any(not isinstance(column, DataColumn) for column in self.columns)
        ):
            raise invalid("columns")
        names = {column.name for column in self.columns}
        if len(names) != len(self.columns):
            raise invalid("duplicate_column")
        if (
            not isinstance(self.unique_by, tuple)
            or len(set(self.unique_by)) != len(self.unique_by)
            or any(name not in names for name in self.unique_by)
        ):
            raise invalid("unique_by")
        if (
            type(self.min_records) is not int
            or type(self.max_records) is not int
            or not 0 <= self.min_records <= self.max_records <= 1000
        ):
            raise invalid("record_limits")
        if not isinstance(self.constraints, tuple) or len(self.constraints) > 50:
            raise invalid("constraints")
        columns = {column.name: column for column in self.columns}
        for constraint in self.constraints:
            if (
                not isinstance(constraint, RowConstraint)
                or constraint.left not in names
                or constraint.right not in names
            ):
                raise invalid("constraint_columns")
            if constraint.comparison == Comparison.LESS_OR_EQUAL and any(
                columns[name].kind not in (ValueKind.INTEGER, ValueKind.DECIMAL)
                for name in (constraint.left, constraint.right)
            ):
                raise invalid("constraint_types")
        if (
            not self.semantic_columns
            and self.execution.authorization.request.estimated_cost.amount != 0
        ):
            raise invalid("deterministic_estimate_must_be_zero")

    @property
    def semantic_columns(self) -> tuple[DataColumn, ...]:
        return tuple(column for column in self.columns if column.semantic_reason is not None)


class DataIssueCode(StrEnum):
    MALFORMED_SOURCE = "malformed_source"
    MISSING_COLUMN = "missing_column"
    MISSING_VALUE = "missing_value"
    INVALID_VALUE = "invalid_value"
    DUPLICATE = "duplicate"
    RECORD_COUNT = "record_count"
    CONSTRAINT = "constraint"


@dataclass(frozen=True, slots=True)
class DataIssue:
    code: DataIssueCode
    source: Reference | None = None
    row: int | None = None
    column: str | None = None


@dataclass(frozen=True, slots=True)
class DataCell:
    name: str
    value: str | None
    source_path: tuple[str, ...]
    lookup_evidence: Reference | None = None
    semantic_evidence: Reference | None = None


@dataclass(frozen=True, slots=True)
class DataRecord:
    row_id: str
    source: Reference
    locator: str
    collected_at: datetime
    source_digest: str
    row: int
    cells: tuple[DataCell, ...]


@dataclass(frozen=True, slots=True)
class DataArtifact:
    name: str
    media_type: str
    content: str

    @property
    def digest(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DataResult:
    execution_reference: Reference
    records: tuple[DataRecord, ...]
    issues: tuple[DataIssue, ...]
    artifacts: tuple[DataArtifact, ...]
    cost: CostRecord | None
    warnings: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.issues
