"""Shared integration fixtures built through public domain actions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fakes import FakeEvaluations, FakeExecutions, FakeLedger, FakeOpportunities, FakeSubmissions

from agentmine.application.contracts.records import BudgetCommit
from agentmine.application.ports.repositories import (
    CostLedgerRepository,
    EvaluationRepository,
    ExecutionRepository,
    OpportunityRepository,
    SubmissionRepository,
)
from agentmine.bootstrap.local import open_local_repositories
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


def usd(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


def instant() -> datetime:
    return datetime(2026, 10, 13, tzinfo=UTC)


def budget() -> Budget:
    return Budget(BudgetPolicy(usd("100"), usd("100"), usd("10"), usd("10")))


def snapshots(identifier: str = "op", score: str = "75") -> dict[OpportunityState, Opportunity]:
    result: dict[OpportunityState, Opportunity] = {}

    def remember(value: Opportunity) -> Opportunity:
        result[value.state] = value
        return value

    op = remember(Opportunity(Reference(identifier), "Research", Reward(usd("100"))))
    remember(op.skip("Outside scope"))
    op = remember(op.normalize())
    op = remember(op.check_eligibility())
    remember(op.assess_eligibility(Eligibility(EligibilityStatus.INELIGIBLE, "Country")))
    op = remember(op.assess_eligibility(Eligibility(EligibilityStatus.ELIGIBLE, "Checks passed")))
    op = remember(op.evaluate(ExpectedValue(usd("60"), "Estimate")))
    op = remember(op.assign_score(Decimal(score)))
    task = Task(
        Reference(identifier + ":task"),
        op.reference,
        TaskType.RESEARCH,
        "Research",
        instant() + timedelta(days=1),
    )
    op = remember(op.plan(task))
    context = CostContext(
        Reference(identifier + ":operation"),
        OperationType.TASK_EXECUTION,
        instant(),
        task.reference,
        op.reference,
    )
    empty = Budget(BudgetPolicy(usd("0"), usd("0"), usd("10"), usd("10")))
    remember(op.wait_for_budget(empty.authorize(usd("1"), CostCategory.AI, context)))
    decision = budget().authorize(usd("1"), CostCategory.AI, context)
    assert decision.authorization is not None
    execution = Execution(
        Reference(identifier + ":exec"), task, decision.mode, instant(), decision.authorization
    )
    op = remember(op.start(execution))
    deliverable = Deliverable(
        Reference(identifier + ":deliverable"), execution.reference, 1, Reference("content")
    )
    op = remember(op.finish(deliverable))
    qa = QAResult(deliverable, QAStatus.PASSED, "Checked")
    op = remember(op.review_qa(qa))
    approval = HumanApproval(deliverable, Reference("target"), Reference("human"), instant())
    op = remember(op.approve(approval))
    sub = Submission(
        Reference(identifier + ":sub"),
        deliverable,
        qa,
        approval,
        approval.target,
        Reference("receipt"),
        instant(),
    )
    op = remember(op.submit(sub))
    remember(
        op.record_outcome(Outcome(sub.reference, OutcomeStatus.REJECTED, Reference("rejected")))
    )
    op = remember(
        op.record_outcome(
            Outcome(
                sub.reference,
                OutcomeStatus.ACCEPTED,
                Reference("accepted"),
                Reward(usd("90"), RewardStage.ACCEPTED, Reference("accepted"), sub.reference),
            )
        )
    )
    remember(
        op.verify_payment(
            Reward(usd("85"), RewardStage.VERIFIED_PAYMENT, Reference("payment"), sub.reference)
        )
    )
    return result


@dataclass(frozen=True)
class RepositoryPorts:
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    executions: ExecutionRepository
    submissions: SubmissionRepository
    ledger: CostLedgerRepository


def repositories(backend: str, path: Path) -> RepositoryPorts:
    if backend == "sqlite":
        local = open_local_repositories(path)
        return RepositoryPorts(
            local.opportunities,
            local.evaluations,
            local.executions,
            local.submissions,
            local.ledger,
        )
    return RepositoryPorts(
        FakeOpportunities(), FakeEvaluations(), FakeExecutions(), FakeSubmissions(), FakeLedger({})
    )


def initialize(repos: RepositoryPorts) -> None:
    repos.ledger.commit(BudgetCommit(Reference("ledger"), budget(), None, None))
