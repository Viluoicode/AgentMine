"""Immutable local revision evidence and internal persistence commands; no dispatch."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from agentmine.application.contracts.data import DataResult
from agentmine.application.contracts.opportunities import same_terms
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    WorkerResult,
    WorkerRun,
    WorkSpecification,
)
from agentmine.domain.budget import Budget
from agentmine.domain.finance import CostCategory
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import AuthorizationStatus
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Deliverable, EligibilityStatus, Execution, QAStatus


class RevisionReason(StrEnum):
    IDENTITY_CONFLICT = "identity_conflict"
    STALE_PARENT = "stale_parent"
    INVALID_EVIDENCE = "invalid_evidence"
    TRIGGER_INCOMPLETE = "trigger_incomplete"
    APPROVAL_REQUIRED = "approval_required"
    SUCCESSOR_OWNED = "successor_owned"
    UNKNOWN_EFFECT = "unknown_effect"
    RESULT_MISSING = "result_missing"
    FINISH_PENDING = "finish_pending"
    NONE = "none"


class RevisionError(ValueError):
    def __init__(self, reason: RevisionReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


def require(condition: bool, reason: RevisionReason = RevisionReason.INVALID_EVIDENCE) -> None:
    if not condition:
        raise RevisionError(reason)


class RevisionTrigger(StrEnum):
    QA = "qa"
    OPERATOR = "operator"


@dataclass(frozen=True, slots=True)
class RevisionParent:
    run: WorkerRun
    deliverable: Deliverable
    snapshot: Versioned[Opportunity]
    result: DataResult

    def __post_init__(self) -> None:
        WorkerResult(self.run, self.result)
        require(
            self.deliverable.execution_reference == self.run.binding.execution_reference
            and self.deliverable.reference == self.run.binding.deliverable_reference
            and self.deliverable.content_reference == bundle_content(self.result).reference
        )


@dataclass(frozen=True, slots=True)
class DataRevisionRequest:
    reference: Reference
    parent_run: WorkerRun
    parent_deliverable: Deliverable
    parent_snapshot: Versioned[Opportunity]
    trigger: RevisionTrigger
    trigger_reference: Reference
    specification: WorkSpecification
    reason: str

    def __post_init__(self) -> None:
        require_reference(self.reference, "revision")
        require_reference(self.trigger_reference, "trigger")
        require(isinstance(self.trigger, RevisionTrigger))
        require(
            isinstance(self.reason, str) and bool(self.reason.strip()) and len(self.reason) <= 4000
        )
        spec = replace(self.specification)
        parent = self.parent_run
        op = self.parent_snapshot.value
        require(
            op.state == OpportunityState.IN_PROGRESS
            and op.execution == parent.plan.execution
            and op.task == spec.task == parent.specification.task
            and op.qa is not None
            and op.qa.deliverable == self.parent_deliverable
            and op.qa.status
            == (QAStatus.FAILED if self.trigger == RevisionTrigger.QA else QAStatus.PASSED)
            and op.deliverable is None
            and op.approval is None
            and op.submission is None
            and op.outcome is None
            and op.payment is None
            and self.parent_deliverable.execution_reference == parent.binding.execution_reference
            and self.parent_deliverable.reference == parent.binding.deliverable_reference
            and spec.reference != parent.specification.reference
            and spec.ledger_reference == parent.specification.ledger_reference
            and spec.actor == parent.specification.actor
            and spec.approved_at >= parent.specification.approved_at
            and same_terms(spec.source_context, parent.specification.source_context)
        )
        old = parent.specification.acceptance
        new = spec.acceptance
        require(old is not None and new is not None)
        assert old is not None and new is not None
        require(
            all(item in new.formats for item in old.formats)
            and all(item in new.requirements for item in old.requirements)
        )
        # Only structurally provable non-relaxing validation changes are supported.
        require(
            spec.min_records >= parent.specification.min_records
            and spec.max_records <= parent.specification.max_records
            and spec.unique_by == parent.specification.unique_by
            and all(item in spec.constraints for item in parent.specification.constraints)
        )
        require(all(item in spec.columns for item in parent.specification.columns))
        evidence = spec.execution_evidence
        prior = parent.specification.execution_evidence
        require(evidence is not None and prior is not None)
        assert evidence is not None and prior is not None
        evaluation = evidence.evaluation
        require(
            evaluation.reference != prior.evaluation.reference
            and evaluation.opportunity_reference == op.reference
            and evaluation.eligibility.status == EligibilityStatus.ELIGIBLE
            and evaluation.scoring_assessment.economics.potential_reward == op.potential_reward
            and evaluation.scoring_assessment.economics.inputs.estimated_cost.ai.amount == 0
            and parent.plan.execution.started_at <= evaluation.evaluated_at <= spec.approved_at
            and evidence.eligibility_request.facts.opportunity_reference == op.reference
            and evidence.eligibility_request.facts.task_type == spec.task.task_type
        )


@dataclass(frozen=True, slots=True)
class DataRevisionApproval:
    request_reference: Reference
    actor: Reference
    approved_at: datetime
    confirmed: bool

    def __post_init__(self) -> None:
        require_reference(self.request_reference, "revision")
        require_reference(self.actor, "actor")
        require_aware_timestamp(self.approved_at)
        require(self.confirmed is True, RevisionReason.APPROVAL_REQUIRED)


@dataclass(frozen=True, slots=True)
class RevisionAllocation:
    request: DataRevisionRequest
    approval: DataRevisionApproval
    binding: ExecutionBinding

    def __post_init__(self) -> None:
        req = self.request
        require(
            self.approval.request_reference == req.reference
            and self.approval.actor == req.specification.actor
            and self.approval.approved_at >= req.specification.approved_at
            and self.binding.specification_reference == req.specification.reference
            and self.binding.deliverable_reference == req.parent_deliverable.reference
            and self.binding.execution_reference != req.parent_run.binding.execution_reference
            and self.binding.operation_reference != req.parent_run.binding.operation_reference
        )

    @property
    def reference(self) -> Reference:
        return self.request.reference

    @property
    def version(self) -> int:
        return self.request.parent_deliverable.version + 1


@dataclass(frozen=True, slots=True)
class RevisionRun:
    allocation: RevisionAllocation
    worker: WorkerRun

    def __post_init__(self) -> None:
        require(
            self.worker.binding == self.allocation.binding
            and self.worker.specification == self.allocation.request.specification
        )

    @property
    def started_snapshot(self) -> Versioned[Opportunity]:
        request = self.allocation.request
        evidence = request.specification.execution_evidence
        assert evidence is not None
        updated = request.parent_snapshot.value.begin_rework(
            request.parent_deliverable,
            self.worker.plan.execution,
            evidence.evaluation.eligibility,
            evidence.evaluation.scoring_assessment,
        )
        return Versioned(updated, request.parent_snapshot.revision + 1)


@dataclass(frozen=True, slots=True)
class RevisionStart:
    allocation: RevisionAllocation
    opportunity_snapshot: Versioned[Opportunity]
    ledger_snapshot: Versioned[Budget]
    started_at: datetime

    def __post_init__(self) -> None:
        require_aware_timestamp(self.started_at)
        require(
            self.opportunity_snapshot == self.allocation.request.parent_snapshot
            and self.started_at >= self.allocation.approval.approved_at
        )
        _ = self.opportunity

    @property
    def run(self) -> RevisionRun:
        allocation = self.allocation
        budget = self.ledger_snapshot.value
        auth = next(
            (
                item
                for item in budget.outstanding
                if item.request.context.operation_reference
                == allocation.binding.operation_reference
            ),
            None,
        )
        require(auth is not None)
        assert auth is not None
        request = auth.request
        require(
            request.category == CostCategory.AI
            and request.estimated_cost.amount == 0
            and request.context.human_approval is None
        )
        decision = budget.authorize(
            request.estimated_cost,
            request.category,
            replace(request.context, occurred_at=self.started_at),
        )
        require(
            decision.status == AuthorizationStatus.AUTHORIZED and decision.authorization == auth
        )
        execution = Execution(
            allocation.binding.execution_reference,
            allocation.request.specification.task,
            auth.mode,
            self.started_at,
            auth,
        )
        worker = WorkerRun(
            allocation.binding,
            allocation.request.specification,
            allocation.request.specification.plan(execution),
        )
        return RevisionRun(allocation, worker)

    @property
    def opportunity(self) -> Opportunity:
        req = self.allocation.request
        evidence = req.specification.execution_evidence
        assert evidence is not None
        return self.opportunity_snapshot.value.begin_rework(
            req.parent_deliverable,
            self.run.worker.plan.execution,
            evidence.evaluation.eligibility,
            evidence.evaluation.scoring_assessment,
        )


@dataclass(frozen=True, slots=True)
class RevisionFinish:
    run: RevisionRun
    retained: WorkerResult
    opportunity_snapshot: Versioned[Opportunity]

    def __post_init__(self) -> None:
        op = self.opportunity_snapshot.value
        require(
            self.retained.run == self.run.worker
            and op.state == OpportunityState.IN_PROGRESS
            and op.execution == self.run.worker.plan.execution
            and op.task == self.run.worker.specification.task
            and op.qa == self.run.allocation.request.parent_snapshot.value.qa
            and op.deliverable is None
            and op.approval is None
        )
        _ = self.opportunity

    @property
    def deliverable(self) -> Deliverable:
        allocation = self.run.allocation
        return Deliverable(
            allocation.binding.deliverable_reference,
            allocation.binding.execution_reference,
            allocation.version,
            bundle_content(self.retained.result).reference,
        )

    @property
    def opportunity(self) -> Opportunity:
        return self.opportunity_snapshot.value.finish(self.deliverable)


class RevisionStatus(StrEnum):
    PREPARED = "prepared"
    APPROVED_NOT_STARTED = "approved_not_started"
    IN_PROGRESS = "in_progress"
    RESULT_RETAINED = "result_retained"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class RevisionView:
    request: DataRevisionRequest
    allocation: RevisionAllocation | None
    run: RevisionRun | None
    result: WorkerResult | None
    deliverable: Deliverable | None
    blocking_reason: RevisionReason = RevisionReason.NONE

    @property
    def status(self) -> RevisionStatus:
        if self.deliverable is not None:
            return RevisionStatus.COMPLETED
        if self.result is not None:
            return RevisionStatus.RESULT_RETAINED
        if self.run is not None:
            return RevisionStatus.IN_PROGRESS
        return (
            RevisionStatus.PREPARED
            if self.allocation is None
            else RevisionStatus.APPROVED_NOT_STARTED
        )

    @property
    def reason(self) -> RevisionReason:
        if self.blocking_reason != RevisionReason.NONE:
            return self.blocking_reason
        if self.deliverable is not None:
            return RevisionReason.NONE
        if self.result is not None:
            return RevisionReason.FINISH_PENDING
        return RevisionReason.RESULT_MISSING if self.run is not None else RevisionReason.NONE
