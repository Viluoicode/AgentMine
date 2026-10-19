"""Milestone 6A acceptance gate: real local components, synthetic external effects, $0."""

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fakes import economic_inputs, eligibility_request, scoring_policy, scoring_signals
from local_flow import LocalFlow, usd

from agentmine.application.contracts.opportunities import DiscoveryRequest
from agentmine.application.contracts.records import BudgetCommit
from agentmine.application.contracts.submission import PaymentStatus
from agentmine.application.contracts.workflow import ExecuteTaskRequest
from agentmine.application.errors import ApplicationError
from agentmine.application.use_cases import (
    DiscoverOpportunities,
    ExecuteTask,
    SubmitTask,
    TrackOutcome,
    VerifyPayment,
)
from agentmine.application.use_cases.context import observe_status
from agentmine.application.use_cases.deliverable_qa import DeliverableQA
from agentmine.application.use_cases.metrics import GetEconomicMetrics
from agentmine.application.use_cases.operator import DecideOperatorReview, PrepareOperatorReview
from agentmine.domain.approval import ApprovalAction, ApprovalScope, OperatorDecision
from agentmine.domain.budget import OperatingMode
from agentmine.domain.economics import EconomicAssessment
from agentmine.domain.eligibility import Deadline, DeadlineKind, EligibilityPolicy
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.finance import CostCategory
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAOutcome
from agentmine.domain.revalidation import ResumeAssessment
from agentmine.domain.scoring import ScoringAssessment
from agentmine.domain.spending import AuthorizationStatus, CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import TaskStatus, TaskType
from agentmine.infrastructure.llm.mock import MockLLMProvider
from agentmine.infrastructure.sqlite.approval import SQLiteApprovalRepository
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.qa import SQLiteQAJournal


