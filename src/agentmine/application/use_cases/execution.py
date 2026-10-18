"""Budget-first dispatch and deterministic QA recording. Providers remain injected."""

from dataclasses import dataclass

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import (
    AIResponse,
    DeliverableDraft,
    ReferencedText,
    WorkRequest,
)
from agentmine.application.contracts.records import BudgetCommit
from agentmine.application.contracts.workflow import ExecuteTaskRequest, ExecutionResult
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.ports.approval import ApprovalRepository
from agentmine.application.ports.repositories import (
    CostLedgerRepository,
    ExecutionRepository,
    OpportunityRepository,
)
from agentmine.application.ports.services import Clock, LLMProvider, OpportunitySource
from agentmine.application.use_cases.context import (
    content_reference,
    load,
    refresh,
    require_state,
    save,
)
from agentmine.domain.finance import CostCategory
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import AuthorizationStatus, CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable, Execution, QAResult


@dataclass(frozen=True, slots=True)
class ExecuteTask:
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    ledger: CostLedgerRepository
    provider: LLMProvider
    source: OpportunitySource
    clock: Clock
    approvals: ApprovalRepository | None = None

    def execute(self, request: ExecuteTaskRequest) -> ExecutionResult:
        previous = load(self.opportunities, request.opportunity_reference)
        original = self.executions.get_work_request(request.execution_reference)
        if original is not None and original != request:
            raise PortError(PortErrorCode.CONFLICT, "execute", "Execution identity reused")
        opportunity = previous.value
        if (
            opportunity.execution is not None
            and opportunity.execution.reference == request.execution_reference
        ):
            if original is None:
                raise PortError(
                    PortErrorCode.INVALID_RESPONSE, "execute", "Execution journal missing"
                )
            if opportunity.deliverable is not None:
                return ExecutionResult(opportunity, None)
            if opportunity.qa is not None:
                raise ApplicationError(
                    ApplicationErrorCode.INVALID_STATE, "execute", "Failed QA requires rework"
                )
            cached = self.executions.get_work_response(request.execution_reference)
            if cached is None:
                raise PortError(
                    PortErrorCode.OUTCOME_UNKNOWN, "execute", "Do not redispatch uncertain work"
                )
            require_state(opportunity, OpportunityState.IN_PROGRESS)
            return ExecutionResult(self._finish(request, cached), None)
        require_state(opportunity, OpportunityState.PLANNED)
        status = refresh(self.opportunities, self.source, self.clock, opportunity.reference)
        if opportunity.task is None:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_STATE, "execute", "Planned task missing"
            )
        if status.deadline != opportunity.task.deadline:
            raise PortError(
                PortErrorCode.CONFLICT, "execute", "Deadline changed; replan before execution"
            )
        # Validate identities/version before reservation or provider I/O.
        Deliverable(
            request.deliverable_reference,
            request.execution_reference,
            request.version,
            Reference("pending"),
        )
        decision = BudgetManager(
            self.ledger, request.ledger_reference, self.clock, self.approvals
        ).authorize(
            request.estimated_cost,
            CostContext(
                request.operation_reference,
                OperationType.TASK_EXECUTION,
                self.clock.now(),
                opportunity.task.reference,
                opportunity.reference,
                request.spending_approval,
            ),
        )
        if decision.status == AuthorizationStatus.DENIED:
            waiting = save(self.opportunities, previous, opportunity.wait_for_budget(decision))
            return ExecutionResult(waiting, decision)
        if decision.authorization is None:
            return ExecutionResult(opportunity, decision)
        candidate = Execution(
            request.execution_reference,
            opportunity.task,
            decision.mode,
            self.clock.now(),
            decision.authorization,
        )
        execution = self.executions.get(request.execution_reference) or candidate
        if execution.task != opportunity.task or execution.authorization != decision.authorization:
            raise PortError(PortErrorCode.CONFLICT, "execute", "Execution journal scope changed")
        self.executions.save_work_request(request)
        self.executions.save(execution)
        save(self.opportunities, previous, opportunity.start(execution))
        # IN_PROGRESS is persisted before dispatch: a crash never permits blind replay.
        response = self.provider.perform_work(WorkRequest(execution, request.inputs))
        self.executions.save_work_response(execution.reference, response)
        return ExecutionResult(self._finish(request, response), decision)

    def _finish(
        self, request: ExecuteTaskRequest, response: AIResponse[DeliverableDraft]
    ) -> Opportunity:
        previous = load(self.opportunities, request.opportunity_reference)
        execution = previous.value.execution
        if execution is None or execution.reference != request.execution_reference:
            raise PortError(PortErrorCode.INVALID_RESPONSE, "execute", "Execution mismatch")
        if response.operation_reference != request.operation_reference:
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "execute", "Provider operation mismatch"
            )
        measurement = response.actual_cost
        if measurement is not None:
            context = execution.authorization.request.context
            if (
                not context.matches_operation(measurement.context)
                or measurement.context.occurred_at > self.clock.now()
            ):
                raise PortError(
                    PortErrorCode.INVALID_RESPONSE, "execute", "Measurement scope mismatch"
                )
            snapshot = self.ledger.get(request.ledger_reference)
            if snapshot is None:
                raise ApplicationError(
                    ApplicationErrorCode.NOT_FOUND, "record", "Budget ledger missing"
                )
            recording = snapshot.value.record(
                measurement.actual_cost, CostCategory.AI, measurement.context
            )
            self.ledger.commit(
                BudgetCommit(
                    request.ledger_reference, recording.budget, snapshot.revision, recording
                )
            )
        if not response.result.content.strip():
            raise PortError(PortErrorCode.INVALID_RESPONSE, "execute", "Empty work product")
        content = ReferencedText(
            content_reference(response.result.content), response.result.content
        )
        deliverable = Deliverable(
            request.deliverable_reference, execution.reference, request.version, content.reference
        )
        updated = previous.value.finish(deliverable)
        self.executions.save_content(content)
        self.executions.save_deliverable(deliverable)
        return save(self.opportunities, previous, updated)


@dataclass(frozen=True, slots=True)
class RunQA:
    """Record a resolved QA assessment; no QA algorithm or paid AI reviewer is invented."""

    opportunities: OpportunityRepository
    executions: ExecutionRepository

    def execute(self, reference: Reference, result: QAResult) -> Opportunity:
        previous = load(self.opportunities, reference)
        if previous.value.qa == result:
            return previous.value
        updated = previous.value.review_qa(result)
        self.executions.save_qa(result)
        return save(self.opportunities, previous, updated)
