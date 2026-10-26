"""First-version deterministic Data execution and original-identity local recovery."""

import logging
from dataclasses import dataclass, replace
from decimal import Decimal

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.runtime import (
    RuntimeStatus,
    WorkerResult,
    WorkerRunFinish,
    WorkerRunStart,
)
from agentmine.application.contracts.worker_execution import (
    ExecuteWorkerRequest,
    WorkerExecutionOutcome,
    WorkerExecutionReason,
    WorkerExecutionStatus,
)
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.ports.data import DataJournal
from agentmine.application.ports.eligibility_review import EligibilityReviewRepository
from agentmine.application.ports.repositories import EvaluationRepository, OpportunityRepository
from agentmine.application.ports.runtime import WorkerRuntimeRepository
from agentmine.application.ports.services import OpportunitySource
from agentmine.application.use_cases.worker_preflight import WorkerPreflight
from agentmine.application.workers.data import DataWorker
from agentmine.domain.errors import DomainError
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import AuthorizationStatus, CostContext, OperationType
from agentmine.domain.values import Reference, require_reference


def blocked(reason: WorkerExecutionReason) -> WorkerExecutionOutcome:
    return WorkerExecutionOutcome(WorkerExecutionStatus.BLOCKED, reason)


@dataclass(frozen=True, slots=True)
class ExecuteWorkerTask:
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    runtime: WorkerRuntimeRepository
    budget: BudgetManager
    journal: DataJournal
    source: OpportunitySource
    operator: Reference
    eligibility_reviews: EligibilityReviewRepository | None = None

    def __post_init__(self) -> None:
        require_reference(self.operator, "operator")

    def execute(self, request: ExecuteWorkerRequest) -> WorkerExecutionOutcome:
        try:
            outcome = self._execute(request)
        except PortError as error:
            reason = {
                PortErrorCode.CONFLICT: WorkerExecutionReason.STATE_CONFLICT,
                PortErrorCode.OUTCOME_UNKNOWN: WorkerExecutionReason.PERSISTENCE_OUTCOME_UNKNOWN,
                PortErrorCode.INVALID_RESPONSE: WorkerExecutionReason.EVIDENCE_INVALID,
                PortErrorCode.UNSUPPORTED: WorkerExecutionReason.EVIDENCE_INVALID,
                PortErrorCode.UNAVAILABLE: WorkerExecutionReason.PERSISTENCE_UNAVAILABLE,
            }[error.code]
            status = (
                WorkerExecutionStatus.BLOCKED
                if error.code in (PortErrorCode.INVALID_RESPONSE, PortErrorCode.UNSUPPORTED)
                else WorkerExecutionStatus.RECOVERABLE
            )
            outcome = WorkerExecutionOutcome(status, reason)
        except (DomainError, ApplicationError):
            outcome = blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        logging.getLogger(__name__).info(
            "worker_execution_result",
            extra={
                "execution_reference": request.binding.execution_reference.value,
                "operation_reference": request.binding.operation_reference.value,
                "status": outcome.status.value,
                "reason_code": outcome.reason.value,
            },
        )
        return outcome

    def _execute(self, request: ExecuteWorkerRequest) -> WorkerExecutionOutcome:
        binding = request.binding
        spec = self.runtime.get_specification(binding.specification_reference)
        if spec is None:
            return blocked(WorkerExecutionReason.NOT_FOUND)
        spec = replace(spec)
        if spec.actor != self.operator or spec.approved_at > self.budget.clock.now():
            return blocked(WorkerExecutionReason.APPROVAL_DENIED)
        if spec.execution_evidence is None or spec.ledger_reference != self.budget.ledger_reference:
            return blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        view = self.runtime.inspect(binding.execution_reference)
        if view is not None:
            if view.run.binding != binding or view.run.specification != spec:
                return blocked(WorkerExecutionReason.IDENTITY_CONFLICT)
            if view.ai_evidence_present:
                return blocked(WorkerExecutionReason.EXTERNAL_OUTCOME_UNKNOWN)
            if view.finished:
                return WorkerExecutionOutcome(
                    WorkerExecutionStatus.COMPLETED,
                    WorkerExecutionReason.NONE,
                    view.opportunity_snapshot.value,
                    view.result,
                )
            if (
                view.opportunity_snapshot.value.state != OpportunityState.IN_PROGRESS
                or view.opportunity_snapshot.value.execution != view.run.plan.execution
                or view.opportunity_snapshot.value.qa is not None
            ):
                return blocked(WorkerExecutionReason.STATE_CONFLICT)
            if view.result is not None:
                return self._finish(view)  # No new execution/refresh/reauthorization.
            previous = view.opportunity_snapshot
        else:
            initial = self.opportunities.get(spec.task.opportunity_reference)
            if initial is None:
                return blocked(WorkerExecutionReason.NOT_FOUND)
            previous = initial
            if previous.revision != request.expected_opportunity_revision:
                return blocked(WorkerExecutionReason.STALE_REVISION)
            if previous.value.state != OpportunityState.PLANNED or previous.value.task != spec.task:
                return blocked(WorkerExecutionReason.STATE_CONFLICT)
        reason = WorkerPreflight(
            self.opportunities,
            self.evaluations,
            self.source,
            self.budget.clock,
            self.operator,
            self.eligibility_reviews,
        ).check(spec, previous.value)
        if reason is not None:
            return blocked(reason)
        if self.opportunities.get(spec.task.opportunity_reference) != previous:
            return blocked(WorkerExecutionReason.STALE_REVISION)
        if (
            self.runtime.has_ai_evidence(binding)
            or self.journal.get_response(binding.execution_reference) is not None
        ):
            return blocked(WorkerExecutionReason.EXTERNAL_OUTCOME_UNKNOWN)
        if view is None:
            ledger = self.budget.ledger.get(self.budget.ledger_reference)
            if ledger is None:
                return blocked(WorkerExecutionReason.NOT_FOUND)
            zero = Money(Decimal(0), ledger.value.policy.monthly_ai_budget.currency)
            decision = self.budget.authorize(
                zero,
                CostContext(
                    binding.operation_reference,
                    OperationType.TASK_EXECUTION,
                    self.budget.clock.now(),
                    spec.task.reference,
                    spec.task.opportunity_reference,
                ),
            )
            if decision.status != AuthorizationStatus.AUTHORIZED:
                reason = (
                    WorkerExecutionReason.BUDGET_DENIED
                    if decision.status == AuthorizationStatus.DENIED
                    else WorkerExecutionReason.SPENDING_APPROVAL_REQUIRED
                )
                return WorkerExecutionOutcome(
                    WorkerExecutionStatus.BLOCKED, reason, previous.value, decision=decision
                )
            latest = self.budget.ledger.get(self.budget.ledger_reference)
            if latest is None:
                return blocked(WorkerExecutionReason.NOT_FOUND)
            command = WorkerRunStart(spec, binding, previous, latest, self.budget.clock.now())
            if not self.runtime.start(command):
                # Concurrent same-ID ownership is inspection/recovery, never a new dispatch.
                return WorkerExecutionOutcome(
                    WorkerExecutionStatus.RECOVERABLE, WorkerExecutionReason.STATE_CONFLICT
                )
            previous = Versioned(command.opportunity, previous.revision + 1)
            view = RuntimeStatus(command.run, previous, None, False)
        return self._work(view, previous)

    def _work(
        self, view: RuntimeStatus, previous: Versioned[Opportunity]
    ) -> WorkerExecutionOutcome:
        if self.opportunities.get(previous.value.reference) != previous:
            return blocked(WorkerExecutionReason.STALE_REVISION)
        try:
            result = DataWorker(self.budget, self.journal, llm=None).execute(view.run.plan)
        except PortError as error:
            if error.code == PortErrorCode.OUTCOME_UNKNOWN:
                return blocked(WorkerExecutionReason.EXTERNAL_OUTCOME_UNKNOWN)
            raise
        except Exception:
            return WorkerExecutionOutcome(
                WorkerExecutionStatus.RECOVERABLE,
                WorkerExecutionReason.WORKER_FAILED,
                previous.value,
            )
        retained = WorkerResult(view.run, result)
        self.runtime.save_result(retained)
        return self._finish(RuntimeStatus(view.run, previous, result, False))

    def _finish(self, view: RuntimeStatus) -> WorkerExecutionOutcome:
        assert view.result is not None
        retained = WorkerResult(view.run, view.result)
        cost = retained.result.cost
        if cost is None or cost.context.occurred_at > self.budget.clock.now():
            return blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        # DataWorker persists its result before accounting. Repair that gap from
        # retained measured evidence; Domain record is idempotent, not guessed zero.
        self.budget.record(
            view.run.plan.execution.authorization, cost.actual_cost, cost.context.occurred_at
        )
        self.runtime.save_result(retained)
        completion = WorkerRunFinish(retained, view.opportunity_snapshot)
        self.runtime.finish(completion)
        current = self.opportunities.get(view.run.specification.task.opportunity_reference)
        return WorkerExecutionOutcome(
            WorkerExecutionStatus.COMPLETED,
            WorkerExecutionReason.NONE,
            None if current is None else current.value,
            retained.result,
        )