def settle(flow: LocalFlow) -> None:
    inspection = flow.execute_worker()
    journal = SQLiteQAJournal(SQLiteDatabase(flow.path))
    report = DeliverableQA(
        flow.repos.opportunities, flow.repos.executions, journal, flow.clock, llm=flow.llm
    ).execute(inspection)
    assert report.outcome == QAOutcome.PASS
    assert SQLiteQAJournal(SQLiteDatabase(flow.path)).get_report(report.reference) == report
    flow.checkpoint(OpportunityState.READY_FOR_HUMAN_REVIEW)
    assert flow.current().approval is None and flow.gateway.submits == 0

    def submit() -> None:
        SubmitTask(
            flow.repos.opportunities,
            flow.repos.executions,
            flow.repos.submissions,
            flow.gateway,
            flow.source,
            flow.clock,
        ).execute(flow.reference, Reference("submission"))

    with pytest.raises(ApplicationError):
        submit()
    assert flow.gateway.submits == 0
    approvals = SQLiteApprovalRepository(SQLiteDatabase(flow.path))
    review = PrepareOperatorReview(
        flow.repos.opportunities, flow.repos.executions, flow.repos.ledger, approvals, flow.clock
    ).execute(
        Reference("review"),
        flow.reference,
        Reference("ledger"),
        ApprovalScope(
            ApprovalAction.EXTERNAL_SUBMISSION,
            Reference("fixture:destination"),
            inspection.deliverable.content_reference,
            inspection.deliverable,
        ),
    )
    assert review.content and review.qa_result and review.eligibility and review.risks
    assert review.actual_cost_so_far == (usd("0"),)
    decision = DecideOperatorReview(
        flow.repos.opportunities,
        flow.repos.executions,
        flow.repos.ledger,
        approvals,
        flow.source,
        flow.clock,
        Reference("fixture:operator"),
    ).execute(
        review.reference, OperatorDecision.APPROVE, "Simulated operator reviewed fixture artifacts"
    )
    assert decision.actor == Reference("fixture:operator")
    assert (
        SQLiteApprovalRepository(SQLiteDatabase(flow.path)).get_decision(review.reference)
        == decision
    )
    flow.checkpoint(OpportunityState.APPROVED_FOR_SUBMISSION)
    assert flow.gateway.submits == 0
    submit()
    flow.checkpoint(OpportunityState.SUBMITTED)
    submit()
    assert flow.gateway.submits == 1 and flow.gateway.reconciles == 0
    assert flow.current().verified_revenue == usd("0")
    TrackOutcome(
        flow.repos.opportunities, flow.repos.submissions, flow.gateway, flow.clock
    ).execute(flow.reference)
    flow.checkpoint(OpportunityState.ACCEPTED)
    accepted_reward = flow.current().accepted_reward
    assert accepted_reward is not None
    assert accepted_reward.amount == usd("90")
    metrics = GetEconomicMetrics(flow.repos.opportunities, flow.repos.ledger)
    assert metrics.execute(flow.reference, Reference("ledger")).verified_revenue == usd("0")
    for status in (PaymentStatus.PENDING, PaymentStatus.UNVERIFIABLE):
        flow.verifier.status = status
        VerifyPayment(
            flow.repos.opportunities, flow.verifier, flow.clock, flow.repos.submissions
        ).execute(flow.reference)
        assert flow.current().state == OpportunityState.ACCEPTED
        assert flow.current().verified_revenue == usd("0")
    flow.verifier.status = PaymentStatus.VERIFIED
    VerifyPayment(
        flow.repos.opportunities, flow.verifier, flow.clock, flow.repos.submissions
    ).execute(flow.reference)
    flow.checkpoint(OpportunityState.PAID)
    VerifyPayment(
        flow.repos.opportunities, flow.verifier, flow.clock, flow.repos.submissions
    ).execute(flow.reference)
    assert flow.verifier.calls == 3  # Completed retry reuses durable evidence.
    result = GetEconomicMetrics(flow.repos.opportunities, flow.repos.ledger).execute(
        flow.reference, Reference("ledger")
    )
    assert result.verified_revenue == usd("85")
    assert result.total_actual_cost == usd("0")
    assert result.net_verified_value == usd("85")
    assert not result.outstanding_operations
    assert result.opportunity.potential_reward.amount == usd("100")
    for category in CostCategory:
        assert result.cost(category) == usd("0")
    assert len(flow.repos.submissions.payment_history(Reference("submission"))) == 3
    print(
        json.dumps(
            {
                "scenario": flow.task_type.value,
                "states": flow.states,
                "external_api_spend_usd": "0",
                "synthetic_verified_reward_usd": "85",
                "recorded_cost_usd": "0",
                "synthetic_net_verified_value_usd": "85",
                "submission_dispatches": flow.gateway.submits,
                "operator": decision.actor.value,
            }
        )
    )


