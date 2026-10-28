"""Original-identity revision dispatch and retained-result recovery, zero AI only."""

import logging
from dataclasses import dataclass, replace
from decimal import Decimal

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.data_revision import (
    RevisionError,
    RevisionFinish,
    RevisionReason,
    RevisionStart,
    RevisionView,
)
from agentmine.application.contracts.runtime import WorkerResult
from agentmine.application.contracts.worker_execution import (
    WorkerExecutionOutcome,
    WorkerExecutionReason,
    WorkerExecutionStatus,
)
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.ports.data import DataJournal
from agentmine.application.ports.data_revision import RevisionRuntimeRepository
from agentmine.application.ports.repositories import EvaluationRepository, OpportunityRepository
from agentmine.application.ports.services import OpportunitySource
from agentmine.application.use_cases.context import load
from agentmine.application.use_cases.revision_preflight import RevisionPreflight
from agentmine.application.workers.data import DataWorker
from agentmine.domain.errors import DomainError
from agentmine.domain.money import Money
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import AuthorizationStatus, CostContext, OperationType
from agentmine.domain.values import Reference


def blocked(reason: WorkerExecutionReason) -> WorkerExecutionOutcome:
    return WorkerExecutionOutcome(WorkerExecutionStatus.BLOCKED, reason)


