from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agentmine.domain.budget import Budget, BudgetPolicy
from agentmine.domain.finance import CostCategory, ExpectedValue, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import CostContext, OperationType
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
    Submission,
    Task,
    TaskType,
)


@pytest.fixture
def lifecycle() -> dict[OpportunityState, Opportunity]:
    """Build real public-action snapshots, including all terminal branches."""
    snapshots: dict[OpportunityState, Opportunity] = {}

    def remember(opportunity: Opportunity) -> Opportunity:
        snapshots[opportunity.state] = opportunity
        return opportunity

    reward = Reward(Money(Decimal("100"), "USD"))
    opportunity = remember(Opportunity(Reference("opportunity-1"), "Research", reward))
    remember(opportunity.skip("Outside current budget"))
    opportunity = remember(opportunity.normalize())
    opportunity = remember(opportunity.check_eligibility())
    remember(opportunity.assess_eligibility(Eligibility(EligibilityStatus.INELIGIBLE, "Region")))
    opportunity = remember(
        opportunity.assess_eligibility(
            Eligibility(EligibilityStatus.ELIGIBLE, "Meets requirements")
        )
    )
    opportunity = remember(
        opportunity.evaluate(ExpectedValue(Money(Decimal("60"), "USD"), "Supplied estimate"))
    )
    opportunity = remember(opportunity.assign_score(Decimal("8")))
    task = Task(Reference("task-1"), opportunity.reference, TaskType.RESEARCH, "Analyze sources")
    opportunity = remember(opportunity.plan(task))
    timestamp = datetime(2026, 10, 13, tzinfo=UTC)
    policy = BudgetPolicy(
        Money(Decimal(1000), "USD"),
        Money(Decimal(100), "USD"),
        Money(Decimal(100), "USD"),
        Money(Decimal(100), "USD"),
    )
    context = CostContext(
        Reference("operation-1"),
        OperationType.TASK_EXECUTION,
        timestamp,
        task.reference,
        opportunity.reference,
    )
    exhausted = Budget(
        BudgetPolicy(
            Money(Decimal(0), "USD"),
            Money(Decimal(0), "USD"),
            policy.max_cost_per_task,
            policy.human_approval_cost_threshold,
        )
    )
    remember(
        opportunity.wait_for_budget(
            exhausted.authorize(Money(Decimal(1), "USD"), CostCategory.AI, context)
        )
    )
    decision = Budget(policy).authorize(Money(Decimal(1), "USD"), CostCategory.AI, context)
    assert decision.authorization is not None
    execution = Execution(
        Reference("execution-1"), task, decision.mode, timestamp, decision.authorization
    )
    opportunity = remember(opportunity.start(execution))
    deliverable = Deliverable(Reference("artifact-1"), execution.reference, 1, Reference("hash-1"))
    opportunity = remember(opportunity.finish(deliverable))
    qa = QAResult(deliverable, QAStatus.PASSED, "Sources and format checked")
    opportunity = remember(opportunity.review_qa(qa))
    approval = HumanApproval(deliverable, Reference("target-1"), Reference("human-1"), timestamp)
    opportunity = remember(opportunity.approve(approval))
    submission = Submission(
        Reference("submission-1"),
        deliverable,
        qa,
        approval,
        approval.target,
        Reference("receipt-1"),
        timestamp,
    )
    opportunity = remember(opportunity.submit(submission))
    remember(
        opportunity.record_outcome(
            Outcome(submission.reference, OutcomeStatus.REJECTED, Reference("rejection-1"))
        )
    )
    accepted_reward = Reward(
        Money(Decimal("90"), "USD"),
        RewardStage.ACCEPTED,
        Reference("acceptance-1"),
        submission.reference,
    )
    opportunity = remember(
        opportunity.record_outcome(
            Outcome(
                submission.reference,
                OutcomeStatus.ACCEPTED,
                Reference("acceptance-1"),
                accepted_reward,
            )
        )
    )
    payment = Reward(
        Money(Decimal("85"), "USD"),
        RewardStage.VERIFIED_PAYMENT,
        Reference("payment-1"),
        submission.reference,
    )
    remember(opportunity.verify_payment(payment))
    return snapshots
