from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fakes import (
    FakeClock,
    FakeEvaluations,
    FakeExecutions,
    FakeGateway,
    FakeLedger,
    FakeOpportunities,
    FakeProvider,
    FakeSource,
    FakeSubmissions,
    FakeVerifier,
    eligibility_request,
)

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.opportunities import DiscoveryRequest, OpportunityObservation
from agentmine.application.contracts.records import OpportunitySave, Versioned
from agentmine.application.contracts.submission import PaymentStatus, SubmissionAttemptStatus
from agentmine.application.contracts.workflow import (
    ExecuteTaskRequest,
    PlanTaskRequest,
    ScoreRequest,
)
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.use_cases.approval import ApproveSubmission, RequestHumanApproval
from agentmine.application.use_cases.execution import ExecuteTask, RunQA
from agentmine.application.use_cases.planning import (
    CheckEligibility,
    DiscoverOpportunities,
    EvaluateOpportunity,
    NormalizeOpportunity,
    PlanTask,
    ScoreOpportunity,
)
from agentmine.application.use_cases.settlement import SubmitTask, TrackOutcome, VerifyPayment
from agentmine.domain.budget import Budget, BudgetPolicy, CostRecording
from agentmine.domain.eligibility import EligibilityPolicy, Requirement
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import ExpectedValue, Reward
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import AuthorizationStatus, RecordingIssue
from agentmine.domain.values import Reference
from agentmine.domain.work import (
    HumanApproval,
    OutcomeStatus,
    QAResult,
    QAStatus,
    TaskStatus,
    TaskType,
)