@dataclass(frozen=True, slots=True)
class ExecuteDataRevision:
    repository: RevisionRuntimeRepository
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    budget: BudgetManager
    journal: DataJournal
    source: OpportunitySource
    operator: Reference

    def execute(self, reference: Reference, *, confirm: bool) -> WorkerExecutionOutcome:
        try:
            outcome = self._execute(reference, confirm)
        except PortError as error:
            recoverable = error.code in (
                PortErrorCode.CONFLICT,
                PortErrorCode.UNAVAILABLE,
                PortErrorCode.OUTCOME_UNKNOWN,
            )
            reason = {
                PortErrorCode.CONFLICT: WorkerExecutionReason.STATE_CONFLICT,
                PortErrorCode.UNAVAILABLE: WorkerExecutionReason.PERSISTENCE_UNAVAILABLE,
                PortErrorCode.OUTCOME_UNKNOWN: WorkerExecutionReason.PERSISTENCE_OUTCOME_UNKNOWN,
                PortErrorCode.INVALID_RESPONSE: WorkerExecutionReason.EVIDENCE_INVALID,
                PortErrorCode.UNSUPPORTED: WorkerExecutionReason.EVIDENCE_INVALID,
            }[error.code]
            outcome = WorkerExecutionOutcome(
                WorkerExecutionStatus.RECOVERABLE if recoverable else WorkerExecutionStatus.BLOCKED,
                reason,
            )
        except RevisionError as error:
            outcome = blocked(
                WorkerExecutionReason.EXTERNAL_OUTCOME_UNKNOWN
                if error.reason == RevisionReason.UNKNOWN_EFFECT
                else WorkerExecutionReason.STATE_CONFLICT
            )
        except (DomainError, ApplicationError):
            outcome = blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        logging.getLogger(__name__).info(
            "revision_execution_result",
            extra={
                "revision_reference": reference.value,
                "status": outcome.status.value,
                "reason_code": outcome.reason.value,
            },
        )
        return outcome

    def _execute(self, reference: Reference, confirm: bool) -> WorkerExecutionOutcome:
        if confirm is not True:
            return blocked(WorkerExecutionReason.APPROVAL_DENIED)
        view = self.repository.inspect(reference)
        if view is None:
            return blocked(WorkerExecutionReason.NOT_FOUND)
        allocation = view.allocation
        if allocation is None:
            return blocked(WorkerExecutionReason.APPROVAL_DENIED)
        req = replace(view.request)
        spec = replace(req.specification)
        if (
            allocation.request != req
            or spec.actor != self.operator
            or spec.ledger_reference != self.budget.ledger_reference
            or allocation.approval.actor != self.operator
            or not spec.approved_at <= allocation.approval.approved_at <= self.budget.clock.now()
        ):
            return blocked(WorkerExecutionReason.APPROVAL_DENIED)
        if (
            self.repository.get_request(reference) != req
            or self.repository.get_allocation(reference) != allocation
        ):
            return blocked(WorkerExecutionReason.IDENTITY_CONFLICT)
        if (
            view.reason == RevisionReason.UNKNOWN_EFFECT
            or self.journal.get_response(allocation.binding.execution_reference) is not None
        ):
            return blocked(WorkerExecutionReason.EXTERNAL_OUTCOME_UNKNOWN)
        current = load(self.opportunities, spec.task.opportunity_reference)
        if view.deliverable is not None:
            return WorkerExecutionOutcome(
                WorkerExecutionStatus.COMPLETED,
                WorkerExecutionReason.NONE,
                current.value,
                None if view.result is None else view.result.result,
            )
        if view.run is not None:
            if (
                current != view.run.started_snapshot
                or current.value.state != OpportunityState.IN_PROGRESS
                or current.value.execution != view.run.worker.plan.execution
                or current.value.qa != req.parent_snapshot.value.qa
                or current.value.task != spec.task
                or current.value.deliverable is not None
            ):
                return blocked(WorkerExecutionReason.STATE_CONFLICT)
            if view.result is not None:
                return self._finish(view)
        elif current != req.parent_snapshot:
            return blocked(WorkerExecutionReason.STALE_REVISION)
        parent = self.repository.parent(req.parent_run.binding.execution_reference)
        if (
            parent is None
            or parent.run != req.parent_run
            or parent.deliverable != req.parent_deliverable
        ):
            return blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        reason = RevisionPreflight(
            self.opportunities,
            self.evaluations,
            self.source,
            self.budget.clock,
            self.operator,
            self.budget.ledger_reference,
        ).check(req, current.value)
        if reason is not None:
            return blocked(reason)
        if load(self.opportunities, current.value.reference) != current:
            return blocked(WorkerExecutionReason.STALE_REVISION)
        if view.run is None:
            ledger = self.budget.ledger.get(self.budget.ledger_reference)
            if ledger is None:
                return blocked(WorkerExecutionReason.NOT_FOUND)
            zero = Money(Decimal(0), ledger.value.policy.monthly_ai_budget.currency)
            decision = self.budget.authorize(
                zero,
                CostContext(
                    allocation.binding.operation_reference,
                    OperationType.TASK_EXECUTION,
                    self.budget.clock.now(),
                    spec.task.reference,
                    spec.task.opportunity_reference,
                ),
            )
            if decision.status != AuthorizationStatus.AUTHORIZED:
                return blocked(
                    WorkerExecutionReason.BUDGET_DENIED
                    if decision.status == AuthorizationStatus.DENIED
                    else WorkerExecutionReason.SPENDING_APPROVAL_REQUIRED
                )
            latest = self.budget.ledger.get(self.budget.ledger_reference)
            if latest is None:
                return blocked(WorkerExecutionReason.NOT_FOUND)
            start = RevisionStart(allocation, current, latest, self.budget.clock.now())
            if not self.repository.start(start):
                return WorkerExecutionOutcome(
                    WorkerExecutionStatus.RECOVERABLE, WorkerExecutionReason.STATE_CONFLICT
                )
            view = self.repository.inspect(reference)
            if view is None or view.run is None:
                return blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        assert view.run is not None
        if load(self.opportunities, current.value.reference) != view.run.started_snapshot:
            return blocked(WorkerExecutionReason.STATE_CONFLICT)
        try:
            result = DataWorker(self.budget, self.journal, llm=None).execute(view.run.worker.plan)
        except (PortError, DomainError, ApplicationError):
            raise
        except Exception:
            return WorkerExecutionOutcome(
                WorkerExecutionStatus.RECOVERABLE, WorkerExecutionReason.WORKER_FAILED
            )
        self.repository.save_result(reference, WorkerResult(view.run.worker, result))
        retained = self.repository.inspect(reference)
        if retained is None:
            return blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        return self._finish(retained)

    def _finish(self, view: RevisionView) -> WorkerExecutionOutcome:
        if view.run is None or view.result is None:
            return blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        expected = view.run.started_snapshot
        if load(self.opportunities, expected.value.reference) != expected:
            return blocked(WorkerExecutionReason.STALE_REVISION)
        cost = view.result.result.cost
        if cost is None or cost.context.occurred_at > self.budget.clock.now():
            return blocked(WorkerExecutionReason.EVIDENCE_INVALID)
        self.budget.record(
            view.run.worker.plan.execution.authorization, cost.actual_cost, cost.context.occurred_at
        )
        self.repository.save_result(view.request.reference, view.result)
        self.repository.finish(RevisionFinish(view.run, view.result, expected))
        return WorkerExecutionOutcome(
            WorkerExecutionStatus.COMPLETED,
            WorkerExecutionReason.NONE,
            load(self.opportunities, expected.value.reference).value,
            view.result.result,
        )


@dataclass(frozen=True, slots=True)
class RecoverDataRevision:
    execution: ExecuteDataRevision

    def execute(self, reference: Reference, *, confirm: bool) -> WorkerExecutionOutcome:
        return self.execution.execute(reference, confirm=confirm)
