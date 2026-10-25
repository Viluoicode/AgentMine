"""Fault injection across durable boundaries; all external effects are fakes."""

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fakes import FakeGateway, economic_inputs, eligibility_request, scoring_policy, scoring_signals
from test_use_cases import World, approved, plan, usd, work_request, world

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.opportunities import DiscoveryRequest
from agentmine.application.contracts.records import BudgetCommit, OpportunitySave
from agentmine.application.contracts.submission import (
    PaymentStatus,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.contracts.workflow import ScoreRequest
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.execution import ExecuteTask
from agentmine.application.use_cases.planning import (
    CheckEligibility,
    DiscoverOpportunities,
    EvaluateOpportunity,
    NormalizeOpportunity,
    ScoreOpportunity,
)
from agentmine.application.use_cases.settlement import SubmitTask, TrackOutcome, VerifyPayment
from agentmine.bootstrap.local import LocalRepositories, open_local_repositories
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.infrastructure.llm.bedrock import BedrockLLMProvider
from agentmine.infrastructure.llm.journal import LLMJournal
from agentmine.infrastructure.llm.pricing import BedrockSettings, TokenPricing
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository

__all__ = ["world"]


def unavailable() -> PortError:
    return PortError(PortErrorCode.UNAVAILABLE, "fault-injection", "Temporary failure")


@pytest.mark.parametrize("changed_source", [False, True])
def test_discovery_recovers_orphan_observation_after_reopen(
    world: World, tmp_path: Path, changed_source: bool
) -> None:
    path = tmp_path / "resilience.db"
    repos = open_local_repositories(path)
    original = world.source.observations[0]
    with patch.object(SQLiteOpportunityRepository, "save", side_effect=unavailable()):
        with pytest.raises(PortError):
            DiscoverOpportunities(world.source, repos.opportunities, world.clock).execute(
                DiscoveryRequest(1)
            )
    repos = open_local_repositories(path)
    assert repos.opportunities.get(world.reference) is None
    assert repos.opportunities.get_observation(world.reference) == original
    world.clock.instant += timedelta(minutes=1)
    world.source.observations = (
        replace(
            original,
            observed_at=world.clock.now(),
            opportunity=replace(original.opportunity, title="Updated source title"),
            source_reference=Reference("other-source")
            if changed_source
            else original.source_reference,
        ),
    )
    command = DiscoverOpportunities(world.source, repos.opportunities, world.clock)
    if changed_source:
        with pytest.raises(PortError) as error:
            command.execute(DiscoveryRequest(1))
        assert error.value.code == PortErrorCode.CONFLICT
        assert repos.opportunities.get(world.reference) is None
    else:
        command.execute(DiscoveryRequest(1))
        restored = repos.opportunities.get(world.reference)
        assert restored is not None and restored.value == original.opportunity
        normalized = NormalizeOpportunity(repos.opportunities).execute(world.reference)
        command.execute(DiscoveryRequest(1))
        retained = repos.opportunities.get(world.reference)
        assert retained is not None and retained.value == normalized
        assert len(repos.opportunities.list_by_status(OpportunityState.NORMALIZED)) == 1
    assert repos.opportunities.get_observation(world.reference) == original


def seed(world: World, path: Path, *, approval: bool = False) -> LocalRepositories:
    if approval:
        approved(world)
    else:
        plan(world)
    repos = open_local_repositories(path)
    repos.opportunities.save(OpportunitySave(world.current(), None))
    observation = world.opportunities.get_observation(world.reference)
    assert observation is not None
    repos.opportunities.save_observation(observation)
    repos.ledger.commit(
        BudgetCommit(
            Reference("ledger"), world.ledger.snapshots[Reference("ledger")].value, None, None
        )
    )
    deliverable = world.current().deliverable
    if deliverable is not None:
        content = world.executions.get_content(deliverable.content_reference)
        assert content is not None
        repos.executions.save_content(content)
    return repos


@pytest.mark.parametrize("method", ["save_content", "save_deliverable"])
def test_execution_recovers_checkpoint_after_database_failure(
    world: World, tmp_path: Path, method: str
) -> None:
    path = tmp_path / "execution.db"
    repos = seed(world, path)
    command = ExecuteTask(
        repos.opportunities,
        repos.executions,
        repos.ledger,
        world.provider,
        world.source,
        world.clock,
    )
    with patch.object(SQLiteExecutionRepository, method, side_effect=unavailable()):
        with pytest.raises(PortError):
            command.execute(work_request(world))
    repos = open_local_repositories(path)
    snapshot = repos.opportunities.get(world.reference)
    assert snapshot is not None and snapshot.value.state == OpportunityState.IN_PROGRESS
    assert repos.executions.get_work_response(Reference("execution")) is not None
    result = replace(
        command, opportunities=repos.opportunities, executions=repos.executions, ledger=repos.ledger
    ).execute(work_request(world))
    assert result.opportunity.state == OpportunityState.QA_PENDING
    assert len(world.provider.calls) == 1
    ledger = repos.ledger.get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.records) == 1
    assert ledger.value.ai_spent(world.clock.now(), monthly=True) == usd("1")
    assert result.opportunity.verified_revenue == usd("0")


