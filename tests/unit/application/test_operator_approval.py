"""One-operator approvals, protected spending and stale evidence, offline."""

from dataclasses import replace
from datetime import timedelta

import pytest
from approval_fakes import MemoryApprovals
from test_use_cases import World, plan, usd, work_request, world

from agentmine.application.approval_guard import ApprovalGuard
from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.records import Versioned
from agentmine.application.errors import ApplicationError, PortError
from agentmine.application.use_cases.execution import RunQA
from agentmine.application.use_cases.operator import (
    DecideOperatorReview,
    GetOperatorReview,
    PrepareOperatorReview,
)
from agentmine.domain.approval import ApprovalAction, ApprovalScope, OperatorDecision
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import CostCategory
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import (
    AuthorizationStatus,
    CostContext,
    OperationType,
    SpendingRequest,
)
from agentmine.domain.values import Reference
from agentmine.domain.work import QAResult, QAStatus

__all__ = ["world"]


def prepare(world: World, approvals: MemoryApprovals) -> PrepareOperatorReview:
    return PrepareOperatorReview(
        world.opportunities, world.executions, world.ledger, approvals, world.clock
    )


def decide(world: World, approvals: MemoryApprovals) -> DecideOperatorReview:
    return DecideOperatorReview(
        world.opportunities,
        world.executions,
        world.ledger,
        approvals,
        world.source,
        world.clock,
        Reference("operator"),
    )


def ready(world: World) -> ApprovalScope:
    plan(world)
    result = world.execute_task().execute(work_request(world))
    assert result.opportunity.deliverable is not None
    deliverable = result.opportunity.deliverable
    RunQA(world.opportunities, world.executions).execute(
        world.reference, QAResult(deliverable, QAStatus.PASSED, "Sources checked")
    )
    return ApprovalScope(
        ApprovalAction.EXTERNAL_SUBMISSION,
        Reference("destination"),
        deliverable.content_reference,
        deliverable,
    )


def test_submission_review_preparation_and_read_are_application_owned(world: World) -> None:
    approvals = MemoryApprovals()
    scope = ready(world)
    command = prepare(world, approvals)
    review = command.for_submission(
        Reference("review"), world.reference, Reference("ledger"), scope.destination
    )
    assert review.scope == scope
    assert (
        command.for_submission(
            Reference("review"), world.reference, Reference("ledger"), scope.destination
        )
        == review
    )
    query = GetOperatorReview(approvals)
    assert query.execute(review.reference).review == review
    assert query.execute(review.reference).decision is None
    with pytest.raises(PortError):
        command.for_submission(
            Reference("review"), world.reference, Reference("ledger"), Reference("changed")
        )
    decision = decide(world, approvals).execute(review.reference, OperatorDecision.APPROVE)
    assert query.execute(review.reference).decision == decision
    assert world.gateway.submits == 0


def test_missing_submission_deliverable_and_review_fail_in_application(world: World) -> None:
    approvals = MemoryApprovals()
    plan(world)
    with pytest.raises(PortError, match="Deliverable required"):
        prepare(world, approvals).for_submission(
            Reference("review"), world.reference, Reference("ledger"), Reference("destination")
        )
    assert not approvals.reviews
    with pytest.raises(PortError, match="Review missing"):
        GetOperatorReview(approvals).execute(Reference("missing"))


@pytest.mark.parametrize("decision", list(OperatorDecision))
def test_decision_audit_and_submission_boundary(world: World, decision: OperatorDecision) -> None:
    approvals = MemoryApprovals()
    scope = ready(world)
    review = prepare(world, approvals).execute(
        Reference("review"), world.reference, Reference("ledger"), scope
    )
    assert review.reward == world.current().potential_reward
    assert review.eligibility == world.current().eligibility
    assert review.score == world.current().score
    assert review.expected_value == world.current().expected_value
    assert review.estimated_cost == usd("20")
    assert review.actual_cost_so_far == (usd("1"),)
    assert review.content and review.qa_result and review.risks
    assert review.submission_destination == Reference("destination")
    with pytest.raises(ApplicationError):
        world.submit_task().execute(world.reference, Reference("submission"))
    command = decide(world, approvals)
    result = command.execute(review.reference, decision, "Operator reviewed evidence")
    assert result.actor == Reference("operator") and result.decided_at == world.clock.now()
    assert result.decision == decision and result.reason == "Operator reviewed evidence"
    assert approvals.get_decision(review.reference) == result
    assert world.gateway.submits == 0
    world.clock.instant += timedelta(seconds=1)
    assert command.execute(review.reference, decision, result.reason) == result
    if decision == OperatorDecision.APPROVE:
        assert world.current().state == OpportunityState.APPROVED_FOR_SUBMISSION
        world.submit_task().execute(world.reference, Reference("submission"))
        assert world.gateway.submits == 1
    elif decision == OperatorDecision.REJECT:
        assert world.current().state == OpportunityState.SKIPPED
    else:
        current = world.current()
        assert (
            current.state == OpportunityState.IN_PROGRESS
            and current.deliverable is None
            and current.approval is None
        )
        assert scope.deliverable is not None
        with pytest.raises(DomainError):
            current.finish(scope.deliverable)
        revised = current.finish(
            replace(scope.deliverable, version=2, content_reference=Reference("changed"))
        )
        assert revised.state == OpportunityState.QA_PENDING
    with pytest.raises(PortError):
        command.execute(
            review.reference,
            OperatorDecision.REJECT
            if decision == OperatorDecision.APPROVE
            else OperatorDecision.APPROVE,
        )


