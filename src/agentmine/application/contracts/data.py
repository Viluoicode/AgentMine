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


class DuplicatePolicy(StrEnum):
    REJECT_ALL = "REJECT_ALL"


class InputPresence(StrEnum):
    MISSING = "MISSING"
    NULL = "NULL"
    VALUE = "VALUE"


def require_v2(version: int) -> None:
    if type(version) is not int or version != 2:
        raise invalid("partition_version")


@dataclass(frozen=True, slots=True)
class DataPartitionPolicy:
    contract_version: int
    id_column: str
    duplicate_policy: DuplicatePolicy

    def __post_init__(self) -> None:
        require_v2(self.contract_version)
        text(self.id_column, "id_column", 100)
        if not isinstance(self.duplicate_policy, DuplicatePolicy):
            raise invalid("duplicate_policy")


@dataclass(frozen=True, slots=True)
class PartitionAcceptance:
    """Explicit per-task thresholds, not an authorization or QA decision."""

    contract_version: int
    min_clean_records: int
    max_rejected_records: int

    def __post_init__(self) -> None:
        require_v2(self.contract_version)
        if (
            type(self.min_clean_records) is not int
            or type(self.max_rejected_records) is not int
            or not 1 <= self.min_clean_records <= 1000
            or not 0 <= self.max_rejected_records <= 1000
        ):
            raise invalid("partition_thresholds")


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


def validate_partition_binding(
    policy: DataPartitionPolicy | None,
    acceptance: PartitionAcceptance | None,
    columns: tuple[DataColumn, ...],
    unique_by: tuple[str, ...],
    max_records: int,
) -> None:
    """Cross-model validation without importing QA into Data."""
    if policy is None and acceptance is None:
        return
    if not isinstance(policy, DataPartitionPolicy) or not isinstance(
        acceptance, PartitionAcceptance
    ):
        raise invalid("partition_binding")
    # Revalidate frozen objects supplied through an untrusted/misbehaving adapter.
    policy.__post_init__()
    acceptance.__post_init__()
    identifiers = [column for column in columns if column.name == policy.id_column]
    if (
        len(identifiers) != 1
        or identifiers[0].required is not True
        or identifiers[0].kind != ValueKind.TEXT
        or any(column.semantic_reason is not None for column in columns)
        or unique_by != (policy.id_column,)
        or type(max_records) is not int
        or acceptance.min_clean_records > max_records
        or acceptance.max_rejected_records > max_records
    ):
        raise invalid("partition_schema")


@dataclass(frozen=True, slots=True)
class DataPlan:
    execution: Execution
    sources: tuple[DataSource, ...]
    columns: tuple[DataColumn, ...]
    unique_by: tuple[str, ...] = ()
    min_records: int = 1
    max_records: int = 1000
    constraints: tuple[RowConstraint, ...] = ()
    output_policy: DataPartitionPolicy | None = None
    partition_acceptance: PartitionAcceptance | None = None

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

        validate_partition_binding(
            self.output_policy,
            self.partition_acceptance,
            self.columns,
            self.unique_by,
            self.max_records,
        )

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
    input_presence: InputPresence | None = None

    def __post_init__(self) -> None:
        if self.input_presence is not None and not isinstance(self.input_presence, InputPresence):
            raise invalid("input_presence")


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
class DataRowReference:
    source: Reference
    source_digest: str
    row: int
    row_id: str

    def __post_init__(self) -> None:
        require_reference(self.source, "partition_source")
        require_digest(self.source_digest)
        text(self.row_id, "row_id", 100)
        if type(self.row) is not int or not 1 <= self.row <= 1000:
            raise invalid("source_row")


def require_digest(digest: str) -> None:
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise invalid("source_digest")


class SourceParseStatus(StrEnum):
    PARSED = "PARSED"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True, slots=True)
class DataSourceOutcome:
    source: Reference
    source_digest: str
    status: SourceParseStatus
    parsed_count: int | None

    def __post_init__(self) -> None:
        require_reference(self.source, "partition_source")
        require_digest(self.source_digest)
        if not isinstance(self.status, SourceParseStatus):
            raise invalid("parse_status")
        if self.status == SourceParseStatus.MALFORMED:
            if self.parsed_count is not None:
                raise invalid("unknown_source_count")
        elif type(self.parsed_count) is not int or not 0 <= self.parsed_count <= 1000:
            raise invalid("parsed_count")


@dataclass(frozen=True, slots=True)
class PartitionRejection:
    row: DataRowReference
    reasons: tuple[DataIssue, ...]
    duplicate_group: Reference | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.row, DataRowReference)
            or not isinstance(self.reasons, tuple)
            or not self.reasons
        ):
            raise invalid("partition_rejection")
        if any(
            not isinstance(reason, DataIssue)
            or not isinstance(reason.code, DataIssueCode)
            or reason.source != self.row.source
            or reason.row != self.row.row
            for reason in self.reasons
        ):
            raise invalid("rejection_scope")
        if self.duplicate_group is not None:
            require_reference(self.duplicate_group, "duplicate_group")
        if any(reason.code == DataIssueCode.DUPLICATE for reason in self.reasons) != (
            self.duplicate_group is not None
        ):
            raise invalid("duplicate_reason")


