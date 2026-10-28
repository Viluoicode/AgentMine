"""Read-only local data history; never routes a revision through first-run dispatch."""

from dataclasses import dataclass

from agentmine.application.contracts.data_revision import (
    RevisionParent,
    RevisionReason,
    RevisionView,
    require,
)
from agentmine.application.contracts.runtime import RuntimeStatus, WorkerRun, WorkSpecification
from agentmine.application.ports.data_revision import RevisionRuntimeRepository
from agentmine.application.ports.repositories import OpportunityRepository
from agentmine.application.ports.runtime import WorkerRunReader
from agentmine.application.use_cases.context import load
from agentmine.application.use_cases.data_revision import GetDataRevision
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class LocalDataHistory:
    first: WorkerRunReader
    revisions: RevisionRuntimeRepository
    opportunities: OpportunityRepository

    def get_specification(self, reference: Reference) -> WorkSpecification | None:
        first = self.first.get_specification(reference)
        revised = self.revisions.specification(reference)
        require(first is None or revised is None, RevisionReason.IDENTITY_CONFLICT)
        return first if first is not None else revised

    def get_run(self, reference: Reference) -> WorkerRun | None:
        view = self.inspect(reference)
        return None if view is None else view.run

    def inspect(self, reference: Reference) -> RuntimeStatus | None:
        first = self.first.inspect(reference)
        revision = self.revisions.for_execution(reference)
        require(first is None or revision is None, RevisionReason.IDENTITY_CONFLICT)
        if first is not None:
            if first.deliverable is not None:
                require(
                    first.deliverable.version == 1
                    and first.deliverable.reference == first.run.binding.deliverable_reference
                    and first.deliverable.execution_reference == reference
                )
            return first
        if revision is None:
            return None
        view = self.revisions.inspect(revision)
        require(view is not None and view.run is not None)
        assert view is not None and view.run is not None
        require(view.run.worker.binding.execution_reference == reference)
        return RuntimeStatus(
            view.run.worker,
            load(self.opportunities, view.request.parent_snapshot.value.reference),
            None if view.result is None else view.result.result,
            view.deliverable is not None,
            view.reason == RevisionReason.UNKNOWN_EFFECT,
            view.deliverable,
            view.request.parent_snapshot.value.qa,
            view.run.started_snapshot.revision,
        )


@dataclass(frozen=True, slots=True)
class GetCompletedDataParent:
    revisions: RevisionRuntimeRepository
    operator: Reference
    ledger_reference: Reference

    def execute(self, execution: Reference) -> RevisionParent:
        parent = self.revisions.parent(execution)
        require(parent is not None)
        assert parent is not None
        require(
            parent.run.specification.actor == self.operator
            and parent.run.specification.ledger_reference == self.ledger_reference,
            RevisionReason.APPROVAL_REQUIRED,
        )
        return parent


@dataclass(frozen=True, slots=True)
class GetRevisionForExecution:
    repository: RevisionRuntimeRepository
    get: GetDataRevision

    def execute(self, execution: Reference) -> RevisionView | None:
        reference = self.repository.for_execution(execution)
        return None if reference is None else self.get.execute(reference)
