"""Load approved retained evidence and delegate exclusively to existing DeliverableQA."""

from dataclasses import dataclass

from agentmine.application.contracts.operational_qa import OperationalQAStatus, QAApplicationBinding
from agentmine.application.contracts.qa import QAInspection, bundle_content
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.ports.operational_qa import OperationalQARepository
from agentmine.application.ports.qa import QAJournal
from agentmine.application.ports.repositories import ExecutionRepository, OpportunityRepository
from agentmine.application.ports.runtime import WorkerRuntimeRepository
from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.context import check_content, load, require_state
from agentmine.application.use_cases.deliverable_qa import DeliverableQA
from agentmine.application.use_cases.worker_preflight import WorkerPreflight
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAReport
from agentmine.domain.values import Reference


def invalid(message: str) -> PortError:
    return PortError(PortErrorCode.CONFLICT, "operational_qa", message)


@dataclass(frozen=True, slots=True)
class RunOperationalDataQA:
    runtime: WorkerRuntimeRepository
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    repository: OperationalQARepository
    journal: QAJournal
    validator: DeliverableQA
    preflight: WorkerPreflight
    clock: Clock
    operator: Reference
    ledger_reference: Reference

    def execute(self, execution: Reference, inspection_reference: Reference) -> QAReport:
        run = self.runtime.get_run(execution)
        if run is None:
            raise ApplicationError(
                ApplicationErrorCode.NOT_FOUND, "qa", "Retained execution required"
            )
        criteria = run.specification.acceptance
        if (
            run.specification.actor != self.operator
            or run.specification.ledger_reference != self.ledger_reference
        ):
            raise invalid("Matching operator/workspace required")
        if criteria is None:
            raise invalid(
                "Approved acceptance criteria missing; criteria must be frozen before execution"
            )
        if self.validator.llm is not None or self.validator.budget is not None:
            raise invalid("Operational Data QA must not configure paid AI")
        owner = self.repository.for_execution(execution)
        if owner is not None and owner.reference != inspection_reference:
            raise invalid("Deliverable already bound to another inspection")
        binding = self.repository.get_binding(inspection_reference)
        cached = self.journal.get_report(inspection_reference)
        if binding is not None:
            inspection = self.repository.get_inspection(inspection_reference)
            if (
                binding.execution_reference != execution
                or binding.actor != self.operator
                or inspection is None
                or inspection.plan != run.plan
                or inspection.formats != criteria.formats
                or inspection.requirements != criteria.requirements
            ):
                raise invalid("Inspection identity/evidence changed")
            if cached is not None and self.repository.applied(inspection_reference):
                return self.validator.execute(inspection, binding=binding)
        else:
            inspection = None
            if cached is not None:
                raise invalid("Unbound report cannot authorize lifecycle changes")
        view = self.runtime.inspect(execution)
        if view is None or not view.finished or view.result is None or view.ai_evidence_present:
            raise invalid("Completed deterministic execution and retained result required")
        current = view.opportunity_snapshot
        require_state(current.value, OpportunityState.QA_PENDING)
        deliverable = self.executions.get_deliverable(run.binding.deliverable_reference, 1)
        if (
            deliverable is None
            or current.value.deliverable != deliverable
            or current.value.execution != run.plan.execution
            or self.executions.get(execution) != run.plan.execution
        ):
            raise invalid("Authoritative plan/execution/deliverable mismatch")
        content = self.executions.get_content(deliverable.content_reference)
        if content is None:
            raise invalid("Exact retained content required")
        check_content(content, deliverable.content_reference)
        if bundle_content(view.result) != content:
            raise invalid("Plan/result/deliverable content mismatch")
        candidate = QAInspection(
            inspection_reference,
            deliverable,
            run.plan,
            view.result,
            criteria.formats,
            criteria.requirements,
        )
        if inspection is not None and candidate != inspection:
            raise invalid("Retained QA inspection differs from authoritative evidence")
        if binding is not None and binding.opportunity_snapshot != current:
            raise invalid("Opportunity changed after inspection claim")
        if cached is None:
            reason = self.preflight.check(run.specification, current.value)
            if reason is not None:
                raise ApplicationError(
                    ApplicationErrorCode.UNRESOLVED, "qa_preflight", reason.value
                )
            if load(self.opportunities, current.value.reference) != current:
                raise invalid("Opportunity changed during QA preflight")
        if binding is None:
            binding = QAApplicationBinding(
                inspection_reference,
                execution,
                deliverable,
                current,
                self.operator,
                self.clock.now(),
            )
        return self.validator.execute(candidate, binding=binding)


@dataclass(frozen=True, slots=True)
class GetOperationalQAStatus:
    runtime: WorkerRuntimeRepository
    repository: OperationalQARepository
    journal: QAJournal

    def execute(self, execution: Reference) -> OperationalQAStatus:
        binding = self.repository.for_execution(execution)
        return OperationalQAStatus(
            binding,
            None if binding is None else self.journal.get_report(binding.reference),
            False if binding is None else self.repository.applied(binding.reference),
        )