@pytest.mark.parametrize("task_type", list(TaskType))
def test_local_discovery_to_verified_value(task_type: TaskType, tmp_path: Path) -> None:
    flow = LocalFlow(tmp_path / "agentmine.sqlite3", task_type)
    flow.discover_to_score()
    # Authorize the explicit future task identity before planning; no dispatch here.
    estimate = usd("1" if task_type == TaskType.RESEARCH else "0")
    authorized = flow.manager().authorize(estimate, flow.context())
    assert authorized.status == AuthorizationStatus.AUTHORIZED
    flow.plan()
    with patch.object(MockLLMProvider, "perform_work", wraps=flow.llm.perform_work) as model:
        settle(flow)
        assert model.call_count == (1 if task_type == TaskType.RESEARCH else 0)
    ledger = flow.repos.ledger.get(Reference("ledger"))
    assert ledger is not None
    execution_cost = next(
        record
        for record in ledger.value.records
        if record.context.operation_reference == Reference("execution-cost")
    )
    assert execution_cost.estimated_cost == estimate
    assert execution_cost.actual_cost == usd("0")
    # Synthetic accounting observations prove all four terms are subtracted.
    # They do not invoke tools, transfer funds, or represent actual API charges.
    for category, amount in (
        (CostCategory.AI, "1"),
        (CostCategory.TOOL, "2"),
        (CostCategory.INFRASTRUCTURE, "3"),
        (CostCategory.TRANSACTION, "4"),
    ):
        context = CostContext(
            Reference("synthetic-late-cost:" + category.value),
            OperationType.OUTCOME_TRACKING,
            flow.clock.now(),
            opportunity_reference=flow.reference,
        )
        decision = flow.manager().authorize(usd(amount), context, category)
        assert decision.authorization is not None
        flow.manager().record(decision.authorization, usd(amount), flow.clock.now())
    flow.checkpoint(OpportunityState.PAID)
    metrics = GetEconomicMetrics(flow.repos.opportunities, flow.repos.ledger).execute(
        flow.reference, Reference("ledger")
    )
    assert metrics.total_actual_cost == usd("10")
    assert metrics.verified_revenue == usd("85")
    assert metrics.net_verified_value == usd("75")
    print(
        json.dumps(
            {
                "scenario": task_type.value + "-synthetic-late-costs",
                "synthetic_cost_usd": "10",
                "synthetic_net_verified_value_usd": "75",
                "external_api_spend_usd": "0",
            }
        )
    )
    assert flow.states == [
        state.value
        for state in (
            OpportunityState.DISCOVERED,
            OpportunityState.NORMALIZED,
            OpportunityState.ELIGIBLE,
            OpportunityState.EVALUATED,
            OpportunityState.SCORED,
            OpportunityState.PLANNED,
            OpportunityState.IN_PROGRESS,
            OpportunityState.QA_PENDING,
            OpportunityState.READY_FOR_HUMAN_REVIEW,
            OpportunityState.APPROVED_FOR_SUBMISSION,
            OpportunityState.SUBMITTED,
            OpportunityState.ACCEPTED,
            OpportunityState.PAID,
            OpportunityState.PAID,
        )
    ]


