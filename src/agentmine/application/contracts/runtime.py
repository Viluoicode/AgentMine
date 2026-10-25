"""Deterministic Data runtime evidence and persistence commands, never dispatch permission."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from agentmine.application.contracts.data import (
    Comparison,
    DataArtifact,
    DataColumn,
    DataIssue,
    DataPlan,
    DataRecord,
    DataResult,
    DataSource,
    RowConstraint,
    ValueKind,
)
from agentmine.application.contracts.opportunities import OpportunityStatus
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.records import Versioned
from agentmine.domain.budget import Budget
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import CostCategory
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import AuthorizationStatus, CostRecord
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Deliverable, Execution, Task, TaskType


def invalid(field: str) -> DomainError:
    return DomainError(ErrorCode.EVIDENCE_MISMATCH, field, "Invalid deterministic runtime binding")


@dataclass(frozen=True, slots=True)
class InputEvidence:
    source_reference: Reference
    content_reference: Reference

    def __post_init__(self) -> None:
        require_reference(self.source_reference, "source")
        require_reference(self.content_reference, "digest")
        digest = self.content_reference.value
        if (
            not digest.startswith("sha256:")
            or len(digest) != 71
            or any(char not in "0123456789abcdef" for char in digest[7:])
        ):
            raise invalid("input_digest")


@dataclass(frozen=True, slots=True)
class WorkSpecification:
    """Approved immutable snapshots, not a client-supplied Execution or authorization.

    Facts/source authenticity and fresh eligibility remain B2 application duties.
    This checkpoint binds known source context and deterministic processing scope.
    """

    reference: Reference
    task: Task
    ledger_reference: Reference
    actor: Reference
    approved_at: datetime
    source_context: OpportunityStatus
    sources: tuple[DataSource, ...]
    input_evidence: tuple[InputEvidence, ...]
    columns: tuple[DataColumn, ...]
    unique_by: tuple[str, ...] = ()
    min_records: int = 1
    max_records: int = 1000
    constraints: tuple[RowConstraint, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("specification", self.reference),
            ("ledger", self.ledger_reference),
            ("actor", self.actor),
        ):
            require_reference(value, name)
        require_aware_timestamp(self.approved_at)
        if not isinstance(self.task, Task) or self.task.task_type != TaskType.DATA_PROCESSING:
            raise invalid("worker_capability")
        source = self.source_context
        if (
            not isinstance(source, OpportunityStatus)
            or source.opportunity_reference != self.task.opportunity_reference
            or source.is_open is not True
            or not source.deadline_known
            or source.terms_reference is None
            or source.requirements is None
            or source.observed_at > self.approved_at
            or source.deadline != self.task.deadline
            or (source.deadline is not None and source.deadline <= self.approved_at)
        ):
            raise invalid("source_context")
        require_reference(source.source_reference, "source_identity")
        if (
            not isinstance(self.sources, tuple)
            or not 1 <= len(self.sources) <= 10
            or any(not isinstance(item, DataSource) for item in self.sources)
            or len({item.reference for item in self.sources}) != len(self.sources)
            or any(item.collected_at > self.approved_at for item in self.sources)
            or not isinstance(self.input_evidence, tuple)
            or any(not isinstance(item, InputEvidence) for item in self.input_evidence)
            or tuple(
                (item.source_reference, item.content_reference.value)
                for item in self.input_evidence
            )
            != tuple((item.reference, "sha256:" + item.digest) for item in self.sources)
        ):
            raise invalid("input_evidence")
        if (
            not isinstance(self.columns, tuple)
            or not 1 <= len(self.columns) <= 50
            or any(
                not isinstance(item, DataColumn) or item.semantic_reason is not None
                for item in self.columns
            )
            or len({item.name for item in self.columns}) != len(self.columns)
            or not isinstance(self.unique_by, tuple)
            or any(
                not isinstance(name, str) or name not in {col.name for col in self.columns}
                for name in self.unique_by
            )
            or len(set(self.unique_by)) != len(self.unique_by)
            or type(self.min_records) is not int
            or type(self.max_records) is not int
            or not 0 <= self.min_records <= self.max_records <= 1000
            or not isinstance(self.constraints, tuple)
            or len(self.constraints) > 50
            or any(not isinstance(item, RowConstraint) for item in self.constraints)
        ):
            raise invalid("data_scope")
        # Reuse DataPlan's cross-column constraint rules when an authorized Execution exists.
        names = {column.name for column in self.columns}
        if any(item.left not in names or item.right not in names for item in self.constraints):
            raise invalid("constraint_columns")
        columns = {column.name: column for column in self.columns}
        if any(
            item.comparison == Comparison.LESS_OR_EQUAL
            and any(
                columns[name].kind not in (ValueKind.INTEGER, ValueKind.DECIMAL)
                for name in (item.left, item.right)
            )
            for item in self.constraints
        ):
            raise invalid("constraint_types")

    def plan(self, execution: Execution) -> DataPlan:
        if execution.task != self.task:
            raise invalid("task")
        return DataPlan(
            execution,
            self.sources,
            self.columns,
            self.unique_by,
            self.min_records,
            self.max_records,
            self.constraints,
        )


@dataclass(frozen=True, slots=True)
class ExecutionBinding:
    specification_reference: Reference
    execution_reference: Reference
    operation_reference: Reference
    deliverable_reference: Reference

    def __post_init__(self) -> None:
        for name, value in (
            ("specification", self.specification_reference),
            ("execution", self.execution_reference),
            ("operation", self.operation_reference),
            ("deliverable", self.deliverable_reference),
        ):
            require_reference(value, name)


@dataclass(frozen=True, slots=True)
class WorkerRun:
    binding: ExecutionBinding
    specification: WorkSpecification
    plan: DataPlan

    def __post_init__(self) -> None:
        if (
            not isinstance(self.binding, ExecutionBinding)
            or not isinstance(self.specification, WorkSpecification)
            or not isinstance(self.plan, DataPlan)
            or self.binding.specification_reference != self.specification.reference
            or self.binding.execution_reference != self.plan.execution.reference
            or self.binding.operation_reference
            != self.plan.execution.authorization.request.context.operation_reference
            or self.specification.plan(self.plan.execution) != self.plan
        ):
            raise invalid("run")


@dataclass(frozen=True, slots=True)
class WorkerRunStart:
    """Internal application command using authoritative snapshots, not an input DTO.

    Adapter MUST compare both snapshots to storage. No caller-supplied authorization:
    resolve the existing zero-cost commitment by operation ID from the Budget.
    """

    specification: WorkSpecification
    binding: ExecutionBinding
    opportunity_snapshot: Versioned[Opportunity]
    ledger_snapshot: Versioned[Budget]
    started_at: datetime

    def __post_init__(self) -> None:
        require_aware_timestamp(self.started_at)
        if (
            not isinstance(self.specification, WorkSpecification)
            or not isinstance(self.binding, ExecutionBinding)
            or not isinstance(self.opportunity_snapshot, Versioned)
            or not isinstance(self.opportunity_snapshot.value, Opportunity)
            or not isinstance(self.ledger_snapshot, Versioned)
            or not isinstance(self.ledger_snapshot.value, Budget)
        ):
            raise invalid("start_contract")
        spec = self.specification
        op = self.opportunity_snapshot.value
        if (
            self.binding.specification_reference != spec.reference
            or op.state != OpportunityState.PLANNED
            or op.task != spec.task
            or op.execution is not None
            or op.deliverable is not None
            or op.qa is not None
            or self.started_at < spec.approved_at
        ):
            raise invalid("start")
        _ = self.run  # Validate existing Domain/DataPlan invariants before storage writes.

    @property
    def run(self) -> WorkerRun:
        authorization = next(
            (
                auth
                for auth in self.ledger_snapshot.value.outstanding
                if auth.request.context.operation_reference == self.binding.operation_reference
            ),
            None,
        )
        if authorization is None:
            raise invalid("persisted_authorization")
        request = authorization.request
        if (
            request.category != CostCategory.AI
            or request.estimated_cost.amount != 0
            or request.context.human_approval is not None
        ):
            raise invalid("deterministic_authorization")
        decision = self.ledger_snapshot.value.authorize(
            request.estimated_cost,
            request.category,
            replace(request.context, occurred_at=self.started_at),
        )
        if (
            decision.status != AuthorizationStatus.AUTHORIZED
            or decision.authorization != authorization
        ):
            raise invalid("current_authorization")
        execution = Execution(
            self.binding.execution_reference,
            self.specification.task,
            authorization.mode,
            self.started_at,
            authorization,
        )
        return WorkerRun(self.binding, self.specification, self.specification.plan(execution))

    @property
    def opportunity(self) -> Opportunity:
        return self.opportunity_snapshot.value.start(self.run.plan.execution)


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """Trusted worker output evidence; schema/provenance binding is not QA or execution."""

    run: WorkerRun
    result: DataResult

    def __post_init__(self) -> None:
        result = self.result
        if (
            not isinstance(self.run, WorkerRun)
            or not isinstance(result, DataResult)
            or result.execution_reference != self.run.binding.execution_reference
            or not isinstance(result.records, tuple)
            or any(not isinstance(item, DataRecord) for item in result.records)
            or not isinstance(result.issues, tuple)
            or any(not isinstance(item, DataIssue) for item in result.issues)
            or not isinstance(result.artifacts, tuple)
            or any(not isinstance(item, DataArtifact) for item in result.artifacts)
            or not isinstance(result.warnings, tuple)
            or any(not isinstance(item, str) for item in result.warnings)
        ):
            raise invalid("worker_result")
        sources = {item.reference: item for item in self.run.plan.sources}
        for record in result.records:
            source = sources.get(record.source)
            if (
                source is None
                or (record.locator, record.collected_at, record.source_digest)
                != (source.locator, source.collected_at, source.digest)
                or any(cell.semantic_evidence is not None for cell in record.cells)
            ):
                raise invalid("result_provenance")
        allowed = {
            "data.csv": "text/csv",
            "data.json": "application/json",
            "validation.json": "application/json",
        }
        if any(
            not isinstance(item.content, str) or allowed.get(item.name) != item.media_type
            for item in result.artifacts
        ):
            raise invalid("artifacts")
        bundle_content(result)  # Enforce unique nonempty artifact inventory and exact digest.
        cost = result.cost
        request = self.run.plan.execution.authorization.request
        if cost is not None and (
            not isinstance(cost, CostRecord)
            or cost.cost.category != CostCategory.AI
            or cost.actual_cost != request.estimated_cost
            or cost.estimated_cost != request.estimated_cost
            or not request.context.matches_operation(cost.context)
            or cost.context.occurred_at < request.context.occurred_at
        ):
            raise invalid("result_cost")


@dataclass(frozen=True, slots=True)
class WorkerRunFinish:
    retained: WorkerResult
    opportunity_snapshot: Versioned[Opportunity]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.retained, WorkerResult)
            or not isinstance(self.opportunity_snapshot, Versioned)
            or not isinstance(self.opportunity_snapshot.value, Opportunity)
        ):
            raise invalid("finish_contract")
        op = self.opportunity_snapshot.value
        if (
            op.state != OpportunityState.IN_PROGRESS
            or op.execution != self.retained.run.plan.execution
            or op.task != self.retained.run.specification.task
            or op.qa is not None
            or op.deliverable is not None
        ):
            raise invalid("finish")

    @property
    def deliverable(self) -> Deliverable:
        binding = self.retained.run.binding
        return Deliverable(
            binding.deliverable_reference,
            binding.execution_reference,
            1,
            bundle_content(self.retained.result).reference,
        )

    @property
    def opportunity(self) -> Opportunity:
        return self.opportunity_snapshot.value.finish(self.deliverable)


class RecoveryReason(StrEnum):
    NONE = "none"
    RESULT_MISSING = "result_missing"
    FINISH_PENDING = "finish_pending"
    STATE_CHANGED = "state_changed"


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    """Derived checkpoint view; Opportunity.state remains the only business lifecycle."""

    run: WorkerRun
    opportunity_snapshot: Versioned[Opportunity]
    result: DataResult | None
    finished: bool

    @property
    def reason(self) -> RecoveryReason:
        if self.finished:
            return RecoveryReason.NONE
        op = self.opportunity_snapshot.value
        if (
            op.state != OpportunityState.IN_PROGRESS
            or op.execution != self.run.plan.execution
            or op.qa is not None
        ):
            return RecoveryReason.STATE_CHANGED
        return (
            RecoveryReason.RESULT_MISSING if self.result is None else RecoveryReason.FINISH_PENDING
        )
