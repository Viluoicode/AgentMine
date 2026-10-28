"""Atomic local revision evidence; methods do not grant provider dispatch permission."""

from typing import Protocol

from agentmine.application.contracts.data_revision import (
    DataRevisionApproval,
    DataRevisionRequest,
    RevisionAllocation,
    RevisionFinish,
    RevisionStart,
    RevisionView,
)
from agentmine.application.contracts.runtime import ExecutionBinding, WorkerResult
from agentmine.domain.values import Reference


class RevisionRuntimeRepository(Protocol):
    """One authoritative workspace/ledger. Conflicts preserve all original evidence.

    Approval, successor ownership, version and immutable allocation commit together.
    Start/finish compare authoritative snapshots and commit each boundary atomically.
    Same-ID readback never authorizes execution or reallocation. No external I/O.
    """

    def prepare(self, request: DataRevisionRequest) -> bool: ...
    def get_request(self, reference: Reference) -> DataRevisionRequest | None: ...
    def approve(
        self, reference: Reference, approval: DataRevisionApproval, binding: ExecutionBinding
    ) -> RevisionAllocation: ...
    def get_allocation(self, reference: Reference) -> RevisionAllocation | None: ...
    def start(self, command: RevisionStart) -> bool: ...
    def save_result(self, reference: Reference, result: WorkerResult) -> bool: ...
    def finish(self, command: RevisionFinish) -> bool: ...
    def inspect(self, reference: Reference) -> RevisionView | None: ...
