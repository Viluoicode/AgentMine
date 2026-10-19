"""SDK integration against Moto DynamoDB; never contacts an AWS endpoint."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from history_fakes import make_world, progress
from local_cases import RepositoryPorts, budget, instant, snapshots, usd
from test_local_persistence import submission_request

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.contracts.records import BudgetCommit, OpportunitySave
from agentmine.application.contracts.submission import (
    OutcomeObservation,
    PaymentStatus,
    PaymentVerificationResult,
    SubmissionAttemptStatus,
    SubmissionResult,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.history import (
    CaptureHistoricalObservation,
    GetHistoricalStatistics,
)
from agentmine.bootstrap.dynamodb import DynamoDBRepositories, dynamodb_repositories
from agentmine.domain.finance import CostCategory
from agentmine.domain.history import HistoricalQuery
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import Outcome, OutcomeStatus, TaskType
from agentmine.infrastructure.dynamodb.store import collection, key, table_definition, wire


@pytest.fixture
def dynamo() -> Iterator[DynamoDBRepositories]:
    moto = pytest.importorskip(
        "moto", reason="Install .[dev,dynamodb-test] for DynamoDB integration tests"
    )
    boto3 = pytest.importorskip("boto3")
    with moto.mock_aws():
        client = boto3.client(
            "dynamodb",
            region_name="us-east-1",
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )
        client.create_table(**table_definition("agentmine-test"))
        # Force every collection through pagination, even with tiny test fixtures.
        yield dynamodb_repositories(client, "agentmine-test", page_size=1)


@pytest.mark.parametrize("task_type", list(TaskType))
def test_existing_application_flow_uses_dynamodb_unchanged(
    dynamo: DynamoDBRepositories,
    task_type: TaskType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import test_local_workflow

    def repositories(backend: str, path: Path) -> RepositoryPorts:
        return RepositoryPorts(
            dynamo.opportunities,
            dynamo.evaluations,
            dynamo.executions,
            dynamo.submissions,
            dynamo.ledger,
        )

    monkeypatch.setattr(test_local_workflow, "repositories", repositories)
    test_local_workflow.test_same_application_flow_with_either_repository_backend(
        "dynamodb", task_type, Path("unused-dynamodb-fixture")
    )
    reopened = dynamodb_repositories(dynamo.opportunities.database.client, "agentmine-test")
    assert reopened.opportunities.get(Reference("op")) == dynamo.opportunities.get(Reference("op"))
    assert reopened.opportunities.verified_revenue("USD") == usd("85")
    assert len(reopened.executions.for_opportunity(Reference("op"))) == 1
    assert any(
        item.status == PaymentStatus.VERIFIED
        for item in reopened.submissions.payment_history(Reference("sub"))
    )


def test_access_patterns_and_exact_ranking(dynamo: DynamoDBRepositories) -> None:
    repo = dynamo.opportunities
    expected = {}
    for state in (
        OpportunityState.ELIGIBLE,
        OpportunityState.WAITING_FOR_BUDGET,
        OpportunityState.READY_FOR_HUMAN_REVIEW,
        OpportunityState.ACCEPTED,
        OpportunityState.PAID,
        OpportunityState.SCORED,
    ):
        identifier = state.value
        stages = snapshots(identifier)
        op = stages[state]
        repo.save_observation(
            OpportunityObservation(
                stages[OpportunityState.DISCOVERED],
                Reference("source"),
                "Fixture",
                instant(),
                True,
                instant() + timedelta(days=1),
            )
        )
        repo.save(OpportunitySave(op, None))
        expected[state] = op
    assert repo.list_eligible() == (expected[OpportunityState.ELIGIBLE],)
    assert repo.list_waiting_for_budget() == (expected[OpportunityState.WAITING_FOR_BUDGET],)
    assert repo.submissions_awaiting_review() == (
        expected[OpportunityState.READY_FOR_HUMAN_REVIEW],
    )
    assert repo.accepted_but_unpaid() == (expected[OpportunityState.ACCEPTED],)
    assert len(repo.list_by_source(Reference("source"))) == 6
    assert repo.verified_revenue("USD") == usd("85")
    assert repo.verified_revenue("EUR") == replace(usd("0"), currency="EUR")
    for identifier, score in (
        ("high", "99.123456789012345678901234567890123456789"),
        ("low", "99.123456789012345678901234567890123456788"),
    ):
        repo.save(OpportunitySave(snapshots(identifier, score)[OpportunityState.SCORED], None))
    assert [op.reference.value for op in repo.list_highest_scoring(2)] == ["high", "low"]
    # Changing state removes the old GSI entry; revisions survive fresh composition.
    op = expected[OpportunityState.ELIGIBLE]
    repo.save(OpportunitySave(op.skip("Fixture decision"), 1))
    assert repo.list_eligible() == ()
    with pytest.raises(PortError) as error:
        repo.save(OpportunitySave(op, 1))
    assert error.value.code == PortErrorCode.CONFLICT


def test_budget_atomic_audit_cost_period_and_stale_write(dynamo: DynamoDBRepositories) -> None:
    ledger = Reference("ledger")
    repo = dynamo.ledger
    repo.commit(BudgetCommit(ledger, budget(), None, None))
    context = CostContext(Reference("usage"), OperationType.SCORING, instant())
    decision = budget().authorize(usd("1"), CostCategory.AI, context)
    repo.commit(BudgetCommit(ledger, decision.budget, 1, decision))
    recording = decision.budget.record(usd("1.25"), CostCategory.AI, context)
    repo.commit(BudgetCommit(ledger, recording.budget, 2, recording))
    assert len(repo.history(ledger)) == 3
    assert repo.costs_by_period(ledger, instant(), instant() + timedelta(seconds=1)) == (
        recording.record,
    )
    assert repo.costs_by_period(ledger, instant() - timedelta(seconds=1), instant()) == ()
    assert repo.monthly_cost(ledger, 2026, 10) == usd("1.25")
    assert repo.monthly_cost(ledger, 2026, 10, CostCategory.TOOL) == usd("0")
    with pytest.raises(PortError):
        repo.commit(BudgetCommit(ledger, decision.budget, 1, decision))
    assert len(repo.history(ledger)) == 3
    # Poison the next audit slot, forcing transaction cancellation AFTER CAS evaluation.
    store = repo.database
    poison = store.item(
        collection("budget_audit", ledger.value), "00000000000000000004", Reference("occupied")
    )
    store.transact([store.put(poison)])
    with pytest.raises(PortError):
        repo.commit(BudgetCommit(ledger, recording.budget, 3, None))
    snapshot = repo.get(ledger)
    assert snapshot is not None and snapshot.revision == 3


@pytest.mark.parametrize("different_ids", [False, True])
def test_submission_claim_has_only_one_owner(
    dynamo: DynamoDBRepositories, different_ids: bool
) -> None:
    original = submission_request()

    def claim(index: int) -> bool:
        request = (
            replace(original, reference=Reference(f"send-{index}")) if different_ids else original
        )
        try:
            return dynamo.submissions.claim_request(request)
        except PortError as error:
            assert error.code == PortErrorCode.CONFLICT
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, (1, 2))) == [False, True]


def test_confirmations_and_terminal_outcomes_are_immutable(dynamo: DynamoDBRepositories) -> None:
    op = snapshots()[OpportunityState.SUBMITTED]
    assert op.submission is not None
    result = SubmissionResult(
        op.submission.reference,
        SubmissionAttemptStatus.CONFIRMED,
        instant(),
        op.submission,
        "Received",
    )
    repo = dynamo.submissions
    repo.record_attempt(result)
    repo.record_attempt(result)
    with pytest.raises(PortError):
        repo.record_attempt(replace(result, explanation="Different receipt"))
    assert repo.attempts_for(result.reference) == (result,)
    observation = OutcomeObservation(
        result.reference,
        instant(),
        Outcome(
            result.reference,
            OutcomeStatus.REJECTED,
            Reference("rejection"),
            rejection_reason="Missing evidence",
        ),
    )
    repo.record_outcome_observation(observation)
    with pytest.raises(PortError):
        repo.record_outcome_observation(
            replace(
                observation,
                outcome=Outcome(result.reference, OutcomeStatus.ACCEPTED, Reference("accepted")),
            )
        )
    assert repo.outcome_history(result.reference) == (observation,)


def test_payment_id_cannot_credit_two_submissions(dynamo: DynamoDBRepositories) -> None:
    paid = snapshots()[OpportunityState.PAID]
    assert (
        paid.payment is not None
        and paid.payment_verification is not None
        and paid.submission is not None
    )
    first = PaymentVerificationResult(
        paid.submission.reference,
        PaymentStatus.VERIFIED,
        instant(),
        paid.payment,
        "Fixture",
        paid.payment_verification,
    )
    reward = replace(paid.payment, submission_reference=Reference("other"))
    second = replace(
        first,
        submission_reference=Reference("other"),
        payment=reward,
        verification=replace(paid.payment_verification, reward=reward),
    )
    repo = dynamo.submissions
    repo.record_payment_observation(first)
    repo.record_payment_observation(first)
    with pytest.raises(PortError):
        repo.record_payment_observation(second)
    assert repo.payment_history(Reference("other")) == ()
    assert repo.payment_history(first.submission_reference) == (first,)


def test_history_capture_latest_as_of_and_atomic_sequence(dynamo: DynamoDBRepositories) -> None:
    world = make_world("history")
    progress(world, OpportunityState.PAID)
    repo = dynamo.history
    capture = CaptureHistoricalObservation(
        world.opportunities, world.evaluations, world.ledger, repo, world.clock
    )
    first = capture.execute(
        Reference("first"), world.reference, Reference("ledger"), Reference("market")
    )
    world.clock.instant += timedelta(seconds=1)
    second = capture.execute(
        Reference("second"), world.reference, Reference("ledger"), Reference("market")
    )
    assert repo.latest(HistoricalQuery()) == (second,)
    assert repo.latest(HistoricalQuery(as_of=first.captured_at)) == (first,)
    assert GetHistoricalStatistics(repo).execute().research.attempts == 1
    with pytest.raises(PortError):
        repo.append(replace(second, reference=Reference("stale")), first.reference)
    assert repo.get(Reference("stale")) is None
    assert repo.for_opportunity(world.reference) == (first, second)


def test_immutable_size_checksum_and_ambiguous_failure(dynamo: DynamoDBRepositories) -> None:
    repo = dynamo.executions
    content = ReferencedText(Reference("content"), "small")
    repo.save_content(content)
    repo.save_content(content)
    with pytest.raises(PortError):
        repo.save_content(replace(content, text="changed"))
    with pytest.raises(PortError) as error:
        repo.save_content(ReferencedText(Reference("huge"), "x" * (400 * 1024)))
    assert error.value.code == PortErrorCode.UNSUPPORTED
    assert repo.get_content(Reference("huge")) is None
    store = repo.database
    with patch.object(store.client, "transact_write_items", side_effect=TimeoutError("SECRET")):
        with pytest.raises(PortError) as error:
            repo.save_content(ReferencedText(Reference("timeout"), "unknown"))
        assert error.value.code == PortErrorCode.OUTCOME_UNKNOWN
        assert "SECRET" not in str(error.value)
    item = store.item(*key("content", "content"), content)
    item["digest"] = "corrupt"
    store.transact([{"Put": {"TableName": store.table, "Item": wire(item)}}])
    with pytest.raises(PortError) as error:
        repo.get_content(content.reference)
    assert error.value.code == PortErrorCode.INVALID_RESPONSE


def test_two_budget_writers_cannot_reserve_same_revision(dynamo: DynamoDBRepositories) -> None:
    repo = dynamo.ledger
    repo.commit(BudgetCommit(Reference("ledger"), budget(), None, None))

    def reserve(index: int) -> bool:
        decision = budget().authorize(
            usd("1"),
            CostCategory.AI,
            CostContext(Reference(f"op-{index}"), OperationType.SCORING, instant()),
        )
        try:
            repo.commit(BudgetCommit(Reference("ledger"), decision.budget, 1, decision))
            return True
        except PortError as error:
            assert error.code == PortErrorCode.CONFLICT
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, (1, 2))) == [False, True]
    snapshot = repo.get(Reference("ledger"))
    assert snapshot is not None and len(snapshot.value.outstanding) == 1
    assert len(repo.history(Reference("ledger"))) == 2


@pytest.mark.parametrize("research", [True, False])
def test_worker_qa_and_operator_ports_use_dynamodb(
    dynamo: DynamoDBRepositories, research: bool
) -> None:
    from data_fakes import make_data_world
    from fakes import FakeSource
    from qa_fakes import inspection_for, seed
    from test_research_worker import make_world as research_world

    from agentmine.application.use_cases.deliverable_qa import DeliverableQA
    from agentmine.application.use_cases.operator import DecideOperatorReview, PrepareOperatorReview
    from agentmine.domain.approval import ApprovalAction, ApprovalScope, OperatorDecision
    from agentmine.domain.finance import Reward
    from agentmine.domain.opportunity import Opportunity
    from agentmine.domain.qa import QAOutcome

    if research:
        world = research_world(dynamo.research)
        dynamo.ledger.commit(
            BudgetCommit(
                Reference("ledger"), world.ledger.snapshots[Reference("ledger")].value, None, None
            )
        )
        worker = replace(world.worker, budget=replace(world.worker.budget, ledger=dynamo.ledger))
        result = worker.execute(world.plan)
        assert worker.execute(world.plan) == result
        assert len(world.llm.calls) == len(world.tool.calls) == 1
        inspection = inspection_for(world.plan, result)
        clock = world.clock
    else:
        data = make_data_world(journal=dynamo.data)
        dynamo.ledger.commit(
            BudgetCommit(
                Reference("ledger"), data.ledger.snapshots[Reference("ledger")].value, None, None
            )
        )
        data_worker = replace(data.worker, budget=replace(data.worker.budget, ledger=dynamo.ledger))
        data_result = data_worker.execute(data.plan)
        assert data_worker.execute(data.plan) == data_result
        assert not data.llm.calls
        inspection = inspection_for(data.plan, data_result)
        clock = data.clock
    seed(inspection, dynamo.opportunities, dynamo.executions)
    report = DeliverableQA(dynamo.opportunities, dynamo.executions, dynamo.qa, clock).execute(
        inspection
    )
    assert report.outcome == QAOutcome.PASS
    assert dynamo.qa.get_report(inspection.reference) == report
    original = Opportunity(Reference("opp"), "QA fixture", Reward(usd("10")))
    observation = OpportunityObservation(
        original,
        Reference("source"),
        "Fixture",
        clock.now(),
        True,
        inspection.plan.execution.task.deadline,
    )
    dynamo.opportunities.save_observation(observation)
    source = FakeSource(clock, (observation,), deadline=observation.deadline)
    review = PrepareOperatorReview(
        dynamo.opportunities, dynamo.executions, dynamo.ledger, dynamo.approvals, clock
    ).execute(
        Reference("review"),
        original.reference,
        Reference("ledger"),
        ApprovalScope(
            ApprovalAction.EXTERNAL_SUBMISSION,
            Reference("destination"),
            inspection.deliverable.content_reference,
            inspection.deliverable,
        ),
    )
    decision = DecideOperatorReview(
        dynamo.opportunities,
        dynamo.executions,
        dynamo.ledger,
        dynamo.approvals,
        source,
        clock,
        Reference("operator"),
    ).execute(review.reference, OperatorDecision.APPROVE, "Offline review")
    assert dynamo.approvals.get_decision(review.reference) == decision
    with pytest.raises(PortError):
        dynamo.approvals.save_decision(replace(decision, reason="Altered decision"))


def test_read_failure_is_not_absence_and_limits_fail_before_dispatch(
    dynamo: DynamoDBRepositories,
) -> None:
    store = dynamo.executions.database
    with patch.object(store.client, "get_item", side_effect=RuntimeError("PRIVATE")):
        with pytest.raises(PortError) as error:
            dynamo.executions.get_content(Reference("missing"))
        assert error.value.code == PortErrorCode.UNAVAILABLE
        assert "PRIVATE" not in str(error.value)
    with patch.object(store.client, "transact_write_items") as dispatch:
        with pytest.raises(PortError) as error:
            store.transact(
                [store.put(store.item("x", str(i), Reference("value"))) for i in range(101)]
            )
        assert error.value.code == PortErrorCode.UNSUPPORTED
        dispatch.assert_not_called()
        with pytest.raises(PortError):
            store.transact([store.put(store.item("x", "y" * 1025, Reference("value")))])
        dispatch.assert_not_called()


def test_stale_index_candidate_reloads_current_state(dynamo: DynamoDBRepositories) -> None:
    from agentmine.infrastructure.dynamodb.store import DynamoStore

    repo = dynamo.opportunities
    stages = snapshots()
    repo.save(OpportunitySave(stages[OpportunityState.ACCEPTED], None))
    pk, sk = key("opportunity", "op")
    repo.save(OpportunitySave(stages[OpportunityState.PAID], 1))
    # Moto does not simulate GSI propagation lag; inject stale keys to exercise the boundary.
    with patch.object(DynamoStore, "query", return_value=({"PK": pk, "SK": sk},)):
        assert repo.accepted_but_unpaid() == ()
    assert repo.verified_revenue("USD") == usd("85")
