from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from agentmine.domain.budget import Budget, BudgetAuthorization, BudgetPolicy, OperatingMode
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import CostCategory, ExpectedValue
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.revalidation import ResumeAssessment
from agentmine.domain.spending import AuthorizationStatus, CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import Eligibility, EligibilityStatus, Execution, TaskStatus


def money(value: int) -> Money:
    return Money(Decimal(value), "USD")


@pytest.fixture
def assessment(lifecycle: dict[OpportunityState, Opportunity]) -> ResumeAssessment:
    waiting = lifecycle[OpportunityState.WAITING_FOR_BUDGET]
    return ResumeAssessment(
        waiting.reference,
        datetime(2026, 10, 14, tzinfo=UTC),
        True,
        datetime(2026, 10, 20, tzinfo=UTC),
        Eligibility(EligibilityStatus.ELIGIBLE, "Fresh requirements checked"),
        ExpectedValue(money(50), "Fresh economics"),
        Decimal(9),
    )


@pytest.fixture
def restored_budget() -> Budget:
    return Budget(BudgetPolicy(money(100), money(20), money(10), money(5)))


def test_denied_task_is_waiting_without_stopping_other_opportunities(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    waiting = lifecycle[OpportunityState.WAITING_FOR_BUDGET]
    assert waiting.task is not None
    assert waiting.task.status == TaskStatus.WAITING_FOR_BUDGET
    assert waiting.waiting_request is not None
    assert waiting.verified_revenue == money(0)
    discovered = lifecycle[OpportunityState.DISCOVERED]
    assert (
        discovered.normalize()
        .check_eligibility()
        .assess_eligibility(Eligibility(EligibilityStatus.ELIGIBLE, "Free deterministic check"))
        .evaluate(ExpectedValue(money(50), "Free estimate"))
        .assign_score(Decimal(1))
        .state
        == OpportunityState.SCORED
    )
    submitted = lifecycle[OpportunityState.SUBMITTED]
    accepted = lifecycle[OpportunityState.ACCEPTED]
    assert accepted.outcome is not None
    assert submitted.record_outcome(accepted.outcome).state == OpportunityState.ACCEPTED


def test_restored_budget_resumes_only_after_fresh_checks_and_new_authorization(
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
    restored_budget: Budget,
) -> None:
    waiting = lifecycle[OpportunityState.WAITING_FOR_BUDGET]
    result = waiting.resume_after_budget(assessment, restored_budget, assessment.refreshed_at)
    resumed = result.opportunity
    assert resumed.state == OpportunityState.PLANNED
    assert resumed.task is not None and resumed.task.status == TaskStatus.READY
    assert resumed.task.deadline == assessment.deadline
    assert resumed.eligibility == assessment.eligibility
    assert resumed.expected_value == assessment.expected_value
    assert resumed.score == Decimal(9)
    assert resumed.waiting_request is None
    assert result.decision is not None and result.decision.authorization is not None
    assert len(result.budget.outstanding) == 1
    execution = Execution(
        Reference("resumed-execution"),
        resumed.task,
        result.decision.mode,
        assessment.refreshed_at,
        result.decision.authorization,
    )
    assert resumed.start(execution).state == OpportunityState.IN_PROGRESS
    assert waiting.task is not None and waiting.task.status == TaskStatus.WAITING_FOR_BUDGET


def test_still_exhausted_stays_waiting_without_new_commitment(
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
) -> None:
    empty = Budget(BudgetPolicy(money(0), money(0), money(10), money(5)))
    waiting = lifecycle[OpportunityState.WAITING_FOR_BUDGET]
    result = waiting.resume_after_budget(assessment, empty, assessment.refreshed_at)
    assert result.opportunity is waiting
    assert result.budget is empty
    assert result.decision is not None and result.decision.status == AuthorizationStatus.DENIED
    assert empty.outstanding == ()


def test_expired_task_while_waiting_never_reserves_spending(
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
    restored_budget: Budget,
) -> None:
    expired = replace(
        assessment,
        deadline=assessment.refreshed_at,
        eligibility=None,
        expected_value=None,
        score=None,
    )
    result = lifecycle[OpportunityState.WAITING_FOR_BUDGET].resume_after_budget(
        expired, restored_budget, assessment.refreshed_at
    )
    assert result.opportunity.state == OpportunityState.SKIPPED
    assert (
        result.opportunity.task is not None and result.opportunity.task.status == TaskStatus.EXPIRED
    )
    assert result.opportunity.skip_reason == "Expired while waiting for budget"
    assert result.decision is None and result.budget.outstanding == ()


def test_closed_or_ineligible_opportunity_cannot_resume(
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
    restored_budget: Budget,
) -> None:
    waiting = lifecycle[OpportunityState.WAITING_FOR_BUDGET]
    closed = waiting.resume_after_budget(
        replace(assessment, is_open=False), restored_budget, assessment.refreshed_at
    )
    assert closed.opportunity.state == OpportunityState.SKIPPED
    assert (
        closed.opportunity.task is not None
        and closed.opportunity.task.status == TaskStatus.CANCELLED
    )
    ineligible = waiting.resume_after_budget(
        replace(
            assessment,
            eligibility=Eligibility(EligibilityStatus.INELIGIBLE, "Requirements changed"),
        ),
        restored_budget,
        assessment.refreshed_at,
    )
    assert ineligible.opportunity.state == OpportunityState.INELIGIBLE
    assert ineligible.decision is None and ineligible.budget.outstanding == ()


@pytest.mark.parametrize("field", ["eligibility", "expected_value", "score"])
def test_missing_checks_cannot_resume(
    field: str,
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
    restored_budget: Budget,
) -> None:
    incomplete = {
        "eligibility": replace(assessment, eligibility=None),
        "expected_value": replace(assessment, expected_value=None),
        "score": replace(assessment, score=None),
    }
    with pytest.raises(DomainError) as error:
        lifecycle[OpportunityState.WAITING_FOR_BUDGET].resume_after_budget(
            incomplete[field], restored_budget, assessment.refreshed_at
        )
    assert error.value.code == ErrorCode.REVALIDATION_REQUIRED
    assert restored_budget.outstanding == ()


def test_stale_wrong_future_or_unknown_assessment_is_rejected(
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
    restored_budget: Budget,
) -> None:
    waiting = lifecycle[OpportunityState.WAITING_FOR_BUDGET]
    for invalid in (
        replace(assessment, refreshed_at=datetime(2026, 10, 12, tzinfo=UTC)),
        replace(assessment, refreshed_at=assessment.refreshed_at + timedelta(seconds=1)),
        replace(assessment, opportunity_reference=Reference("other")),
        replace(assessment, eligibility=Eligibility(EligibilityStatus.UNKNOWN, "Not checked")),
        replace(
            assessment,
            eligibility=Eligibility(EligibilityStatus.REQUIRES_HUMAN_REVIEW, "Review pending"),
        ),
    ):
        with pytest.raises(DomainError):
            waiting.resume_after_budget(invalid, restored_budget, assessment.refreshed_at)
    with pytest.raises(DomainError):
        waiting.resume_after_budget(
            replace(
                assessment, expected_value=ExpectedValue(Money(Decimal(1), "EUR"), "Wrong currency")
            ),
            restored_budget,
            assessment.refreshed_at,
        )


def test_waiting_task_cannot_start_or_bypass_budget_resume(
    lifecycle: dict[OpportunityState, Opportunity],
    restored_budget: Budget,
) -> None:
    waiting = lifecycle[OpportunityState.WAITING_FOR_BUDGET]
    assert waiting.task is not None and waiting.waiting_request is not None
    request = waiting.waiting_request
    decision = restored_budget.authorize(request.estimated_cost, request.category, request.context)
    assert decision.authorization is not None
    with pytest.raises(DomainError):
        Execution(
            Reference("execution"),
            waiting.task,
            decision.mode,
            request.context.occurred_at,
            decision.authorization,
        )
    old_execution = lifecycle[OpportunityState.IN_PROGRESS].execution
    assert old_execution is not None
    with pytest.raises(DomainError):
        waiting.start(old_execution)
    planned_task = lifecycle[OpportunityState.PLANNED].task
    assert planned_task is not None
    with pytest.raises(DomainError) as error:
        waiting.plan(planned_task)
    assert error.value.code == ErrorCode.INVALID_TRANSITION


def test_execution_requires_matching_authorization_and_unexpired_task(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    execution = lifecycle[OpportunityState.IN_PROGRESS].execution
    assert execution is not None
    with pytest.raises(DomainError):
        replace(execution, authorization=cast(BudgetAuthorization, None))
    with pytest.raises(DomainError):
        replace(execution, mode=OperatingMode.SAVER)
    with pytest.raises(DomainError):
        replace(execution, task=replace(execution.task, reference=Reference("other")))
    with pytest.raises(DomainError):
        replace(execution, task=replace(execution.task, deadline=execution.started_at))


def test_approval_request_is_not_budget_wait_and_wrong_scope_cannot_wait(
    lifecycle: dict[OpportunityState, Opportunity],
    restored_budget: Budget,
) -> None:
    planned = lifecycle[OpportunityState.PLANNED]
    assert planned.task is not None
    request_context = CostContext(
        Reference("operation"),
        OperationType.TASK_EXECUTION,
        datetime(2026, 10, 13, tzinfo=UTC),
        planned.task.reference,
        planned.reference,
    )
    approval = restored_budget.authorize(money(6), CostCategory.AI, request_context)
    with pytest.raises(DomainError):
        planned.wait_for_budget(approval)
    empty = Budget(BudgetPolicy(money(0), money(0), money(10), money(5)))
    wrong = empty.authorize(
        money(1), CostCategory.AI, replace(request_context, task_reference=Reference("other"))
    )
    with pytest.raises(DomainError):
        planned.wait_for_budget(wrong)


def test_resume_assessment_validation(assessment: ResumeAssessment) -> None:
    for score in (Decimal(-1), Decimal("100.01"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(DomainError):
            replace(assessment, score=score)
    with pytest.raises(DomainError):
        replace(assessment, refreshed_at=assessment.refreshed_at.replace(tzinfo=None))
    with pytest.raises(DomainError):
        replace(assessment, deadline=datetime(2026, 10, 20))


def test_day_rollover_restores_execution_after_waiting(
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
) -> None:
    policy = BudgetPolicy(money(100), money(5), money(10), money(5))
    yesterday = CostContext(
        Reference("previous-operation"),
        OperationType.TASK_EXECUTION,
        datetime(2026, 10, 13, tzinfo=UTC),
        Reference("other-task"),
        Reference("other-opportunity"),
    )
    budget = Budget(policy).authorize(money(5), CostCategory.AI, yesterday).budget
    budget = budget.record(money(5), CostCategory.AI, yesterday).budget
    assert budget.operating_mode(yesterday.occurred_at) == OperatingMode.SCOUT_ONLY
    result = lifecycle[OpportunityState.WAITING_FOR_BUDGET].resume_after_budget(
        assessment, budget, assessment.refreshed_at
    )
    assert result.opportunity.state == OpportunityState.PLANNED
    assert result.decision is not None and result.decision.status == AuthorizationStatus.AUTHORIZED
    assert result.budget.records == budget.records


def test_new_human_threshold_requires_approval_before_resuming(
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
    restored_budget: Budget,
) -> None:
    stricter = restored_budget.with_policy(
        replace(restored_budget.policy, human_approval_cost_threshold=money(0))
    )
    waiting = lifecycle[OpportunityState.WAITING_FOR_BUDGET]
    result = waiting.resume_after_budget(assessment, stricter, assessment.refreshed_at)
    assert result.opportunity is waiting
    assert (
        result.decision is not None
        and result.decision.status == AuthorizationStatus.REQUIRES_HUMAN_APPROVAL
    )
    approved = waiting.resume_after_budget(
        replace(assessment, human_approval=Reference("spend-approval")),
        stricter,
        assessment.refreshed_at,
    )
    assert approved.opportunity.state == OpportunityState.PLANNED


@pytest.mark.parametrize(
    ("phase", "operation"),
    [
        (OpportunityState.IN_PROGRESS, OperationType.TASK_EXECUTION),
        (OpportunityState.QA_PENDING, OperationType.QA),
    ],
)
def test_paid_execution_or_qa_step_waits_and_restores_its_phase(
    phase: OpportunityState,
    operation: OperationType,
    lifecycle: dict[OpportunityState, Opportunity],
    assessment: ResumeAssessment,
    restored_budget: Budget,
) -> None:
    current = lifecycle[phase]
    assert current.task is not None
    empty = Budget(BudgetPolicy(money(0), money(0), money(10), money(5)))
    context = CostContext(
        Reference("waiting-step"),
        operation,
        datetime(2026, 10, 13, tzinfo=UTC),
        current.task.reference,
        current.reference,
    )
    waiting = current.wait_for_budget(empty.authorize(money(1), CostCategory.AI, context))
    assert waiting.task is not None and waiting.task.status == TaskStatus.WAITING_FOR_BUDGET
    assert waiting.execution == current.execution and waiting.deliverable == current.deliverable
    deliverable = lifecycle[OpportunityState.QA_PENDING].deliverable
    qa = lifecycle[OpportunityState.READY_FOR_HUMAN_REVIEW].qa
    assert deliverable is not None and qa is not None
    with pytest.raises(DomainError):
        waiting.finish(deliverable)
    with pytest.raises(DomainError):
        waiting.review_qa(qa)
    result = waiting.resume_after_budget(assessment, restored_budget, assessment.refreshed_at)
    assert result.opportunity.state == phase
    assert result.opportunity.execution == current.execution
    assert result.opportunity.deliverable == current.deliverable
    assert result.opportunity.waiting_state is None
    assert result.decision is not None and result.decision.status == AuthorizationStatus.AUTHORIZED


def test_manually_skipped_waiting_task_is_cancelled(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    skipped = lifecycle[OpportunityState.WAITING_FOR_BUDGET].skip("Human cancelled")
    assert skipped.task is not None and skipped.task.status == TaskStatus.CANCELLED
    assert skipped.waiting_request is None and skipped.waiting_state is None