@pytest.mark.parametrize("change", ["content", "costs", "opportunity", "closed", "expired"])
def test_changed_review_cannot_approve(world: World, change: str) -> None:
    approvals = MemoryApprovals()
    scope = ready(world)
    review = prepare(world, approvals).execute(
        Reference("review"), world.reference, Reference("ledger"), scope
    )
    if change == "content":
        assert review.content is not None
        world.executions.contents[review.content.reference] = replace(
            review.content, text="tampered"
        )
    elif change == "costs":
        snapshot = world.ledger.snapshots[Reference("ledger")]
        world.ledger.snapshots[Reference("ledger")] = Versioned(
            snapshot.value, snapshot.revision + 1
        )
    elif change == "opportunity":
        snapshot_op = world.opportunities.snapshots[world.reference]
        world.opportunities.snapshots[world.reference] = Versioned(
            snapshot_op.value, snapshot_op.revision + 1
        )
    elif change == "closed":
        world.source.is_open = False
    else:
        world.clock.instant += timedelta(days=2)
    with pytest.raises((PortError, ApplicationError)):
        decide(world, approvals).execute(review.reference, OperatorDecision.APPROVE)
    assert not approvals.decisions and world.gateway.submits == 0


def test_decision_recovers_failed_opportunity_save(world: World) -> None:
    approvals = MemoryApprovals()
    scope = ready(world)
    review = prepare(world, approvals).execute(
        Reference("review"), world.reference, Reference("ledger"), scope
    )
    world.opportunities.fail_save = True
    command = decide(world, approvals)
    with pytest.raises(PortError):
        command.execute(review.reference, OperatorDecision.APPROVE)
    assert approvals.get_decision(review.reference) is not None
    assert world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW
    world.opportunities.fail_save = False
    command.execute(review.reference, OperatorDecision.APPROVE)
    assert world.current().state == OpportunityState.APPROVED_FOR_SUBMISSION


def spending_scope(world: World) -> ApprovalScope:
    return ApprovalScope(
        ApprovalAction.SPENDING,
        Reference("ledger"),
        Reference("operation"),
        spending=SpendingRequest(
            usd("1"),
            CostCategory.AI,
            CostContext(
                Reference("operation"),
                OperationType.TASK_EXECUTION,
                world.clock.now(),
                Reference("task"),
                world.reference,
            ),
        ),
    )


@pytest.mark.parametrize("decision", list(OperatorDecision))
def test_threshold_requires_recorded_approve(world: World, decision: OperatorDecision) -> None:
    plan(world)
    snapshot = world.ledger.snapshots[Reference("ledger")]
    world.ledger.snapshots[Reference("ledger")] = Versioned(
        snapshot.value.with_policy(
            replace(snapshot.value.policy, human_approval_cost_threshold=usd("0"))
        ),
        snapshot.revision + 1,
    )
    approvals = MemoryApprovals()
    scope = spending_scope(world)
    review = prepare(world, approvals).execute(
        Reference("spend-review"), world.reference, Reference("ledger"), scope
    )
    without = world.execute_task().execute(work_request(world))
    assert (
        without.decision is not None
        and without.decision.status == AuthorizationStatus.REQUIRES_HUMAN_APPROVAL
    )
    # The rejected authorization audit changes the ledger revision: refresh review before decision.
    review = prepare(world, approvals).execute(
        Reference("spend-review-2"), world.reference, Reference("ledger"), scope
    )
    decide(world, approvals).execute(review.reference, decision)
    request = replace(work_request(world), spending_approval=review.reference)
    worker = replace(world.execute_task(), approvals=approvals)
    if decision == OperatorDecision.APPROVE:
        result = worker.execute(request)
        assert result.opportunity.state == OpportunityState.QA_PENDING
        assert len(world.provider.calls) == 1
    else:
        with pytest.raises(PortError):
            worker.execute(request)
        assert not world.provider.calls


