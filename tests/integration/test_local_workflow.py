from datetime import timedelta
from pathlib import Path

import pytest
from fakes import (
    FakeClock,
    FakeGateway,
    FakeProvider,
    FakeSource,
    FakeVerifier,
    economic_inputs,
    eligibility_request,
    scoring_policy,
    scoring_signals,
)
from local_cases import initialize, instant, repositories, usd

from agentmine.application.contracts.opportunities import DiscoveryRequest, OpportunityObservation
from agentmine.application.contracts.submission import PaymentStatus
from agentmine.application.contracts.workflow import (
    ExecuteTaskRequest,
    PlanTaskRequest,
    ScoreRequest,
)
from agentmine.application.use_cases import (
    ApproveSubmission,
    CheckEligibility,
    DiscoverOpportunities,
    EvaluateOpportunity,
    ExecuteTask,
    NormalizeOpportunity,
    PlanTask,
    RequestHumanApproval,
    RunQA,
    ScoreOpportunity,
    SubmitTask,
    TrackOutcome,
    VerifyPayment,
)
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.finance import Reward
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import HumanApproval, QAResult, QAStatus, TaskType


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
@pytest.mark.parametrize("task_type", list(TaskType))
def test_same_application_flow_with_either_repository_backend(
    backend: str, task_type: TaskType, tmp_path: Path
) -> None:
    path = tmp_path / "agentmine.db"
    repos = repositories(backend, path)
    initialize(repos)
    clock = FakeClock(instant())
    original = Opportunity(Reference("op"), "Research/data", Reward(usd("100")))
    observation = OpportunityObservation(
        original,
        Reference("source"),
        "Requirements",
        clock.now(),
        True,
        clock.now() + timedelta(days=1),
    )
    source = FakeSource(clock, (observation,), deadline=observation.deadline)
    provider = FakeProvider(actual_cost=usd("1.125"))
    gateway = FakeGateway(clock)
    verifier = FakeVerifier(clock, usd("85"))

    def checkpoint(expected: Opportunity) -> None:
        nonlocal repos
        if backend == "sqlite":
            repos = repositories(backend, path)  # New adapters and new connections.
        restored = repos.opportunities.get(original.reference)
        assert restored is not None and restored.value == expected

    DiscoverOpportunities(source, repos.opportunities, clock).execute(DiscoveryRequest(1))
    checkpoint(original)
    checkpoint(NormalizeOpportunity(repos.opportunities).execute(original.reference))
    checkpoint(
        CheckEligibility(
            repos.opportunities,
            source,
            clock,
            EligibilityEngine(EligibilityPolicy(timedelta(hours=1))),
        ).execute(eligibility_request(original.reference))
    )
    checkpoint(
        EvaluateOpportunity(repos.opportunities, source, clock).execute(
            original.reference, economic_inputs()
        )
    )
    checkpoint(
        ScoreOpportunity(
            repos.opportunities, repos.evaluations, source, clock, scoring_policy()
        ).execute(
            ScoreRequest(
                original.reference, Reference("eval"), scoring_signals(), (Reference("evidence"),)
            )
        )
    )
    assert len(repos.evaluations.for_opportunity(original.reference)) == 1
    checkpoint(
        PlanTask(repos.opportunities, source, clock).execute(
            PlanTaskRequest(original.reference, Reference("task"), task_type, "Supported work")
        )
    )
    command = ExecuteTaskRequest(
        original.reference,
        Reference("ledger"),
        Reference("operation"),
        Reference("exec"),
        Reference("deliverable"),
        1,
        usd("1"),
    )
    execution = ExecuteTask(
        repos.opportunities, repos.executions, repos.ledger, provider, source, clock
    ).execute(command)
    checkpoint(execution.opportunity)
    # Cached response, actual costs and content survive; retry cannot dispatch twice.
    retried = ExecuteTask(
        repos.opportunities, repos.executions, repos.ledger, provider, source, clock
    ).execute(command)
    assert retried.opportunity == execution.opportunity
    assert len(provider.calls) == 1
    deliverable = execution.opportunity.deliverable
    assert deliverable is not None
    checkpoint(
        RunQA(repos.opportunities, repos.executions).execute(
            original.reference, QAResult(deliverable, QAStatus.PASSED, "Checks passed")
        )
    )
    review = RequestHumanApproval(repos.opportunities, repos.executions, clock).execute(
        original.reference
    )
    approval = HumanApproval(
        review.deliverable, Reference("target"), Reference("human"), clock.now()
    )
    checkpoint(
        ApproveSubmission(repos.opportunities, source, clock).execute(original.reference, approval)
    )
    submitted = SubmitTask(
        repos.opportunities, repos.executions, repos.submissions, gateway, source, clock
    ).execute(original.reference, Reference("sub"))
    assert submitted.submission is not None
    if backend == "sqlite":
        repos = repositories(backend, path)
    SubmitTask(
        repos.opportunities, repos.executions, repos.submissions, gateway, source, clock
    ).execute(original.reference, Reference("sub"))
    assert gateway.submits == 1
    accepted = TrackOutcome(repos.opportunities, repos.submissions, gateway, clock).execute(
        original.reference
    )
    checkpoint(accepted)
    assert accepted.verified_revenue == usd("0")
    assert repos.submissions.get_outcome(Reference("sub")) == accepted.outcome
    assert (
        VerifyPayment(repos.opportunities, verifier, clock).execute(original.reference) == accepted
    )
    verifier.status = PaymentStatus.VERIFIED
    paid = VerifyPayment(repos.opportunities, verifier, clock).execute(original.reference)
    checkpoint(paid)
    assert paid.state == OpportunityState.PAID and paid.verified_revenue == usd("85")
    ledger = repos.ledger.get(Reference("ledger"))
    assert ledger is not None
    assert ledger.value.records[0].actual_cost == usd("1.125")
    assert ledger.value.records[0].estimated_cost == usd("1")
    assert not ledger.value.outstanding