def test_real_sqlite_lock_blocks_budget_commit_without_dispatch(
    world: World, tmp_path: Path
) -> None:
    path = tmp_path / "locked.db"
    repos = seed(world, path)
    ledger = SQLiteCostLedgerRepository(SQLiteDatabase(path, timeout_seconds=0))
    before = ledger.get(Reference("ledger"))
    command = ExecuteTask(
        repos.opportunities, repos.executions, ledger, world.provider, world.source, world.clock
    )
    with sqlite3.connect(path, isolation_level=None) as lock:
        lock.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(PortError) as error:
                command.execute(work_request(world))
            assert error.value.code == PortErrorCode.UNAVAILABLE
            assert not world.provider.calls
        finally:
            lock.rollback()
    assert ledger.get(Reference("ledger")) == before
    assert command.execute(work_request(world)).opportunity.state == OpportunityState.QA_PENDING
    assert len(world.provider.calls) == 1


@dataclass
class ReceiptGateway(FakeGateway):
    receipts: dict[Reference, SubmissionResult] = field(default_factory=dict)

    def submit(self, request: SubmissionRequest) -> SubmissionResult:
        result = super().submit(request)
        self.receipts[request.reference] = result
        return result

    def reconcile(self, request: SubmissionRequest) -> SubmissionResult:
        self.reconciles += 1
        return self.receipts[request.reference]  # Observation only; cannot create a receipt.


class TimeoutAfterSend(ReceiptGateway):
    def submit(self, request: SubmissionRequest) -> SubmissionResult:
        super().submit(request)  # Simulated remote receipt exists before transport timeout.
        raise TimeoutError("PRIVATE_TRANSPORT_DETAIL")