@pytest.mark.parametrize(
    "change", ["missing", "amount", "category", "operation", "ledger", "destination"]
)
def test_approval_cannot_be_reused_for_changed_scope(world: World, change: str) -> None:
    plan(world)
    approvals = MemoryApprovals()
    scope = spending_scope(world)
    review = prepare(world, approvals).execute(
        Reference("review"), world.reference, Reference("ledger"), scope
    )
    decide(world, approvals).execute(review.reference, OperatorDecision.APPROVE)
    assert scope.spending is not None
    context = replace(scope.spending.context, human_approval=review.reference)
    manager = BudgetManager(world.ledger, Reference("ledger"), world.clock, approvals)
    if change == "missing":
        context = replace(context, human_approval=Reference("invented"))
    if change == "operation":
        context = replace(context, operation_reference=Reference("another"))
    if change == "ledger":
        manager = replace(manager, ledger_reference=Reference("other"))
        world.ledger.snapshots[Reference("other")] = world.ledger.snapshots[Reference("ledger")]
    if change == "destination":
        with pytest.raises(PortError):
            ApprovalGuard(approvals, world.clock).require(
                review.reference, replace(scope, destination=Reference("other"))
            )
        return
    with pytest.raises(PortError):
        manager.authorize(
            usd("2") if change == "amount" else usd("1"),
            context,
            CostCategory.TOOL if change == "category" else CostCategory.AI,
        )


@pytest.mark.parametrize(
    "action", [ApprovalAction.WALLET_FINANCIAL, ApprovalAction.SENSITIVE_ACCOUNT]
)
def test_sensitive_actions_have_no_implicit_consent(world: World, action: ApprovalAction) -> None:
    plan(world)
    approvals = MemoryApprovals()
    scope = ApprovalScope(
        action, Reference("account-destination"), Reference("exact-action-payload")
    )
    review = prepare(world, approvals).execute(
        Reference("review"), world.reference, Reference("ledger"), scope
    )
    guard = ApprovalGuard(approvals, world.clock)
    with pytest.raises(PortError):
        guard.require(review.reference, scope)
    decide(world, approvals).execute(review.reference, OperatorDecision.APPROVE)
    guard.require(review.reference, scope)
    with pytest.raises(PortError):
        guard.require(
            review.reference, replace(scope, payload_reference=Reference("changed-action"))
        )
    assert world.gateway.submits == 0 and world.provider.calls == []


def test_threshold_change_rechecks_existing_authorization(world: World) -> None:
    plan(world)
    manager = BudgetManager(world.ledger, Reference("ledger"), world.clock)
    scope = spending_scope(world)
    assert scope.spending is not None
    decision = manager.authorize(usd("1"), scope.spending.context)
    assert decision.authorization is not None
    snapshot = world.ledger.snapshots[Reference("ledger")]
    world.ledger.snapshots[Reference("ledger")] = Versioned(
        snapshot.value.with_policy(
            replace(snapshot.value.policy, human_approval_cost_threshold=usd("0"))
        ),
        snapshot.revision + 1,
    )
    with pytest.raises(PortError):
        manager.require_authorized(decision.authorization, usd("1"))
    assert not world.provider.calls


def test_approval_does_not_override_budget_caps(world: World) -> None:
    plan(world)
    approvals = MemoryApprovals()
    scope = spending_scope(world)
    assert scope.spending is not None
    scope = replace(scope, spending=replace(scope.spending, estimated_cost=usd("20")))
    review = prepare(world, approvals).execute(
        Reference("review"), world.reference, Reference("ledger"), scope
    )
    decide(world, approvals).execute(review.reference, OperatorDecision.APPROVE)
    manager = BudgetManager(world.ledger, Reference("ledger"), world.clock, approvals)
    assert scope.spending is not None
    result = manager.authorize(
        usd("20"), replace(scope.spending.context, human_approval=review.reference)
    )
    assert result.status == AuthorizationStatus.DENIED


def test_forged_reference_fails_without_approval_repository(world: World) -> None:
    plan(world)
    with pytest.raises(PortError):
        world.execute_task().execute(
            replace(work_request(world), spending_approval=Reference("invented"))
        )
    assert not world.provider.calls


def test_approval_at_threshold_not_required(world: World) -> None:
    plan(world)
    snapshot = world.ledger.snapshots[Reference("ledger")]
    world.ledger.snapshots[Reference("ledger")] = Versioned(
        snapshot.value.with_policy(
            replace(snapshot.value.policy, human_approval_cost_threshold=usd("1"))
        ),
        snapshot.revision + 1,
    )
    result = world.execute_task().execute(work_request(world))
    assert result.opportunity.state == OpportunityState.QA_PENDING
