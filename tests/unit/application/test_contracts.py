from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agentmine.application.contracts.ai import (
    AIResponse,
    EvaluationAdvice,
    EvaluationRequest,
    QARequest,
    ReferencedText,
    WorkRequest,
)
from agentmine.application.contracts.opportunities import DiscoveryRequest, OpportunityStatus
from agentmine.application.contracts.records import BudgetCommit, OpportunitySave, Versioned
from agentmine.application.contracts.submission import (
    OutcomeObservation,
    PaymentStatus,
    PaymentVerificationRequest,
    PaymentVerificationResult,
    SubmissionAttemptStatus,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.budget import Budget, BudgetPolicy
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import Cost, CostCategory, ExpectedValue, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.spending import CostContext, CostRecord, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import (
    Deliverable,
    Execution,
    HumanApproval,
    Outcome,
    OutcomeStatus,
    QAResult,
    QAStatus,
    Submission,
    Task,
    TaskType,
)


@pytest.fixture
def at() -> datetime:
    return datetime(2026, 10, 13, tzinfo=UTC)


@pytest.fixture
def budget() -> Budget:
    amount = Money(Decimal("100"), "USD")
    return Budget(BudgetPolicy(amount, amount, amount, amount))


@pytest.fixture
def submission(at: datetime) -> Submission:
    deliverable = Deliverable(Reference("draft"), Reference("execution"), 1, Reference("content"))
    qa = QAResult(deliverable, QAStatus.PASSED, "Reviewed")
    approval = HumanApproval(deliverable, Reference("target"), Reference("human"), at)
    return Submission(
        Reference("submission"),
        deliverable,
        qa,
        approval,
        approval.target,
        Reference("receipt"),
        at,
    )


@pytest.mark.parametrize("revision", [0, -1, True])
def test_conditional_writes_reject_invalid_revisions(revision: int, budget: Budget) -> None:
    with pytest.raises(DomainError):
        Versioned(budget, revision)
    with pytest.raises(DomainError):
        BudgetCommit(Reference("ledger"), budget, revision, None)


def test_budget_audit_cannot_be_saved_with_another_snapshot(budget: Budget, at: datetime) -> None:
    context = CostContext(Reference("operation"), OperationType.SCORING, at)
    decision = budget.authorize(Money(Decimal("1"), "USD"), CostCategory.AI, context)
    with pytest.raises(DomainError):
        BudgetCommit(Reference("ledger"), budget, 1, decision)
    commit = BudgetCommit(Reference("ledger"), decision.budget, 1, decision)
    assert commit.audit_event == decision


def test_discovery_and_refresh_reject_invalid_boundaries(at: datetime) -> None:
    with pytest.raises(DomainError):
        DiscoveryRequest(0)
    with pytest.raises(DomainError):
        OpportunityStatus(
            Reference("opportunity"), Reference("source"), at.replace(tzinfo=None), True, None
        )


def test_ai_evaluation_requires_matching_ai_authorization(budget: Budget, at: datetime) -> None:
    opportunity = Opportunity(
        Reference("opportunity"), "Research", Reward(Money(Decimal(1), "USD"))
    )
    context = CostContext(
        Reference("operation"),
        OperationType.SCORING,
        at,
        opportunity_reference=opportunity.reference,
    )
    decision = budget.authorize(Money(Decimal(1), "USD"), CostCategory.AI, context)
    assert decision.authorization is not None
    request = EvaluationRequest(opportunity, "Research requirements", decision.authorization)
    assert request.authorization == decision.authorization
    other = replace(opportunity, reference=Reference("other"))
    with pytest.raises(DomainError):
        replace(request, opportunity=other)
    with pytest.raises(DomainError):
        replace(
            request,
            authorization=replace(
                decision.authorization,
                request=replace(decision.request, category=CostCategory.TOOL),
            ),
        )
    assert OpportunitySave(opportunity, None).expected_revision is None


def test_ai_actual_cost_is_optional_and_never_inferred_from_estimate(at: datetime) -> None:
    advice = EvaluationAdvice(ExpectedValue(Money(Decimal(1), "USD"), "Estimate"), "Advice", ())
    response = AIResponse(Reference("operation"), advice, None, Reference("evidence"))
    assert response.actual_cost is None
    context = CostContext(Reference("other"), OperationType.SCORING, at)
    measured = CostRecord(
        Cost(context.operation_reference, Money(Decimal(2), "USD"), CostCategory.AI), context, None
    )
    with pytest.raises(DomainError):
        replace(response, actual_cost=measured)


@pytest.mark.parametrize("task_type", [TaskType.RESEARCH, TaskType.DATA_PROCESSING])
def test_supported_work_and_qa_bind_authorization_and_content(
    task_type: TaskType, budget: Budget, at: datetime
) -> None:
    task = Task(Reference("task"), Reference("opportunity"), task_type, "Supported work")
    context = CostContext(
        Reference("work"),
        OperationType.TASK_EXECUTION,
        at,
        task.reference,
        task.opportunity_reference,
    )
    decision = budget.authorize(Money(Decimal(1), "USD"), CostCategory.AI, context)
    assert decision.authorization is not None
    execution = Execution(Reference("execution"), task, decision.mode, at, decision.authorization)
    assert WorkRequest(execution, ()).execution.task.task_type == task_type
    deliverable = Deliverable(Reference("draft"), execution.reference, 1, Reference("content"))
    qa_decision = decision.budget.authorize(
        Money(Decimal(1), "USD"),
        CostCategory.AI,
        replace(context, operation_reference=Reference("qa"), operation=OperationType.QA),
    )
    assert qa_decision.authorization is not None
    request = QARequest(
        execution,
        deliverable,
        ReferencedText(deliverable.content_reference, "Report"),
        "Check sources",
        qa_decision.authorization,
    )
    with pytest.raises(DomainError):
        replace(request, content=ReferencedText(Reference("other"), "Report"))
    with pytest.raises(DomainError):
        replace(request, authorization=decision.authorization)
    with pytest.raises(DomainError):
        replace(request, deliverable=replace(deliverable, execution_reference=Reference("other")))


def test_submission_requires_exact_approved_version_target_and_content(
    submission: Submission,
) -> None:
    request = SubmissionRequest(
        submission.reference,
        submission.deliverable,
        submission.qa,
        submission.approval,
        submission.target,
        ReferencedText(submission.deliverable.content_reference, "Report"),
    )
    for changes in (
        {"target": Reference("other")},
        {"deliverable": replace(submission.deliverable, version=2)},
        {"qa": replace(submission.qa, status=QAStatus.FAILED)},
        {"content": ReferencedText(Reference("other-content"), "Report")},
    ):
        with pytest.raises(DomainError):
            replace(request, **changes)


def test_unknown_submission_cannot_carry_confirmed_receipt(
    submission: Submission, at: datetime
) -> None:
    result = SubmissionResult(
        submission.reference, SubmissionAttemptStatus.UNKNOWN, at, None, "Reconcile before retry"
    )
    assert result.submission is None
    with pytest.raises(DomainError):
        replace(result, submission=submission)
    with pytest.raises(DomainError):
        replace(result, status=SubmissionAttemptStatus.CONFIRMED)
    confirmed = replace(result, status=SubmissionAttemptStatus.CONFIRMED, submission=submission)
    with pytest.raises(DomainError):
        replace(confirmed, reference=Reference("other"))


@pytest.mark.parametrize("stage", [RewardStage.POTENTIAL, RewardStage.ACCEPTED])
def test_potential_and_accepted_rewards_are_not_verified_payment(
    stage: RewardStage, at: datetime
) -> None:
    reference = Reference("submission")
    reward = (
        Reward(Money(Decimal(5), "USD"))
        if stage == RewardStage.POTENTIAL
        else Reward(Money(Decimal(5), "USD"), stage, Reference("acceptance"), reference)
    )
    with pytest.raises(DomainError):
        PaymentVerificationResult(reference, PaymentStatus.VERIFIED, at, reward, "Not payment")


def test_pending_payment_does_not_create_revenue(submission: Submission, at: datetime) -> None:
    result = PaymentVerificationResult(
        submission.reference, PaymentStatus.PENDING, at, None, "Not paid"
    )
    assert result.payment is None
    payment = Reward(
        Money(Decimal(5), "USD"),
        RewardStage.VERIFIED_PAYMENT,
        Reference("payment-evidence"),
        submission.reference,
    )
    verified = replace(result, status=PaymentStatus.VERIFIED, payment=payment)
    with pytest.raises(DomainError):
        replace(verified, status=PaymentStatus.PENDING)
    with pytest.raises(DomainError):
        replace(verified, submission_reference=Reference("other"))


def test_payment_and_outcome_require_matching_accepted_submission(
    submission: Submission, at: datetime
) -> None:
    outcome = Outcome(submission.reference, OutcomeStatus.ACCEPTED, Reference("acceptance"))
    assert PaymentVerificationRequest(submission, outcome).outcome == outcome
    with pytest.raises(DomainError):
        PaymentVerificationRequest(submission, replace(outcome, status=OutcomeStatus.REJECTED))
    with pytest.raises(DomainError):
        OutcomeObservation(Reference("other"), at, outcome)


def test_port_error_retains_business_code_and_operation() -> None:
    error = PortError(PortErrorCode.OUTCOME_UNKNOWN, "submit", "Reconciliation required")
    assert error.code == PortErrorCode.OUTCOME_UNKNOWN
    assert error.operation == "submit"
    assert str(error) == "Reconciliation required"
