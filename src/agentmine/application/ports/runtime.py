"""Durable first-run Data evidence; no orchestration, authorization or provider dispatch."""

from typing import Protocol

from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    RuntimeStatus,
    WorkerResult,
    WorkerRun,
    WorkerRunFinish,
    WorkerRunStart,
    WorkSpecification,
)
from agentmine.domain.values import Reference


class WorkerRuntimeRepository(Protocol):
    """Application owns identities/bindings; adapters own atomic persistence.

    Equal immutable operations return False; conflicting identities/revisions raise
    CONFLICT. Start creates task ownership, run, Execution, DataPlan and Opportunity
    transition in ONE transaction after matching authoritative spec/op/budget/source.
    True means newly persisted start, never permission to bypass B2 preflight.
    Result retention is immutable and distinct from finish. Finish checks retained
    result/run and current Opportunity revision, then atomically persists content,
    deliverable, Opportunity and completion marker. Identical completed retries are
    historical readback and never rewind later lifecycle states. No ledger mutation,
    external I/O or automatic redispatch belongs in this port.
    """

    def save_specification(self, specification: WorkSpecification) -> bool: ...
    def get_specification(self, reference: Reference) -> WorkSpecification | None: ...
    def get_run(self, execution_reference: Reference) -> WorkerRun | None: ...
    def has_ai_evidence(self, binding: ExecutionBinding) -> bool:
        """Inspect semantic claims/responses even before a runtime run exists.

        True blocks deterministic execution; it is never permission to retry AI.
        """
        ...

    def start(self, command: WorkerRunStart) -> bool: ...
    def save_result(self, result: WorkerResult) -> bool: ...
    def finish(self, command: WorkerRunFinish) -> bool: ...
    def inspect(self, execution_reference: Reference) -> RuntimeStatus | None: ...
    def incomplete(self) -> tuple[RuntimeStatus, ...]: ...