@dataclass(frozen=True, slots=True)
class DuplicateIDGroup:
    reference: Reference
    canonical_id: str
    members: tuple[DataRowReference, ...]

    def __post_init__(self) -> None:
        require_reference(self.reference, "duplicate_group")
        text(self.canonical_id, "canonical_id", 32_000)
        if (
            not isinstance(self.members, tuple)
            or not 2 <= len(self.members) <= 1000
            or any(not isinstance(row, DataRowReference) for row in self.members)
            or len(set(self.members)) != len(self.members)
        ):
            raise invalid("duplicate_members")


@dataclass(frozen=True, slots=True)
class DataPartitionAssessment:
    """Retained evidence shape only; C1 does not calculate or authorize partitions."""

    contract_version: int
    policy: DataPartitionPolicy
    clean_rows: tuple[DataRowReference, ...]
    rejected_rows: tuple[PartitionRejection, ...]
    source_outcomes: tuple[DataSourceOutcome, ...]
    duplicate_groups: tuple[DuplicateIDGroup, ...]
    evidence_complete: bool

    def __post_init__(self) -> None:
        require_v2(self.contract_version)
        if (
            not isinstance(self.policy, DataPartitionPolicy)
            or type(self.evidence_complete) is not bool
        ):
            raise invalid("partition_assessment")
        for values, expected, maximum in (
            (self.clean_rows, DataRowReference, 1000),
            (self.rejected_rows, PartitionRejection, 1000),
            (self.source_outcomes, DataSourceOutcome, 10),
            (self.duplicate_groups, DuplicateIDGroup, 500),
        ):
            if (
                not isinstance(values, tuple)
                or len(values) > maximum
                or any(not isinstance(v, expected) for v in values)
            ):
                raise invalid("partition_members")
        if not self.source_outcomes or len(self.clean_rows) + len(self.rejected_rows) > 1000:
            raise invalid("partition_bounds")
        if self.evidence_complete and any(
            source.status != SourceParseStatus.PARSED for source in self.source_outcomes
        ):
            raise invalid("partition_coverage")

        # Validate supplied evidence structure only; never derive a partition from values.
        rows = (*self.clean_rows, *(item.row for item in self.rejected_rows))
        keys = [(row.source, row.source_digest, row.row) for row in rows]
        if len(set(keys)) != len(keys) or len({row.row_id for row in rows}) != len(rows):
            raise invalid("partition_membership")
        sources = {(item.source, item.source_digest): item for item in self.source_outcomes}
        if len(sources) != len(self.source_outcomes):
            raise invalid("partition_sources")
        for row in rows:
            outcome = sources.get((row.source, row.source_digest))
            if outcome is None or outcome.status != SourceParseStatus.PARSED:
                raise invalid("partition_source_binding")
        for source in self.source_outcomes:
            if source.status == SourceParseStatus.PARSED and source.parsed_count != sum(
                row.source == source.source and row.source_digest == source.source_digest
                for row in rows
            ):
                raise invalid("partition_count")
        groups = {group.reference: group for group in self.duplicate_groups}
        if len(groups) != len(self.duplicate_groups):
            raise invalid("duplicate_group_identity")
        rejections = {item.row: item for item in self.rejected_rows}
        for group in self.duplicate_groups:
            if any(
                member not in rejections or rejections[member].duplicate_group != group.reference
                for member in group.members
            ):
                raise invalid("duplicate_group_membership")
        for rejected in self.rejected_rows:
            if rejected.duplicate_group is not None:
                matched_group = groups.get(rejected.duplicate_group)
                if matched_group is None or rejected.row not in matched_group.members:
                    raise invalid("duplicate_group_membership")


@dataclass(frozen=True, slots=True)
class DataResult:
    execution_reference: Reference
    records: tuple[DataRecord, ...]
    issues: tuple[DataIssue, ...]
    artifacts: tuple[DataArtifact, ...]
    cost: CostRecord | None
    warnings: tuple[str, ...]
    partition: DataPartitionAssessment | None = None

    def __post_init__(self) -> None:
        if self.partition is not None and not isinstance(self.partition, DataPartitionAssessment):
            raise invalid("result_partition")
        if self.partition is not None:
            if not isinstance(self.records, tuple) or any(
                not isinstance(row, DataRecord) for row in self.records
            ):
                raise invalid("result_records")
            if any(cell.input_presence is None for row in self.records for cell in row.cells):
                raise invalid("result_input_presence")
            supplied = tuple(
                DataRowReference(row.source, row.source_digest, row.row, row.row_id)
                for row in self.records
            )
            retained = (
                *self.partition.clean_rows,
                *(item.row for item in self.partition.rejected_rows),
            )
            if len(supplied) != len(retained) or set(supplied) != set(retained):
                raise invalid("result_membership")

    @property
    def valid(self) -> bool:
        return not self.issues