def usd(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


@dataclass
class World:
    clock: FakeClock
    source: FakeSource
    opportunities: FakeOpportunities
    evaluations: FakeEvaluations
    executions: FakeExecutions
    ledger: FakeLedger
    provider: FakeProvider
    submissions: FakeSubmissions
    gateway: FakeGateway
    verifier: FakeVerifier
    reference: Reference

    def execute_task(self) -> ExecuteTask:
        return ExecuteTask(
            self.opportunities, self.executions, self.ledger, self.provider, self.source, self.clock
        )

    def submit_task(self) -> SubmitTask:
        return SubmitTask(
            self.opportunities,
            self.executions,
            self.submissions,
            self.gateway,
            self.source,
            self.clock,
        )

    def current(self) -> Opportunity:
        result = self.opportunities.get(self.reference)
        assert result is not None
        return result.value


@pytest.fixture
def world() -> World:
    clock = FakeClock(datetime(2026, 10, 13, tzinfo=UTC))
    opportunity = Opportunity(Reference("opportunity"), "Research digital data", Reward(usd("100")))
    observation = OpportunityObservation(
        opportunity,
        Reference("source-item"),
        "Research requirements",
        clock.now(),
        True,
        clock.now() + timedelta(days=1),
    )
    policy = BudgetPolicy(usd("100"), usd("100"), usd("10"), usd("10"))
    return World(
        clock,
        FakeSource(clock, (observation,), deadline=observation.deadline),
        FakeOpportunities(),
        FakeEvaluations(),
        FakeExecutions(),
        FakeLedger({Reference("ledger"): Versioned(Budget(policy), 1)}),
        FakeProvider(actual_cost=usd("1")),
        FakeSubmissions(),
        FakeGateway(clock),
        FakeVerifier(clock, usd("85")),
        opportunity.reference,
    )


def scored(world: World) -> Opportunity:
    DiscoverOpportunities(world.source, world.opportunities, world.clock).execute(
        DiscoveryRequest(10)
    )
    NormalizeOpportunity(world.opportunities).execute(world.reference)
    CheckEligibility(
        world.opportunities,
        world.source,
        world.clock,
        EligibilityEngine(EligibilityPolicy(timedelta(hours=1))),
    ).execute(eligibility_request(world.reference))
    EvaluateOpportunity(world.opportunities, world.source, world.clock).execute(
        world.reference, ExpectedValue(usd("60"), "Caller-supplied economic assessment")
    )
    return ScoreOpportunity(
        world.opportunities, world.evaluations, world.source, world.clock
    ).execute(
        ScoreRequest(
            world.reference,
            Reference("evaluation"),
            Decimal("8"),
            (Reference("assessment-evidence"),),
        )
    )


def plan(world: World, task_type: TaskType = TaskType.RESEARCH) -> Opportunity:
    scored(world)
    return PlanTask(world.opportunities, world.source, world.clock).execute(
        PlanTaskRequest(world.reference, Reference("task"), task_type, "Research/Data work")
    )


def work_request(world: World) -> ExecuteTaskRequest:
    return ExecuteTaskRequest(
        world.reference,
        Reference("ledger"),
        Reference("operation"),
        Reference("execution"),
        Reference("deliverable"),
        1,
        usd("1"),
    )


def approved(world: World) -> Opportunity:
    plan(world)
    result = world.execute_task().execute(work_request(world))
    assert result.opportunity.deliverable is not None
    RunQA(world.opportunities, world.executions).execute(
        world.reference,
        QAResult(result.opportunity.deliverable, QAStatus.PASSED, "Deterministic checks passed"),
    )
    review = RequestHumanApproval(world.opportunities, world.executions, world.clock).execute(
        world.reference
    )
    approval = HumanApproval(
        review.deliverable, Reference("target"), Reference("human"), world.clock.now()
    )
    return ApproveSubmission(world.opportunities, world.source, world.clock).execute(
        world.reference, approval
    )


@pytest.mark.parametrize("task_type", [TaskType.RESEARCH, TaskType.DATA_PROCESSING])
def test_discover_normalize_eligible_evaluate_score_plan(world: World, task_type: TaskType) -> None:
    opportunity = plan(world, task_type)
    assert opportunity.history == (
        OpportunityState.DISCOVERED,
        OpportunityState.NORMALIZED,
        OpportunityState.ELIGIBILITY_CHECK,
        OpportunityState.ELIGIBLE,
        OpportunityState.EVALUATED,
        OpportunityState.SCORED,
        OpportunityState.PLANNED,
    )
    assert opportunity.task is not None and opportunity.task.task_type == task_type
    assert opportunity.task.deadline == world.source.deadline
    assert len(world.evaluations.for_opportunity(world.reference)) == 1
    assert world.provider.calls == []
    assert world.ledger.audits == []  # Free path is independent of AI budget.


def test_all_thirteen_use_cases_with_fakes_and_only_payment_creates_revenue(world: World) -> None:
    assert approved(world).state == OpportunityState.APPROVED_FOR_SUBMISSION
    result = world.submit_task().execute(world.reference, Reference("submission"))
    assert result.status == SubmissionAttemptStatus.CONFIRMED
    outcome = TrackOutcome(
        world.opportunities, world.submissions, world.gateway, world.clock
    ).execute(world.reference)
    assert outcome.state == OpportunityState.ACCEPTED
    assert outcome.verified_revenue == usd("0")
    verifier = VerifyPayment(world.opportunities, world.verifier, world.clock)
    assert verifier.execute(world.reference).state == OpportunityState.ACCEPTED
    world.verifier.status = PaymentStatus.VERIFIED
    paid = verifier.execute(world.reference)
    assert paid.state == OpportunityState.PAID and paid.verified_revenue == usd("85")
    assert verifier.execute(world.reference) == paid
    assert world.verifier.calls == 2
    assert len(world.provider.calls) == 1


def test_ineligible_cannot_be_evaluated_or_planned(world: World) -> None:
    DiscoverOpportunities(world.source, world.opportunities, world.clock).execute(
        DiscoveryRequest(1)
    )
    NormalizeOpportunity(world.opportunities).execute(world.reference)
    request = eligibility_request(world.reference)
    result = CheckEligibility(
        world.opportunities,
        world.source,
        world.clock,
        EligibilityEngine(EligibilityPolicy(timedelta(hours=1))),
    ).execute(
        replace(request, facts=replace(request.facts, physical_presence=Requirement.REQUIRED))
    )
    assert result.state == OpportunityState.INELIGIBLE
    with pytest.raises(DomainError):
        EvaluateOpportunity(world.opportunities, world.source, world.clock).execute(
            world.reference, ExpectedValue(usd("60"), "Estimate")
        )
    assert world.current().state == OpportunityState.INELIGIBLE


def test_budget_denied_waits_without_calling_provider_and_free_work_continues(world: World) -> None:
    snapshot = world.ledger.snapshots[Reference("ledger")]
    world.ledger.snapshots[Reference("ledger")] = Versioned(
        snapshot.value.with_policy(
            replace(snapshot.value.policy, monthly_ai_budget=usd("0"), daily_ai_budget=usd("0"))
        ),
        snapshot.revision,
    )
    plan(world)  # Exhaustion does not stop discovery-to-plan.
    result = world.execute_task().execute(work_request(world))
    assert result.decision is not None and result.decision.status == AuthorizationStatus.DENIED
    assert result.opportunity.state == OpportunityState.WAITING_FOR_BUDGET
    assert (
        result.opportunity.task is not None
        and result.opportunity.task.status == TaskStatus.WAITING_FOR_BUDGET
    )
    assert world.provider.calls == []
    assert len(world.ledger.audits) == 1


def test_unsupported_task_never_enters_execution(world: World) -> None:
    scored(world)
    with pytest.raises(ApplicationError) as caught:
        PlanTask(world.opportunities, world.source, world.clock).execute(
            PlanTaskRequest(world.reference, Reference("task"), "coding", "Write code")
        )
    assert caught.value.code == ApplicationErrorCode.UNSUPPORTED_TASK
    assert world.current().state == OpportunityState.SCORED
    assert world.provider.calls == []


def test_expired_opportunity_cannot_be_planned(world: World) -> None:
    scored(world)
    world.source.deadline = world.clock.now()
    with pytest.raises(ApplicationError) as caught:
        PlanTask(world.opportunities, world.source, world.clock).execute(
            PlanTaskRequest(world.reference, Reference("task"), TaskType.RESEARCH, "Research")
        )
    assert caught.value.code == ApplicationErrorCode.EXPIRED
    assert world.current().state == OpportunityState.SCORED


def test_expired_task_has_no_budget_reservation_or_provider_call(world: World) -> None:
    plan(world)
    world.clock.instant += timedelta(days=2)
    with pytest.raises(ApplicationError) as caught:
        world.execute_task().execute(work_request(world))
    assert caught.value.code == ApplicationErrorCode.EXPIRED
    assert world.provider.calls == [] and world.ledger.audits == []


def test_closed_opportunity_cannot_execute(world: World) -> None:
    plan(world)
    world.source.is_open = False
    with pytest.raises(ApplicationError) as caught:
        world.execute_task().execute(work_request(world))
    assert caught.value.code == ApplicationErrorCode.CLOSED
    assert world.provider.calls == []


def test_budget_conflict_prevents_paid_dispatch(world: World) -> None:
    plan(world)
    world.ledger.fail_commit = True
    with pytest.raises(PortError) as caught:
        world.execute_task().execute(work_request(world))
    assert caught.value.code == PortErrorCode.CONFLICT
    assert world.current().state == OpportunityState.PLANNED
    assert world.provider.calls == []


def test_opportunity_conflict_prevents_paid_dispatch_but_retains_reservation(world: World) -> None:
    plan(world)
    world.opportunities.fail_save = True
    with pytest.raises(PortError):
        world.execute_task().execute(work_request(world))
    assert world.provider.calls == []
    assert len(world.ledger.snapshots[Reference("ledger")].value.outstanding) == 1


def test_execution_timeout_cannot_be_blindly_retried(world: World) -> None:
    plan(world)
    world.provider.fail = True
    with pytest.raises(PortError):
        world.execute_task().execute(work_request(world))
    assert world.current().state == OpportunityState.IN_PROGRESS
    with pytest.raises(PortError) as caught:
        world.execute_task().execute(work_request(world))
    assert caught.value.code == PortErrorCode.OUTCOME_UNKNOWN
    assert len(world.provider.calls) == 1
    assert len(world.ledger.snapshots[Reference("ledger")].value.outstanding) == 1


def test_execution_retry_is_idempotent_and_request_reuse_conflicts(world: World) -> None:
    plan(world)
    request = work_request(world)
    result = world.execute_task().execute(request)
    assert world.execute_task().execute(request).opportunity == result.opportunity
    assert len(world.provider.calls) == 1
    with pytest.raises(PortError):
        world.execute_task().execute(replace(request, estimated_cost=usd("2")))


def test_actual_cost_over_estimate_is_recorded_with_audit_issue(world: World) -> None:
    plan(world)
    world.provider.actual_cost = usd("2")
    world.execute_task().execute(work_request(world))
    audit = world.ledger.audits[-1].audit_event
    assert isinstance(audit, CostRecording)
    assert audit.record.actual_cost == usd("2")
    assert audit.record.estimated_cost == usd("1")
    assert RecordingIssue.ESTIMATE_EXCEEDED in audit.issues


def test_unknown_actual_cost_retains_commitment(world: World) -> None:
    plan(world)
    world.provider.actual_cost = None
    world.execute_task().execute(work_request(world))
    budget = world.ledger.snapshots[Reference("ledger")].value
    assert len(budget.outstanding) == 1 and budget.records == ()


def test_failed_qa_cannot_request_approval_or_submit(world: World) -> None:
    plan(world)
    result = world.execute_task().execute(work_request(world))
    assert result.opportunity.deliverable is not None
    failed = RunQA(world.opportunities, world.executions).execute(
        world.reference,
        QAResult(result.opportunity.deliverable, QAStatus.FAILED, "Missing sources"),
    )
    assert failed.state == OpportunityState.IN_PROGRESS
    with pytest.raises(ApplicationError):
        RequestHumanApproval(world.opportunities, world.executions, world.clock).execute(
            world.reference
        )
    with pytest.raises(ApplicationError):
        world.submit_task().execute(world.reference, Reference("submission"))
    assert world.gateway.submits == 0


def test_unknown_submission_reconciles_without_resubmission(world: World) -> None:
    approved(world)
    world.gateway.status = SubmissionAttemptStatus.UNKNOWN
    assert world.submit_task().execute(world.reference, Reference("submission")).submission is None
    assert world.current().state == OpportunityState.APPROVED_FOR_SUBMISSION
    world.gateway.status = SubmissionAttemptStatus.CONFIRMED
    assert (
        world.submit_task().execute(world.reference, Reference("submission")).submission is not None
    )
    assert world.gateway.submits == 1 and world.gateway.reconciles == 1
    world.submit_task().execute(world.reference, Reference("submission"))
    assert world.gateway.submits == 1 and world.gateway.reconciles == 1


def test_changed_content_is_rejected_before_submission(world: World) -> None:
    opportunity = approved(world)
    assert opportunity.deliverable is not None
    reference = opportunity.deliverable.content_reference
    world.executions.contents[reference] = ReferencedText(reference, "Unapproved modified bytes")
    with pytest.raises(PortError) as caught:
        world.submit_task().execute(world.reference, Reference("submission"))
    assert caught.value.code == PortErrorCode.INVALID_RESPONSE
    assert world.gateway.submits == 0 and world.submissions.requests == {}


def test_outcome_tracking_continues_in_scout_mode_and_unknown_outcome_is_not_rejection(
    world: World,
) -> None:
    approved(world)
    world.submit_task().execute(world.reference, Reference("submission"))
    snapshot = world.ledger.snapshots[Reference("ledger")]
    world.ledger.snapshots[Reference("ledger")] = Versioned(
        snapshot.value.with_policy(
            replace(snapshot.value.policy, monthly_ai_budget=usd("0"), daily_ai_budget=usd("0"))
        ),
        snapshot.revision,
    )
    tracker = TrackOutcome(world.opportunities, world.submissions, world.gateway, world.clock)
    world.gateway.outcome_status = None
    assert tracker.execute(world.reference).state == OpportunityState.SUBMITTED
    world.gateway.outcome_status = OutcomeStatus.REJECTED
    assert tracker.execute(world.reference).state == OpportunityState.REJECTED
    with pytest.raises(ApplicationError):
        VerifyPayment(world.opportunities, world.verifier, world.clock).execute(world.reference)
    assert world.verifier.calls == 0


def test_rediscovery_does_not_reset_lifecycle_or_duplicate_assessment(world: World) -> None:
    plan(world)
    before = world.current()
    DiscoverOpportunities(world.source, world.opportunities, world.clock).execute(
        DiscoveryRequest(1)
    )
    assert world.current() == before
    assert len(world.evaluations.records) == 1


def test_missing_opportunity_is_structured_error(world: World) -> None:
    with pytest.raises(ApplicationError) as caught:
        NormalizeOpportunity(world.opportunities).execute(Reference("missing"))
    assert caught.value.code == ApplicationErrorCode.NOT_FOUND


def test_repository_compare_and_swap_rejects_stale_writer(world: World) -> None:
    plan(world)
    old = world.opportunities.get(world.reference)
    assert old is not None
    world.opportunities.save(OpportunitySave(old.value, old.revision))
    with pytest.raises(PortError):
        world.opportunities.save(OpportunitySave(old.value, old.revision))


def test_pre_dispatch_conflict_can_retry_without_duplicate_reservation(world: World) -> None:
    plan(world)
    world.opportunities.fail_save = True
    with pytest.raises(PortError):
        world.execute_task().execute(work_request(world))
    world.opportunities.fail_save = False
    world.clock.instant += timedelta(seconds=1)
    result = world.execute_task().execute(work_request(world))
    assert result.opportunity.state == OpportunityState.QA_PENDING
    assert len(world.provider.calls) == 1
    assert len(world.ledger.snapshots[Reference("ledger")].value.authorizations) == 1


def test_cached_response_can_recover_failed_cost_commit_without_redispatch(world: World) -> None:
    plan(world)

    def fail_cost_commit() -> None:
        world.ledger.fail_commit = True

    world.provider.on_response = fail_cost_commit
    with pytest.raises(PortError):
        world.execute_task().execute(work_request(world))
    assert world.current().state == OpportunityState.IN_PROGRESS
    assert world.executions.get_work_response(Reference("execution")) is not None
    world.ledger.fail_commit = False
    recovered = world.execute_task().execute(work_request(world))
    assert recovered.opportunity.state == OpportunityState.QA_PENDING
    assert len(world.provider.calls) == 1
    assert len(world.ledger.snapshots[Reference("ledger")].value.records) == 1


def test_spending_approval_threshold_does_not_dispatch_or_wait_for_budget(world: World) -> None:
    plan(world)
    snapshot = world.ledger.snapshots[Reference("ledger")]
    world.ledger.snapshots[Reference("ledger")] = Versioned(
        snapshot.value.with_policy(
            replace(snapshot.value.policy, human_approval_cost_threshold=usd("0"))
        ),
        snapshot.revision,
    )
    result = world.execute_task().execute(work_request(world))
    assert result.decision is not None
    assert result.decision.status == AuthorizationStatus.REQUIRES_HUMAN_APPROVAL
    assert result.opportunity.state == OpportunityState.PLANNED
    assert world.provider.calls == []


def test_future_approval_is_rejected_without_state_change(world: World) -> None:
    opportunity = approved(world)
    assert opportunity.approval is not None
    with pytest.raises(PortError):
        ApproveSubmission(world.opportunities, world.source, world.clock).execute(
            world.reference,
            replace(opportunity.approval, approved_at=world.clock.now() + timedelta(days=1)),
        )
    assert world.current() == opportunity


def test_mismatched_payment_currency_cannot_create_verified_revenue(world: World) -> None:
    approved(world)
    world.submit_task().execute(world.reference, Reference("submission"))
    TrackOutcome(world.opportunities, world.submissions, world.gateway, world.clock).execute(
        world.reference
    )
    world.verifier.status = PaymentStatus.VERIFIED
    world.verifier.amount = Money(Decimal("85"), "EUR")
    with pytest.raises(DomainError):
        VerifyPayment(world.opportunities, world.verifier, world.clock).execute(world.reference)
    assert world.current().state == OpportunityState.ACCEPTED
    assert world.current().verified_revenue == usd("0")
