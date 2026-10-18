import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import localcontext
from pathlib import Path
from threading import Barrier

import pytest
from fakes import economic_inputs, scoring_policy, scoring_signals
from local_cases import budget, instant, snapshots, usd

from agentmine.application.contracts.ai import AIResponse, DeliverableDraft, ReferencedText
from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.contracts.records import BudgetCommit, EvaluationRecord, OpportunitySave
from agentmine.application.contracts.submission import (
    SubmissionAttemptStatus,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.contracts.workflow import ExecuteTaskRequest
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.bootstrap.local import open_local_repositories
from agentmine.domain.budget import Budget, BudgetPolicy
from agentmine.domain.economics import EconomicAssessment
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import CostCategory
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.revalidation import ResumeAssessment
from agentmine.domain.scoring import ScoringAssessment
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import QAStatus
from agentmine.infrastructure.sqlite.codec import SnapshotCodec
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository


@pytest.mark.parametrize("state", list(OpportunityState))
def test_all_lifecycle_snapshots_survive_reopen_and_keep_guards(
    tmp_path: Path, state: OpportunityState
) -> None:
    path = tmp_path / "mine.db"
    original = snapshots()[state]
    repo = open_local_repositories(path).opportunities
    assert repo.get(original.reference) is None
    repo.save(OpportunitySave(original, None))
    restored = open_local_repositories(path).opportunities.get(original.reference)
    assert restored is not None and restored.revision == 1 and restored.value == original
    assert isinstance(restored.value.state, OpportunityState)
    assert restored.value.history == original.history
    if state != OpportunityState.DISCOVERED:
        with pytest.raises(DomainError):
            restored.value.normalize()
    if state == OpportunityState.WAITING_FOR_BUDGET:
        assert restored.value.waiting_request is not None
        assert restored.value.task is not None and restored.value.task.waiting_since == instant()
    if state == OpportunityState.PAID:
        assert restored.value.verified_revenue == usd("85")
    else:
        assert restored.value.verified_revenue == usd("0")


def test_required_opportunity_queries_and_provenance(tmp_path: Path) -> None:
    repo = open_local_repositories(tmp_path / "mine.db").opportunities
    states = [
        OpportunityState.ELIGIBLE,
        OpportunityState.WAITING_FOR_BUDGET,
        OpportunityState.READY_FOR_HUMAN_REVIEW,
        OpportunityState.ACCEPTED,
        OpportunityState.PAID,
    ]
    for state in states:
        original = snapshots(state.value)
        repo.save_observation(
            OpportunityObservation(
                original[OpportunityState.DISCOVERED],
                Reference("source"),
                "Requirements",
                instant(),
                True,
                None,
            )
        )
        repo.save(OpportunitySave(original[state], None))
    assert [op.state for op in repo.list_eligible()] == [OpportunityState.ELIGIBLE]
    assert [op.state for op in repo.list_waiting_for_budget()] == [
        OpportunityState.WAITING_FOR_BUDGET
    ]
    assert [op.state for op in repo.submissions_awaiting_review()] == [
        OpportunityState.READY_FOR_HUMAN_REVIEW
    ]
    assert [op.state for op in repo.accepted_but_unpaid()] == [OpportunityState.ACCEPTED]
    assert len(repo.list_by_source(Reference("source"))) == 5
    assert repo.list_by_source(Reference("other")) == ()
    assert repo.verified_revenue("USD") == usd("85")
    assert repo.verified_revenue("EUR").amount == 0
    observation = repo.get_observation(Reference("eligible"))
    assert observation is not None
    repo.save_observation(observation)
    with pytest.raises(PortError) as error:
        repo.save_observation(replace(observation, source_reference=Reference("changed")))
    assert error.value.code == PortErrorCode.CONFLICT


def test_score_sort_is_exact_stable_and_excludes_unscored(tmp_path: Path) -> None:
    repo = open_local_repositories(tmp_path / "mine.db").opportunities
    for reference, score in [
        ("z", "75.00000000000000000001"),
        ("b", "75"),
        ("a", "75"),
        ("zero", "0"),
    ]:
        repo.save(OpportunitySave(snapshots(reference, score)[OpportunityState.SCORED], None))
    repo.save(OpportunitySave(snapshots("unscored")[OpportunityState.ELIGIBLE], None))
    with localcontext() as context:
        context.prec = 2
        assert [op.reference.value for op in repo.list_highest_scoring(3)] == ["z", "a", "b"]
    assert len(repo.list_highest_scoring()) == 4
    with pytest.raises(ValueError):
        repo.list_highest_scoring(0)


def test_evaluation_history_and_immutable_identity(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    repo = open_local_repositories(path).evaluations
    op = snapshots()[OpportunityState.ELIGIBLE]
    assert op.eligibility is not None
    assessment = ScoringAssessment(
        EconomicAssessment(op.potential_reward, economic_inputs()),
        scoring_signals(),
        scoring_policy(),
    )
    first = EvaluationRecord(
        Reference("a"),
        op.reference,
        op.eligibility,
        assessment.economics.expected_net_value,
        assessment.score,
        instant(),
        (),
        assessment,
    )
    later = replace(first, reference=Reference("b"), evaluated_at=instant() + timedelta(seconds=1))
    repo.save(later)
    repo.save(first)
    repo.save(first)
    restored = open_local_repositories(path).evaluations
    assert restored.for_opportunity(op.reference) == (first, later)
    assert restored.get(first.reference) == first
    with pytest.raises(PortError):
        restored.save(replace(first, evidence=(Reference("changed"),)))


def test_complete_execution_journal_roundtrip_and_version_identity(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    repo = open_local_repositories(path).executions
    op = snapshots()[OpportunityState.READY_FOR_HUMAN_REVIEW]
    assert op.execution is not None and op.deliverable is not None and op.qa is not None
    execution, deliverable, qa = op.execution, op.deliverable, op.qa
    later = replace(
        execution, reference=Reference("later"), started_at=instant() + timedelta(seconds=1)
    )
    repo.save(later)
    repo.save(execution)
    repo.save(execution)
    repo.save_deliverable(deliverable)
    second = replace(deliverable, version=2, content_reference=Reference("v2"))
    repo.save_deliverable(second)
    repo.save_qa(qa)
    content = ReferencedText(deliverable.content_reference, "Unicode: nghiên cứu\nData")
    repo.save_content(content)
    request = ExecuteTaskRequest(
        op.reference,
        Reference("ledger"),
        Reference("operation"),
        execution.reference,
        deliverable.reference,
        1,
        usd("1"),
    )
    repo.save_work_request(request)
    response = AIResponse(
        request.operation_reference,
        DeliverableDraft(content.text, (Reference("evidence"),)),
        None,
        Reference("response"),
    )
    repo.save_work_response(execution.reference, response)
    restored = open_local_repositories(path).executions
    assert restored.for_opportunity(op.reference) == (execution, later)
    assert restored.get(execution.reference) == execution
    assert restored.get_deliverable(deliverable.reference, 1) == deliverable
    assert restored.get_deliverable(deliverable.reference, 2) == second
    assert restored.get_qa(deliverable.reference, 1) == qa
    assert restored.get_content(content.reference) == content
    assert restored.get_work_request(execution.reference) == request
    assert restored.get_work_response(execution.reference) == response
    with pytest.raises(PortError):
        restored.save_qa(replace(qa, status=QAStatus.FAILED))
    with pytest.raises(PortError):
        restored.save_content(replace(content, text="changed"))
    with pytest.raises(PortError):
        restored.save_work_request(replace(request, estimated_cost=usd("2")))
    assert restored.get(Reference("missing")) is None
    assert restored.get_deliverable(deliverable.reference, 3) is None


def submission_request() -> SubmissionRequest:
    op = snapshots()[OpportunityState.SUBMITTED]
    sub = op.submission
    assert sub is not None
    return SubmissionRequest(
        sub.reference,
        sub.deliverable,
        sub.qa,
        sub.approval,
        sub.target,
        ReferencedText(sub.deliverable.content_reference, "Report"),
    )


def test_submission_claim_is_single_owner_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    first, second = open_local_repositories(path), open_local_repositories(path)
    barrier = Barrier(2)
    request = submission_request()

    def claim(index: int) -> bool:
        barrier.wait(timeout=10)
        return (first, second)[index].submissions.claim_request(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(claim, [0, 1])) == [False, True]
    reopened = open_local_repositories(path).submissions
    assert not reopened.claim_request(request)
    assert reopened.get_request(request.reference) == request
    with pytest.raises(PortError):
        reopened.claim_request(replace(request, content=replace(request.content, text="changed")))
    with pytest.raises(PortError):
        reopened.claim_request(replace(request, reference=Reference("other")))
    saved = replace(request, reference=Reference("saved"))
    with pytest.raises(PortError):
        reopened.save_request(saved)
    separate = open_local_repositories(tmp_path / "saved.db").submissions
    separate.save_request(saved)
    assert not separate.claim_request(saved)


def test_submission_receipts_attempts_outcomes_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    repo = open_local_repositories(path).submissions
    op = snapshots()[OpportunityState.ACCEPTED]
    assert op.submission is not None and op.outcome is not None
    sub = op.submission
    pending = SubmissionResult(
        sub.reference, SubmissionAttemptStatus.UNKNOWN, instant(), None, "Pending"
    )
    confirmed = SubmissionResult(
        sub.reference,
        SubmissionAttemptStatus.CONFIRMED,
        instant() + timedelta(seconds=1),
        sub,
        "Confirmed",
    )
    repo.record_attempt(confirmed)
    repo.record_attempt(pending)
    repo.record_attempt(
        replace(pending, observed_at=instant().astimezone(timezone(timedelta(hours=7))))
    )
    repo.save(sub)
    repo.save(sub)
    repo.save_outcome(op.outcome)
    restored = open_local_repositories(path).submissions
    assert restored.attempts_for(sub.reference) == (pending, confirmed)
    assert restored.get(sub.reference) == sub
    assert restored.get_outcome(sub.reference) == op.outcome
    with pytest.raises(PortError):
        restored.save(replace(sub, receipt=Reference("different")))
    with pytest.raises(PortError):
        restored.save_outcome(replace(op.outcome, evidence=Reference("different")))


def test_opportunity_compare_and_swap_rejects_stale_writers(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    repo = open_local_repositories(path).opportunities
    op = snapshots()[OpportunityState.DISCOVERED]
    saved = repo.save(OpportunitySave(op, None))
    other = open_local_repositories(path).opportunities
    assert other.get(op.reference) == saved
    assert repo.save(OpportunitySave(op.normalize(), 1)).revision == 2
    for stale in (None, 1):
        with pytest.raises(PortError) as error:
            other.save(OpportunitySave(op, stale))
        assert error.value.code == PortErrorCode.CONFLICT
    restored = other.get(op.reference)
    assert restored is not None and restored.value.state == OpportunityState.NORMALIZED


def test_budget_commits_are_atomic_under_competing_authorizations(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    repos = [open_local_repositories(path).ledger, open_local_repositories(path).ledger]
    initial = Budget(BudgetPolicy(usd("100"), usd("100"), usd("100"), usd("100")))
    reference = Reference("ledger")
    repos[0].commit(BudgetCommit(reference, initial, None, None))
    barrier = Barrier(2)

    def reserve(index: int) -> bool:
        previous = repos[index].get(reference)
        assert previous is not None
        decision = previous.value.authorize(
            usd("70"),
            CostCategory.AI,
            CostContext(Reference(str(index)), OperationType.SCORING, instant()),
        )
        barrier.wait(timeout=10)
        try:
            repos[index].commit(
                BudgetCommit(reference, decision.budget, previous.revision, decision)
            )
            return True
        except PortError as error:
            assert error.code == PortErrorCode.CONFLICT
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(reserve, [0, 1])) == [False, True]
    restored = repos[0].get(reference)
    assert restored is not None and restored.revision == 2
    assert restored.value.ai_committed(instant()) == usd("70")
    assert len(repos[0].history(reference)) == 2


def test_audit_insert_failure_rolls_back_budget_update(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    repo = open_local_repositories(path).ledger
    reference = Reference("ledger")
    original = repo.commit(BudgetCommit(reference, budget(), None, None))
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TRIGGER fail_audit BEFORE INSERT ON snapshots
            WHEN NEW.kind = 'budget_audit' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    decision = original.value.authorize(
        usd("1"), CostCategory.AI, CostContext(Reference("op"), OperationType.SCORING, instant())
    )
    with pytest.raises(PortError) as error:
        repo.commit(BudgetCommit(reference, decision.budget, original.revision, decision))
    assert error.value.code == PortErrorCode.UNAVAILABLE
    assert repo.get(reference) == original
    assert len(repo.history(reference)) == 1


def test_budget_state_actual_cost_periods_timezone_and_monthly_totals(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    repo = open_local_repositories(path).ledger
    reference = Reference("ledger")
    initial = budget().with_policy(
        replace(budget().policy, calendar_timezone=timezone(timedelta(hours=7)))
    )
    snapshot = repo.commit(BudgetCommit(reference, initial, None, None))
    context = CostContext(Reference("reserved"), OperationType.SCORING, instant())
    decision = snapshot.value.authorize(usd("2"), CostCategory.AI, context)
    snapshot = repo.commit(BudgetCommit(reference, decision.budget, snapshot.revision, decision))
    for operation, amount, category, occurred in [
        ("a", "0.1", CostCategory.AI, datetime(2026, 9, 30, 16, 59, 59, tzinfo=UTC)),
        ("b", "0.2", CostCategory.TOOL, datetime(2026, 9, 30, 17, tzinfo=UTC)),
        ("c", "0.3", CostCategory.INFRASTRUCTURE, datetime(2026, 10, 31, 16, 59, 59, tzinfo=UTC)),
        ("d", "0.4", CostCategory.TRANSACTION, datetime(2026, 10, 31, 17, tzinfo=UTC)),
    ]:
        recorded = snapshot.value.record(
            usd(amount),
            category,
            CostContext(Reference(operation), OperationType.SCORING, occurred),
        )
        snapshot = repo.commit(
            BudgetCommit(reference, recorded.budget, snapshot.revision, recorded)
        )
    restored = open_local_repositories(path).ledger
    assert restored.get(reference) == snapshot
    assert restored.monthly_cost(reference, 2026, 10) == usd("0.5")
    assert restored.monthly_cost(reference, 2026, 9, CostCategory.AI) == usd("0.1")
    assert restored.monthly_cost(reference, 2026, 10, CostCategory.AI) == usd("0")
    assert restored.monthly_cost(Reference("missing"), 2026, 10) is None
    start, end = datetime(2026, 9, 30, 17, tzinfo=UTC), datetime(2026, 10, 31, 17, tzinfo=UTC)
    assert [
        record.cost.reference.value for record in restored.costs_by_period(reference, start, end)
    ] == ["b", "c"]
    assert [
        record.cost.reference.value
        for record in restored.costs_by_period(reference, start, end, CostCategory.TOOL)
    ] == ["b"]
    assert snapshot.value.outstanding == (decision.authorization,)
    released = snapshot.value.release(context.operation_reference)
    final = restored.commit(BudgetCommit(reference, released, snapshot.revision, None))
    assert not final.value.outstanding
    assert open_local_repositories(path).ledger.get(reference) == final
    assert len(restored.history(reference)) == 7
    with pytest.raises(ValueError):
        restored.costs_by_period(reference, end, start)


def test_corrupt_and_unsupported_snapshots_fail_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "mine.db"
    repo = open_local_repositories(path).opportunities
    original = snapshots()[OpportunityState.PAID]
    repo.save(OpportunitySave(original, None))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE snapshots SET payload = '{}' WHERE kind = 'opportunity'")
    with pytest.raises(PortError) as error:
        repo.get(original.reference)
    assert error.value.code == PortErrorCode.INVALID_RESPONSE
    for payload, expected_code in [
        ('{"version":999,"value":null}', PortErrorCode.UNSUPPORTED),
        ('{"version":1,"value":{"type":"os.system","fields":{}}}', PortErrorCode.INVALID_RESPONSE),
    ]:
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE snapshots SET payload = ?, digest = ?",
                (payload, hashlib.sha256(payload.encode()).hexdigest()),
            )
        with pytest.raises(PortError) as error:
            repo.get(original.reference)
        assert error.value.code == expected_code


def test_codec_rejects_wrong_types_and_recomputes_derived_values() -> None:
    codec = SnapshotCodec()
    assessment = EconomicAssessment(
        snapshots()[OpportunityState.DISCOVERED].potential_reward, economic_inputs()
    )
    payload = json.loads(codec.dumps(assessment))
    payload["value"]["fields"]["expected_gross_value"]["fields"]["amount"] = {"decimal": "999"}
    with pytest.raises(PortError):
        codec.loads(json.dumps(payload), EconomicAssessment)
    payload = json.loads(codec.dumps(Reference("id")))
    payload["value"]["fields"]["value"] = 5
    with pytest.raises(PortError):
        codec.loads(json.dumps(payload), Reference)


def test_unknown_database_version_and_unavailable_path(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(PortError) as error:
        SQLiteDatabase(path)
    assert error.value.code == PortErrorCode.UNSUPPORTED
    with pytest.raises(PortError) as error:
        SQLiteDatabase(tmp_path / "missing" / "mine.db")
    assert error.value.code == PortErrorCode.UNAVAILABLE


def test_locked_database_translates_error_without_partial_write(tmp_path: Path) -> None:
    path = tmp_path / "locked.db"
    database = SQLiteDatabase(path, timeout_seconds=0)
    repo = SQLiteCostLedgerRepository(database)
    reference = Reference("ledger")
    with database.transaction(write=True):
        with pytest.raises(PortError) as error:
            repo.commit(BudgetCommit(reference, budget(), None, None))
        assert error.value.code == PortErrorCode.UNAVAILABLE
    assert repo.get(reference) is None


def test_budget_wait_can_resume_using_restored_domain_objects(tmp_path: Path) -> None:
    path = tmp_path / "waiting.db"
    local = open_local_repositories(path)
    waiting = snapshots()[OpportunityState.WAITING_FOR_BUDGET]
    local.opportunities.save(OpportunitySave(waiting, None))
    empty = Budget(BudgetPolicy(usd("0"), usd("0"), usd("10"), usd("10")))
    request = waiting.waiting_request
    assert request is not None
    denied = empty.authorize(request.estimated_cost, request.category, request.context)
    local.ledger.commit(BudgetCommit(Reference("ledger"), empty, None, denied))
    local = open_local_repositories(path)
    restored = local.opportunities.get(waiting.reference)
    ledger = local.ledger.get(Reference("ledger"))
    assert restored is not None and ledger is not None
    assert local.ledger.history(Reference("ledger"))[0].value.audit_event == denied
    funded = ledger.value.with_policy(budget().policy)
    ledger = local.ledger.commit(BudgetCommit(Reference("ledger"), funded, ledger.revision, None))
    task = restored.value.task
    assert task is not None
    at = instant() + timedelta(seconds=1)
    assessment = ResumeAssessment(
        waiting.reference,
        at,
        True,
        task.deadline,
        waiting.eligibility,
        waiting.expected_value,
        waiting.score,
    )
    result = restored.value.resume_after_budget(assessment, ledger.value, at)
    assert result.opportunity.state == OpportunityState.PLANNED
    assert result.decision is not None
    local.ledger.commit(
        BudgetCommit(Reference("ledger"), result.budget, ledger.revision, result.decision)
    )
    local.opportunities.save(OpportunitySave(result.opportunity, restored.revision))
    reopened = open_local_repositories(path)
    assert not reopened.opportunities.list_waiting_for_budget()
    saved = reopened.ledger.get(Reference("ledger"))
    assert saved is not None and saved.value.ai_committed(at) == usd("1")


def test_fixed_timezone_preserves_fractional_offset() -> None:
    codec = SnapshotCodec()
    original = budget().with_policy(
        replace(
            budget().policy,
            calendar_timezone=timezone(timedelta(hours=7, microseconds=123)),
        )
    )
    assert codec.loads(codec.dumps(original), Budget) == original