@pytest.mark.parametrize("changed", ["open", "expired", "closed", "ineligible"])
def test_scout_continuity_and_refreshed_resume(changed: str, tmp_path: Path) -> None:
    flow = LocalFlow(tmp_path / "agentmine.sqlite3", TaskType.RESEARCH)
    # Exhaust the ledger through a synthetic measurement, not by changing requested mode.
    snapshot = flow.repos.ledger.get(Reference("ledger"))
    assert snapshot is not None
    budget = snapshot.value.with_policy(
        replace(snapshot.value.policy, monthly_ai_budget=usd("1"), daily_ai_budget=usd("1"))
    )
    flow.repos.ledger.commit(BudgetCommit(Reference("ledger"), budget, snapshot.revision, None))
    context = CostContext(
        Reference("prior-simulated-usage"), OperationType.SCORING, flow.clock.now()
    )
    prior = flow.manager().authorize(usd("1"), context)
    assert prior.authorization is not None
    flow.manager().record(prior.authorization, usd("1"), flow.clock.now())
    snapshot = flow.repos.ledger.get(Reference("ledger"))
    assert (
        snapshot is not None
        and snapshot.value.operating_mode(flow.clock.now()) == OperatingMode.SCOUT_ONLY
    )
    flow.discover_to_score()  # All free steps genuinely run after exhaustion.
    flow.plan()
    with patch.object(MockLLMProvider, "perform_work", wraps=flow.llm.perform_work) as model:
        result = ExecuteTask(
            flow.repos.opportunities,
            flow.repos.executions,
            flow.repos.ledger,
            flow.llm,
            flow.source,
            flow.clock,
        ).execute(
            ExecuteTaskRequest(
                flow.reference,
                Reference("ledger"),
                Reference("execution-cost"),
                Reference("execution"),
                Reference("deliverable"),
                1,
                usd("1"),
            )
        )
        assert result.decision is not None and result.decision.status == AuthorizationStatus.DENIED
        assert result.decision.mode == OperatingMode.SCOUT_ONLY
        assert model.call_count == 0
    flow.checkpoint(OpportunityState.WAITING_FOR_BUDGET)
    waiting_task = flow.current().task
    assert waiting_task is not None and waiting_task.status == TaskStatus.WAITING_FOR_BUDGET
    assert len(flow.repos.opportunities.list_waiting_for_budget()) == 1
    # Another listing is persisted while the paid task is waiting.
    observation = flow.source.observations[0]
    extra = replace(
        observation,
        opportunity=replace(observation.opportunity, reference=Reference("new-listing")),
        source_reference=Reference("new-source-item"),
    )
    flow.source.observations = (extra,)
    DiscoverOpportunities(flow.source, flow.repos.opportunities, flow.clock).execute(
        DiscoveryRequest(1)
    )
    assert flow.repos.opportunities.get(Reference("new-listing")) is not None
    flow.source.observations = (observation,)
    # Restoration is an explicit local policy update, not erasure of incurred costs.
    snapshot = flow.repos.ledger.get(Reference("ledger"))
    assert snapshot is not None
    restored = snapshot.value.with_policy(
        replace(snapshot.value.policy, monthly_ai_budget=usd("100"), daily_ai_budget=usd("100"))
    )
    flow.repos.ledger.commit(BudgetCommit(Reference("ledger"), restored, snapshot.revision, None))
    assert restored.operating_mode(flow.clock.now()) == OperatingMode.FULL
    assert restored.records == snapshot.value.records
    flow.clock.instant += timedelta(hours=1)
    if changed == "expired":
        flow.clock.instant += timedelta(days=4)
    if changed == "closed":
        flow.source.is_open = False
    refreshes = flow.source.refreshes
    status = observe_status(flow.repos.opportunities, flow.source, flow.clock, flow.reference)
    assert flow.source.refreshes == refreshes + 1
    assert status.is_open is not None and status.deadline_known
    assert status.observed_at == flow.clock.now()
    request = eligibility_request(flow.reference)
    facts = replace(
        request.facts, is_open=status.is_open, deadline=Deadline(DeadlineKind.AT, status.deadline)
    )
    if changed == "ineligible":
        from agentmine.domain.eligibility import AIParticipationPolicy

        facts = replace(facts, ai_policy=AIParticipationPolicy.PROHIBITED)
    eligibility = EligibilityEngine(EligibilityPolicy(timedelta(hours=1))).evaluate(
        facts, request.profile, flow.clock.now()
    )
    inputs = economic_inputs()
    inputs = replace(
        inputs,
        predicted_success_probability=replace(
            inputs.predicted_success_probability, value=Decimal("0.5")
        ),
    )
    economics = EconomicAssessment(flow.current().potential_reward, inputs)
    score = ScoringAssessment(economics, scoring_signals(), scoring_policy())
    assert score.score != flow.current().score  # Recalculated; not copied stale score.
    assessment = ResumeAssessment(
        flow.reference,
        status.observed_at,
        status.is_open,
        status.deadline,
        eligibility,
        economics.expected_net_value,
        score.score,
    )
    snapshot = flow.repos.ledger.get(Reference("ledger"))
    assert snapshot is not None
    resumed = flow.current().resume_after_budget(assessment, snapshot.value, flow.clock.now())
    flow.repos.ledger.commit(
        BudgetCommit(Reference("ledger"), resumed.budget, snapshot.revision, resumed.decision)
    )
    flow.save(resumed.opportunity)
    if changed == "open":
        flow.checkpoint(OpportunityState.PLANNED)
        assert flow.current().score == score.score
        settle(flow)
    else:
        flow.checkpoint(
            OpportunityState.INELIGIBLE if changed == "ineligible" else OpportunityState.SKIPPED
        )
        assert resumed.decision is None
        assert flow.current().execution is None and flow.tool.calls == 0
        task = flow.current().task
        assert task is not None
        assert task.status == (TaskStatus.EXPIRED if changed == "expired" else TaskStatus.CANCELLED)
        assert not resumed.budget.outstanding
        assert flow.gateway.submits == flow.verifier.calls == 0
    print(
        json.dumps(
            {
                "scenario": "budget-restoration-" + changed,
                "states": flow.states,
                "external_api_spend_usd": "0",
                "synthetic_prior_cost_usd": "1",
                "refresh_observed_at": status.observed_at.isoformat(),
            }
        )
    )
