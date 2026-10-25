"""New B1 acceptance criteria, not reproductions of a pre-existing runtime defect."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest

from agentmine.application.contracts.data import (
    DataArtifact,
    DataColumn,
    DataFormat,
    DataResult,
    DataSource,
)
from agentmine.application.contracts.opportunities import OpportunityObservation, OpportunityStatus
from agentmine.application.contracts.records import BudgetCommit, OpportunitySave, Versioned
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    InputEvidence,
    RecoveryReason,
    WorkerResult,
    WorkerRunFinish,
    WorkerRunStart,
    WorkSpecification,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.runtime import WorkerRuntimeRepository
from agentmine.domain.budget import Budget, BudgetPolicy
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import CostCategory, ExpectedValue, Reward
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import Eligibility, EligibilityStatus, Task, TaskType
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository


def money(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


@dataclass
class Case:
    database: SQLiteDatabase
    runtime: WorkerRuntimeRepository
    start: WorkerRunStart


@pytest.fixture
def case(tmp_path: Path) -> Case:
    database = SQLiteDatabase(tmp_path / "runtime.sqlite3")
    runtime = SQLiteWorkerRuntimeRepository(database)
    now = datetime(2026, 10, 25, tzinfo=UTC)
    discovered = Opportunity(Reference("op"), "Process approved data", Reward(money("10")))
    task = Task(
        Reference("task"),
        discovered.reference,
        TaskType.DATA_PROCESSING,
        "Normalize",
        now + timedelta(days=1),
    )
    op = (
        discovered.normalize()
        .check_eligibility()
        .assess_eligibility(
            Eligibility(EligibilityStatus.ELIGIBLE, "Explicit synthetic acceptance facts")
        )
        .evaluate(ExpectedValue(money("5"), "Subjective test forecast"))
        .assign_score(Decimal("70"))
        .plan(task)
    )
    opportunities = SQLiteOpportunityRepository(database)
    opportunities.save_observation(
        OpportunityObservation(
            discovered, Reference("source:1"), "Approved terms", now, True, task.deadline
        )
    )
    snapshot = opportunities.save(OpportunitySave(op, None))
    source = DataSource(
        Reference("input"), "operator:captured.json", now, DataFormat.JSON, '[{"name":"A"}]'
    )
    specification = WorkSpecification(
        Reference("spec"),
        task,
        Reference("ledger"),
        Reference("operator"),
        now,
        OpportunityStatus(
            op.reference,
            Reference("source:1"),
            now,
            True,
            task.deadline,
            True,
            Reference("source:version1"),
            "Approved terms",
        ),
        (source,),
        (InputEvidence(source.reference, Reference("sha256:" + source.digest)),),
        (DataColumn("name", ("name",)),),
    )
    runtime.save_specification(specification)
    binding = ExecutionBinding(
        specification.reference,
        Reference("execution"),
        Reference("operation"),
        Reference("deliverable"),
    )
    empty = Budget(BudgetPolicy(money("10"), money("5"), money("3"), money("1")))
    decision = empty.authorize(
        money("0"),
        CostCategory.AI,
        CostContext(
            binding.operation_reference,
            OperationType.TASK_EXECUTION,
            now,
            task.reference,
            op.reference,
        ),
    )
    ledger = SQLiteCostLedgerRepository(database).commit(
        BudgetCommit(specification.ledger_reference, decision.budget, None, decision)
    )
    return Case(database, runtime, WorkerRunStart(specification, binding, snapshot, ledger, now))


def result(case: Case) -> WorkerResult:
    run = case.start.run
    return WorkerResult(
        run,
        DataResult(
            run.binding.execution_reference,
            (),
            (),
            (DataArtifact("validation.json", "application/json", '{"valid":true}'),),
            None,
            ("actual_cost_unknown",),
        ),
    )


def current(case: Case) -> Versioned[Opportunity]:
    value = SQLiteOpportunityRepository(case.database).get(
        case.start.specification.task.opportunity_reference
    )
    assert value is not None
    return value


def storage_rows(case: Case) -> tuple[tuple[object, ...], ...]:
    with case.database.transaction() as connection:
        return tuple(
            tuple(row)
            for row in connection.execute("SELECT * FROM snapshots ORDER BY kind,id").fetchall()
        )


def test_specification_reload_and_immutable_conflict(case: Case) -> None:
    spec = case.start.specification
    reopened: WorkerRuntimeRepository = SQLiteWorkerRuntimeRepository(
        SQLiteDatabase(case.database.path)
    )
    assert reopened.get_specification(spec.reference) == spec
    assert reopened.save_specification(spec) is False
    with pytest.raises(PortError) as error:
        reopened.save_specification(replace(spec, actor=Reference("different")))
    assert error.value.code == PortErrorCode.CONFLICT


def test_same_start_is_idempotent_and_no_ledger_change(case: Case) -> None:
    assert case.runtime.start(case.start) is True
    revision = current(case).revision
    assert case.runtime.start(case.start) is False
    assert current(case).revision == revision
    assert (
        SQLiteCostLedgerRepository(case.database).get(Reference("ledger"))
        == case.start.ledger_snapshot
    )
    assert case.runtime.get_run(Reference("execution")) == case.start.run
    view = case.runtime.inspect(Reference("execution"))
    assert view is not None and view.reason == RecoveryReason.RESULT_MISSING
    assert case.runtime.incomplete() == (view,)


def test_concurrent_different_id_first_owner(case: Case) -> None:
    other = replace(
        case.start, binding=replace(case.start.binding, execution_reference=Reference("other"))
    )

    ready = Barrier(2)

    def start(command: WorkerRunStart) -> bool:
        try:
            repository = SQLiteWorkerRuntimeRepository(SQLiteDatabase(case.database.path))
            ready.wait(timeout=10)
            return repository.start(command)
        except PortError as error:
            assert error.code == PortErrorCode.CONFLICT
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(start, (case.start, other))) == [False, True]
    assert len(case.runtime.incomplete()) == 1


def test_stale_opportunity_and_ledger_rejected(case: Case) -> None:
    old = current(case)
    SQLiteOpportunityRepository(case.database).save(OpportunitySave(old.value, old.revision))
    with pytest.raises(PortError):
        case.runtime.start(case.start)
    assert case.runtime.get_run(Reference("execution")) is None
    fresh = replace(case.start, opportunity_snapshot=current(case))
    ledger = case.start.ledger_snapshot
    SQLiteCostLedgerRepository(case.database).commit(
        BudgetCommit(Reference("ledger"), ledger.value, ledger.revision, None)
    )
    with pytest.raises(PortError):
        case.runtime.start(fresh)
    assert case.runtime.incomplete() == ()


@pytest.mark.parametrize(
    "failed_kind", ["runtime_owner", "runtime_run", "execution", "data_plan", "opportunity"]
)
def test_start_transaction_rolls_back_every_write(case: Case, failed_kind: str) -> None:
    original = case.database.write
    before_rows = storage_rows(case)

    def write(*args: object, **kwargs: object) -> None:
        # Inject an ordinary storage error after the named write, including the last.
        original(*args, **kwargs)  # type: ignore[arg-type]
        if args[1] == failed_kind:
            raise RuntimeError("injected failure")

    with patch.object(case.database, "write", side_effect=write), pytest.raises(RuntimeError):
        case.runtime.start(case.start)
    assert current(case) == case.start.opportunity_snapshot
    assert storage_rows(case) == before_rows
    assert case.runtime.get_run(Reference("execution")) is None
    assert case.runtime.start(case.start) is True  # No leaked task owner or plan.


def test_result_restart_and_finish_are_idempotent(case: Case) -> None:
    case.runtime.start(case.start)
    retained = result(case)
    assert case.runtime.save_result(retained) is True
    reopened = SQLiteWorkerRuntimeRepository(SQLiteDatabase(case.database.path))
    view = reopened.inspect(Reference("execution"))
    assert view is not None and view.result == retained.result
    assert view.reason == RecoveryReason.FINISH_PENDING
    assert reopened.save_result(retained) is False
    finish = WorkerRunFinish(retained, current(case))
    assert reopened.finish(finish) is True
    assert reopened.finish(finish) is False
    assert current(case).value.state == OpportunityState.QA_PENDING
    assert reopened.incomplete() == ()
    completed = reopened.inspect(Reference("execution"))
    assert completed is not None and completed.reason == RecoveryReason.NONE
    assert current(case).value.verified_revenue == money("0")
    with pytest.raises(PortError):
        reopened.save_result(
            replace(retained, result=replace(retained.result, warnings=("changed",)))
        )


@pytest.mark.parametrize("failed_kind", ["content", "deliverable", "opportunity", "runtime_finish"])
def test_finish_atomic_rollback(case: Case, failed_kind: str) -> None:
    case.runtime.start(case.start)
    retained = result(case)
    case.runtime.save_result(retained)
    before = current(case)
    before_rows = storage_rows(case)
    finish = WorkerRunFinish(retained, before)
    original = case.database.write

    def write(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        if args[1] == failed_kind:
            raise RuntimeError("injected failure")

    with patch.object(case.database, "write", side_effect=write), pytest.raises(RuntimeError):
        case.runtime.finish(finish)
    assert current(case) == before
    assert storage_rows(case) == before_rows
    assert case.runtime.finish(finish) is True


def test_finish_stale_revision_does_not_publish(case: Case) -> None:
    case.runtime.start(case.start)
    retained = result(case)
    case.runtime.save_result(retained)
    finish = WorkerRunFinish(retained, current(case))
    old = current(case)
    SQLiteOpportunityRepository(case.database).save(OpportunitySave(old.value, old.revision))
    with pytest.raises(PortError):
        case.runtime.finish(finish)
    assert current(case).value.state == OpportunityState.IN_PROGRESS


def test_digest_identity_and_unsupported_capabilities(case: Case) -> None:
    spec = case.start.specification
    with pytest.raises(DomainError):
        replace(
            spec,
            input_evidence=(InputEvidence(Reference("input"), Reference("sha256:" + "0" * 64)),),
        )
    with pytest.raises(DomainError):
        replace(
            spec,
            input_evidence=(
                InputEvidence(Reference("other"), spec.input_evidence[0].content_reference),
            ),
        )
    with pytest.raises(DomainError):
        replace(spec, task=replace(spec.task, task_type=TaskType.RESEARCH))
    with pytest.raises(DomainError):
        replace(spec, columns=(replace(spec.columns[0], semantic_reason="Interpret"),))
    with pytest.raises(DomainError):
        replace(
            case.start,
            binding=replace(case.start.binding, specification_reference=Reference("other")),
        )


def test_unpersisted_authorization_cannot_start(case: Case) -> None:
    # A forged caller budget is rejected against the authoritative snapshot.
    ledger = case.start.ledger_snapshot
    forged = replace(
        case.start,
        ledger_snapshot=Versioned(
            ledger.value.with_requested_mode(case.start.run.plan.execution.mode),
            ledger.revision + 1,
        ),
    )
    with pytest.raises(PortError):
        case.runtime.start(forged)
    assert current(case).value.state == OpportunityState.PLANNED


def test_start_rejects_orphaned_result_identity(case: Case) -> None:
    # Runtime must not adopt an unrelated journal result under a fresh first-run ID.
    from agentmine.infrastructure.sqlite.data import SQLiteDataJournal

    SQLiteDataJournal(case.database).save_result(result(case).result)
    with pytest.raises(PortError):
        case.runtime.start(case.start)
    assert current(case) == case.start.opportunity_snapshot


def test_first_start_requires_source_provenance_identity(case: Case) -> None:
    original = case.start.specification
    changed = replace(
        original,
        reference=Reference("other-spec"),
        source_context=replace(original.source_context, source_reference=Reference("other-source")),
    )
    with pytest.raises(PortError):
        case.runtime.save_specification(changed)


def test_result_requires_retained_run_and_finish_requires_result(case: Case) -> None:
    retained = result(case)
    with pytest.raises(PortError):
        case.runtime.save_result(retained)
    case.runtime.start(case.start)
    with pytest.raises(PortError):
        case.runtime.finish(WorkerRunFinish(retained, current(case)))
    assert current(case).value.state == OpportunityState.IN_PROGRESS


def test_historical_finish_does_not_rewind_lifecycle(case: Case) -> None:
    from agentmine.domain.work import QAResult, QAStatus

    case.runtime.start(case.start)
    retained = result(case)
    case.runtime.save_result(retained)
    finish = WorkerRunFinish(retained, current(case))
    case.runtime.finish(finish)
    old = current(case)
    updated = old.value.review_qa(
        QAResult(finish.deliverable, QAStatus.PASSED, "Explicit test QA assertion")
    )
    saved = SQLiteOpportunityRepository(case.database).save(OpportunitySave(updated, old.revision))
    assert case.runtime.finish(finish) is False
    assert current(case) == saved


@pytest.mark.parametrize(
    "invalid_fields",
    [
        {"min_records": True},
        {"max_records": 1001},
        {"unique_by": ("absent",)},
        {"columns": ()},
        {"sources": ()},
        {"input_evidence": ()},
    ],
)
def test_specification_rejects_invalid_scope(case: Case, invalid_fields: dict[str, object]) -> None:
    with pytest.raises(DomainError):
        replace(case.start.specification, **invalid_fields)  # type: ignore[arg-type]


def test_snapshot_context_and_authorization_are_not_guessed(case: Case) -> None:
    spec = case.start.specification
    for source in (
        replace(spec.source_context, terms_reference=None),
        replace(spec.source_context, requirements=None),
        replace(spec.source_context, is_open=None),
    ):
        with pytest.raises(DomainError):
            replace(spec, source_context=source)
    with pytest.raises(DomainError):
        replace(
            case.start,
            ledger_snapshot=Versioned(Budget(case.start.ledger_snapshot.value.policy), 1),
        )


def test_missing_inspection_is_not_an_invented_run(case: Case) -> None:
    assert case.runtime.inspect(Reference("missing")) is None
    assert case.runtime.get_run(Reference("missing")) is None
    assert case.runtime.get_specification(Reference("missing")) is None


def test_concurrent_same_id_start_and_finish_are_readback(case: Case) -> None:
    ready = Barrier(2)

    def start() -> bool:
        repository = SQLiteWorkerRuntimeRepository(SQLiteDatabase(case.database.path))
        ready.wait(timeout=10)
        return repository.start(case.start)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start) for _ in range(2)]
        assert sorted(future.result() for future in futures) == [False, True]
    retained = result(case)
    case.runtime.save_result(retained)
    command = WorkerRunFinish(retained, current(case))
    ready = Barrier(2)

    def finish() -> bool:
        repository = SQLiteWorkerRuntimeRepository(SQLiteDatabase(case.database.path))
        ready.wait(timeout=10)
        return repository.finish(command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish) for _ in range(2)]
        assert sorted(future.result() for future in futures) == [False, True]


def test_same_execution_changed_binding_conflicts(case: Case) -> None:
    case.runtime.start(case.start)
    changed = replace(
        case.start,
        binding=replace(case.start.binding, deliverable_reference=Reference("different")),
    )
    with pytest.raises(PortError):
        case.runtime.start(changed)


def test_result_write_failure_rolls_back_and_reopens(case: Case) -> None:
    import sqlite3

    case.runtime.start(case.start)
    before = storage_rows(case)
    original = case.database.write

    def write(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        raise sqlite3.OperationalError("simulated disk failure")

    with patch.object(case.database, "write", side_effect=write), pytest.raises(PortError) as error:
        case.runtime.save_result(result(case))
    assert error.value.code == PortErrorCode.UNAVAILABLE
    assert storage_rows(case) == before
    reopened = SQLiteWorkerRuntimeRepository(SQLiteDatabase(case.database.path))
    assert reopened.save_result(result(case)) is True


def test_result_cannot_change_execution_identity(case: Case) -> None:
    retained = result(case)
    with pytest.raises(DomainError):
        replace(retained, result=replace(retained.result, execution_reference=Reference("other")))


def test_numeric_constraint_types_and_artifact_inventory(case: Case) -> None:
    from agentmine.application.contracts.data import Comparison, RowConstraint

    with pytest.raises(DomainError):
        replace(
            case.start.specification,
            constraints=(RowConstraint("name", Comparison.LESS_OR_EQUAL, "name"),),
        )
    retained = result(case)
    with pytest.raises(DomainError):
        replace(
            retained,
            result=replace(
                retained.result, artifacts=(DataArtifact("../unsafe", "application/json", "{}"),)
            ),
        )


def test_scout_only_zero_authorization_remains_supported(case: Case) -> None:
    from agentmine.domain.budget import OperatingMode

    old = case.start.ledger_snapshot
    budget = Budget(old.value.policy, OperatingMode.SCOUT_ONLY)
    request = old.value.outstanding[0].request
    decision = budget.authorize(request.estimated_cost, request.category, request.context)
    ledger = SQLiteCostLedgerRepository(case.database).commit(
        BudgetCommit(Reference("ledger"), decision.budget, old.revision, decision)
    )
    command = replace(case.start, ledger_snapshot=ledger)
    assert command.run.plan.execution.mode == OperatingMode.SCOUT_ONLY
    assert case.runtime.start(command) is True


def test_runtime_record_references_existing_plan_without_copying_sources(case: Case) -> None:
    case.runtime.start(case.start)
    stored = case.database.get("runtime_run", Reference("execution").value, ExecutionBinding)
    assert stored is not None and stored.value == case.start.binding
    assert case.runtime.get_run(Reference("execution")) == case.start.run


def test_paid_authorization_is_outside_deterministic_foundation(case: Case) -> None:
    budget = Budget(case.start.ledger_snapshot.value.policy)
    request = case.start.ledger_snapshot.value.outstanding[0].request
    decision = budget.authorize(money("1"), request.category, request.context)
    with pytest.raises(DomainError):
        replace(case.start, ledger_snapshot=Versioned(decision.budget, 1))


def test_incomplete_inspection_exposes_changed_phase_without_repair(case: Case) -> None:
    case.runtime.start(case.start)
    old = current(case)
    context = case.start.ledger_snapshot.value.outstanding[0].request.context
    denied = Budget(BudgetPolicy(money("0"), money("0"), money("3"), money("1"))).authorize(
        money("1"),
        CostCategory.AI,
        replace(context, operation_reference=Reference("other-operation")),
    )
    waiting = old.value.wait_for_budget(denied)
    saved = SQLiteOpportunityRepository(case.database).save(OpportunitySave(waiting, old.revision))
    view = case.runtime.inspect(Reference("execution"))
    assert view is not None and view.reason == RecoveryReason.STATE_CHANGED
    assert case.runtime.incomplete() == (view,)
    assert current(case) == saved
