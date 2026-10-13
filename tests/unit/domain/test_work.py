from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import CostCategory, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import AuthorizationStatus, CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import (
    Deliverable,
    Eligibility,
    EligibilityStatus,
    Execution,
    HumanApproval,
    Outcome,
    OutcomeStatus,
    QAResult,
    QAStatus,
    Task,
    TaskType,
)


@pytest.mark.parametrize("task_type", list(TaskType))
@pytest.mark.parametrize("mode", [OperatingMode.FULL, OperatingMode.SAVER])
def test_supported_tasks_can_execute(task_type: TaskType, mode: OperatingMode) -> None:
    task = Task(Reference("task"), Reference("opportunity"), task_type, "Work")
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    amount = Money(Decimal(100), "USD")
    decision = Budget(BudgetPolicy(amount, amount, amount, amount), mode).authorize(
        Money(Decimal(1), "USD"),
        CostCategory.AI,
        CostContext(
            Reference("operation"),
            OperationType.TASK_EXECUTION,
            timestamp,
            task.reference,
            task.opportunity_reference,
        ),
    )
    assert decision.authorization is not None
    execution = Execution(Reference("execution"), task, mode, timestamp, decision.authorization)
    assert execution.task == task


@pytest.mark.parametrize("unsupported", ["coding", "trading", "research", ""])
def test_unsupported_or_unparsed_task_types_cannot_execute(unsupported: str) -> None:
    with pytest.raises(DomainError) as error:
        Task(Reference("task"), Reference("opportunity"), cast(TaskType, unsupported), "Work")
    assert error.value.code == ErrorCode.EXECUTION_FORBIDDEN


def test_scout_only_allows_free_execution_and_denies_paid_execution() -> None:
    task = Task(Reference("task"), Reference("opportunity"), TaskType.RESEARCH, "Work")
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    amount = Money(Decimal(100), "USD")
    budget = Budget(BudgetPolicy(amount, amount, amount, amount), OperatingMode.SCOUT_ONLY)
    context = CostContext(
        Reference("operation"),
        OperationType.TASK_EXECUTION,
        timestamp,
        task.reference,
        task.opportunity_reference,
    )
    denied = budget.authorize(Money(Decimal(1), "USD"), CostCategory.AI, context)
    assert denied.status == AuthorizationStatus.DENIED
    free = budget.authorize(Money(Decimal(0), "USD"), CostCategory.TOOL, context)
    assert free.authorization is not None
    Execution(Reference("execution"), task, OperatingMode.SCOUT_ONLY, timestamp, free.authorization)
    with pytest.raises(DomainError):
        Execution(
            Reference("execution"), task, cast(OperatingMode, "full"), timestamp, free.authorization
        )
    with pytest.raises(DomainError):
        Execution(
            Reference("execution"),
            task,
            OperatingMode.SCOUT_ONLY,
            timestamp.replace(tzinfo=None),
            free.authorization,
        )


@pytest.mark.parametrize("version", [0, -1, True, 1.5])
def test_deliverable_versions_are_positive_integers(version: int | float) -> None:
    with pytest.raises(DomainError):
        Deliverable(
            Reference("artifact"), Reference("execution"), cast(int, version), Reference("hash")
        )


def test_required_explanations_and_enum_types() -> None:
    with pytest.raises(DomainError):
        Task(Reference("task"), Reference("opportunity"), TaskType.RESEARCH, " ")
    with pytest.raises(DomainError):
        Eligibility(EligibilityStatus.UNKNOWN, " ")
    with pytest.raises(DomainError):
        Eligibility(cast(EligibilityStatus, "eligible"), "Valid")
    deliverable = Deliverable(Reference("artifact"), Reference("execution"), 1, Reference("hash"))
    with pytest.raises(DomainError):
        QAResult(deliverable, QAStatus.PASSED, " ")
    with pytest.raises(DomainError):
        QAResult(deliverable, cast(QAStatus, "passed"), "Checked")


def test_submission_requires_current_qa_approval_and_target(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    submission = lifecycle[OpportunityState.SUBMITTED].submission
    assert submission is not None
    with pytest.raises(DomainError):
        replace(submission, qa=replace(submission.qa, status=QAStatus.FAILED))
    with pytest.raises(DomainError):
        replace(submission, deliverable=replace(submission.deliverable, version=2))
    with pytest.raises(DomainError):
        replace(
            submission,
            qa=replace(submission.qa, deliverable=replace(submission.deliverable, version=2)),
        )
    with pytest.raises(DomainError):
        replace(submission, target=Reference("other-target"))
    with pytest.raises(DomainError):
        replace(submission, submitted_at=submission.approval.approved_at - timedelta(seconds=1))
    with pytest.raises(DomainError):
        replace(submission, submitted_at=submission.submitted_at.replace(tzinfo=None))
    with pytest.raises(DomainError):
        replace(submission, receipt=cast(Reference, None))


def test_approval_requires_actor_target_and_aware_timestamp(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    approval = lifecycle[OpportunityState.APPROVED_FOR_SUBMISSION].approval
    assert approval is not None
    with pytest.raises(DomainError):
        replace(approval, actor=cast(Reference, None))
    with pytest.raises(DomainError):
        replace(approval, target=cast(Reference, None))
    with pytest.raises(DomainError):
        replace(approval, approved_at=approval.approved_at.replace(tzinfo=None))
    assert isinstance(approval, HumanApproval)


def test_outcome_cannot_turn_acceptance_into_verified_payment() -> None:
    reference = Reference("submission")
    payment = Reward(
        Money(Decimal(10), "USD"), RewardStage.VERIFIED_PAYMENT, Reference("payment"), reference
    )
    with pytest.raises(DomainError):
        Outcome(reference, OutcomeStatus.ACCEPTED, Reference("acceptance"), payment)
    accepted = replace(payment, stage=RewardStage.ACCEPTED)
    with pytest.raises(DomainError):
        Outcome(reference, OutcomeStatus.REJECTED, Reference("rejection"), accepted)
    with pytest.raises(DomainError):
        Outcome(
            Reference("other-submission"), OutcomeStatus.ACCEPTED, Reference("acceptance"), accepted
        )
    with pytest.raises(DomainError):
        Outcome(reference, cast(OutcomeStatus, "accepted"), Reference("acceptance"))


def test_missing_deliverables_and_work_cannot_pass_as_evidence(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    submission = lifecycle[OpportunityState.SUBMITTED].submission
    execution = lifecycle[OpportunityState.IN_PROGRESS].execution
    assert submission is not None and execution is not None
    with pytest.raises(DomainError):
        replace(execution, task=cast(Task, None))
    with pytest.raises(DomainError):
        replace(submission.qa, deliverable=cast(Deliverable, None))
    with pytest.raises(DomainError):
        replace(submission.approval, deliverable=cast(Deliverable, None))
    with pytest.raises(DomainError):
        replace(submission, deliverable=cast(Deliverable, None))
    with pytest.raises(DomainError):
        replace(submission, qa=cast(QAResult, None))
    with pytest.raises(DomainError):
        replace(submission, approval=cast(HumanApproval, None))
