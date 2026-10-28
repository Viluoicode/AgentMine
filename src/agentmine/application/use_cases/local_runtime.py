"""Explicit local operator preparation/inspection/recovery/export; no work loop."""

from dataclasses import dataclass

from agentmine.application.contracts.execution_evidence import DataExecutionEvidence
from agentmine.application.contracts.local_runtime import ArtifactExport, PrepareDataRequest
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.runtime import InputEvidence, RuntimeStatus, WorkSpecification
from agentmine.application.contracts.worker_execution import (
    ExecuteWorkerRequest,
    WorkerExecutionOutcome,
)
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.ports.eligibility_review import EligibilityReviewRepository
from agentmine.application.ports.local_runtime import ArtifactExporter, DataInputReader
from agentmine.application.ports.repositories import EvaluationRepository, OpportunityRepository
from agentmine.application.ports.runtime import WorkerRunReader, WorkerRuntimeRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.context import load, observe_status, require_state
from agentmine.application.use_cases.worker_execution import ExecuteWorkerTask
from agentmine.application.use_cases.worker_preflight import WorkerPreflight
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class GetOperatorOpportunity:
    opportunities: OpportunityRepository

    def execute(self, reference: Reference) -> Versioned[Opportunity]:
        return load(self.opportunities, reference)


@dataclass(frozen=True, slots=True)
class PrepareDataSpecification:
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    runtime: WorkerRuntimeRepository
    reader: DataInputReader
    source: OpportunitySource
    clock: Clock
    operator: Reference
    ledger_reference: Reference
    eligibility_reviews: EligibilityReviewRepository

    def execute(self, request: PrepareDataRequest) -> WorkSpecification:
        previous = load(self.opportunities, request.opportunity_reference)
        require_state(previous.value, OpportunityState.PLANNED)
        if previous.value.task is None:
            raise PortError(PortErrorCode.CONFLICT, "prepare_work", "Planned task required")
        evaluation = self.evaluations.get(request.evaluation_reference)
        if evaluation is None:
            raise PortError(
                PortErrorCode.CONFLICT,
                "prepare_work",
                "Retained economic/scoring evidence required",
            )
        sources = self.reader.load(request.inputs)
        existing = self.runtime.get_specification(request.reference)
        status = observe_status(
            self.opportunities, self.source, self.clock, request.opportunity_reference
        )
        candidate = WorkSpecification(
            request.reference,
            previous.value.task,
            self.ledger_reference,
            self.operator,
            self.clock.now() if existing is None else existing.approved_at,
            status if existing is None else existing.source_context,
            sources,
            tuple(
                InputEvidence(item.reference, Reference("sha256:" + item.digest))
                for item in sources
            ),
            request.columns,
            request.unique_by,
            request.min_records,
            request.max_records,
            request.constraints,
            DataExecutionEvidence(
                request.eligibility,
                request.policy,
                evaluation,
                request.eligibility_review_reference,
            ),
            request.acceptance,
        )
        if existing is not None and existing != candidate:
            raise PortError(PortErrorCode.CONFLICT, "prepare_work", "Specification identity reused")
        reason = WorkerPreflight(
            self.opportunities,
            self.evaluations,
            self.source,
            self.clock,
            self.operator,
            self.eligibility_reviews,
        ).check(candidate, previous.value)
        if reason is not None:
            raise ApplicationError(ApplicationErrorCode.UNRESOLVED, "prepare_work", reason.value)
        if load(self.opportunities, request.opportunity_reference) != previous:
            raise PortError(
                PortErrorCode.CONFLICT, "prepare_work", "Opportunity changed during preparation"
            )
        self.runtime.save_specification(candidate)
        return candidate


@dataclass(frozen=True, slots=True)
class GetDataSpecification:
    runtime: WorkerRunReader

    def execute(self, reference: Reference) -> WorkSpecification:
        value = self.runtime.get_specification(reference)
        if value is None:
            raise ApplicationError(
                ApplicationErrorCode.NOT_FOUND, "specification", "Specification not found"
            )
        return value


@dataclass(frozen=True, slots=True)
class GetWorkerRuntime:
    runtime: WorkerRunReader

    def execute(self, reference: Reference) -> RuntimeStatus:
        value = self.runtime.inspect(reference)
        if value is None:
            raise ApplicationError(ApplicationErrorCode.NOT_FOUND, "runtime", "Execution not found")
        return value


@dataclass(frozen=True, slots=True)
class RecoverDataExecution:
    runtime: WorkerRuntimeRepository
    execute_worker: ExecuteWorkerTask

    def execute(self, reference: Reference) -> WorkerExecutionOutcome:
        view = GetWorkerRuntime(self.runtime).execute(reference)
        return self.execute_worker.execute(
            ExecuteWorkerRequest(view.run.binding, view.opportunity_snapshot.revision)
        )


@dataclass(frozen=True, slots=True)
class ExportDataArtifacts:
    runtime: WorkerRunReader
    exporter: ArtifactExporter
    operator: Reference

    def execute(self, reference: Reference) -> ArtifactExport:
        view = GetWorkerRuntime(self.runtime).execute(reference)
        if (
            view.run.specification.actor != self.operator
            or view.result is None
            or view.deliverable is None
        ):
            raise PortError(
                PortErrorCode.CONFLICT, "export", "Matching operator and retained result required"
            )
        return self.exporter.export(
            reference,
            bundle_content(view.result).reference,
            view.result.artifacts,
            deliverable=view.deliverable,
        )