@pytest.mark.parametrize("failure", ["timeout", "attempt", "receipt", "opportunity"])
def test_submission_failure_reopen_and_changed_id_never_resend(
    world: World, tmp_path: Path, failure: str
) -> None:
    path = tmp_path / "submission.db"
    repos = seed(world, path, approval=True)
    gateway = TimeoutAfterSend(world.clock) if failure == "timeout" else ReceiptGateway(world.clock)
    command = SubmitTask(
        repos.opportunities, repos.executions, repos.submissions, gateway, world.source, world.clock
    )
    targets = {
        "attempt": (SQLiteSubmissionRepository, "record_attempt"),
        "receipt": (SQLiteSubmissionRepository, "save"),
        "opportunity": (SQLiteOpportunityRepository, "save"),
    }
    if failure == "timeout":
        with pytest.raises(PortError) as error:
            command.execute(world.reference, Reference("send"))
        assert "PRIVATE" not in str(error.value)
    else:
        owner, method = targets[failure]
        with patch.object(owner, method, side_effect=unavailable()):
            with pytest.raises(PortError):
                command.execute(world.reference, Reference("send"))
    repos = open_local_repositories(path)
    command = replace(
        command,
        opportunities=repos.opportunities,
        executions=repos.executions,
        submissions=repos.submissions,
    )
    assert repos.submissions.get_request(Reference("send")) is not None
    with pytest.raises(PortError):
        command.execute(world.reference, Reference("different-send"))
    result = command.execute(world.reference, Reference("send"))
    assert result.submission is not None
    assert command.execute(world.reference, Reference("send")) == result
    assert gateway.submits == 1
    assert gateway.reconciles == int(failure in ("timeout", "attempt"))
    TrackOutcome(repos.opportunities, repos.submissions, gateway, world.clock).execute(
        world.reference
    )
    for status in (PaymentStatus.PENDING, PaymentStatus.UNVERIFIABLE):
        world.verifier.status = status
        result_op = VerifyPayment(
            repos.opportunities, world.verifier, world.clock, repos.submissions
        ).execute(world.reference)
        assert result_op.state == OpportunityState.ACCEPTED
        assert result_op.accepted_reward is None  # This gateway does not report an amount.
        assert result_op.verified_revenue == usd("0")
    assert len(repos.opportunities.accepted_but_unpaid()) == 1
    assert repos.opportunities.verified_revenue("USD") == usd("0")


class UnavailableBedrock:
    calls = 0

    def count_tokens(self, **kwargs: object) -> object:
        return {"inputTokens": 20}

    def converse(self, **kwargs: object) -> object:
        self.calls += 1
        raise TimeoutError("PRIVATE_PROVIDER_DETAIL")


def test_bedrock_outage_preserves_reservation_and_free_pipeline_continues(
    world: World, tmp_path: Path
) -> None:
    path = tmp_path / "outage.db"
    repos = seed(world, path)
    client = UnavailableBedrock()
    provider = BedrockLLMProvider(
        client,
        BedrockSettings(
            "fixture-model",
            "fixture-region",
            TokenPricing(usd("1000"), usd("2000"), "synthetic tariff"),
            100,
            100,
        ),
        BudgetManager(repos.ledger, Reference("ledger"), world.clock),
        LLMJournal(tmp_path / "llm.db"),
    )
    command = ExecuteTask(
        repos.opportunities, repos.executions, repos.ledger, provider, world.source, world.clock
    )
    with pytest.raises(PortError) as error:
        command.execute(work_request(world))
    assert "PRIVATE" not in str(error.value)
    repos = open_local_repositories(path)
    with pytest.raises(PortError) as retry:
        replace(
            command,
            opportunities=repos.opportunities,
            executions=repos.executions,
            ledger=repos.ledger,
        ).execute(work_request(world))
    assert retry.value.code == PortErrorCode.OUTCOME_UNKNOWN
    assert client.calls == 1
    ledger = repos.ledger.get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.outstanding) == 1
    assert not ledger.value.records  # Unknown charge is reserved, not fabricated as actual zero.
    original = world.source.observations[0]
    reference = Reference("second-listing")
    world.source.observations = (
        replace(
            original,
            opportunity=replace(original.opportunity, reference=reference),
            source_reference=Reference("second-source"),
        ),
    )
    DiscoverOpportunities(world.source, repos.opportunities, world.clock).execute(
        DiscoveryRequest(1)
    )
    NormalizeOpportunity(repos.opportunities).execute(reference)
    CheckEligibility(
        repos.opportunities,
        world.source,
        world.clock,
        EligibilityEngine(EligibilityPolicy(timedelta(hours=1))),
    ).execute(eligibility_request(reference))
    EvaluateOpportunity(repos.opportunities, world.source, world.clock).execute(
        reference, economic_inputs()
    )
    scored = ScoreOpportunity(
        repos.opportunities, repos.evaluations, world.source, world.clock, scoring_policy()
    ).execute(ScoreRequest(reference, Reference("second-evaluation"), scoring_signals(), ()))
    assert scored.state == OpportunityState.SCORED
    assert scored.verified_revenue == usd("0") and client.calls == 1
    assert repos.ledger.get(Reference("ledger")) == ledger
