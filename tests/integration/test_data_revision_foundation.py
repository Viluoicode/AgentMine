"""Revision foundation: real SQLite/parent worker/QA; test-only source and clock."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

import pytest
from test_operational_deliverable_qa import execute_data, qa
from test_runtime_operator_cli import CLI, cli

from agentmine.application.contracts.data_revision import (
    DataRevisionApproval,
    DataRevisionRequest,
    RevisionAllocation,
    RevisionFinish,
    RevisionStart,
    RevisionTrigger,
)
from agentmine.application.contracts.runtime import ExecutionBinding, WorkerResult
from agentmine.application.workers.data import DataWorker
from agentmine.domain.errors import DomainError
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.data_revision import SQLiteRevisionRuntimeRepository
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

__all__ = ["cli"]


def request(
    cli: CLI,
    suffix: str = "2",
    *,
    trigger: RevisionTrigger = RevisionTrigger.QA,
    trigger_reference: str = "qa-001",
) -> DataRevisionRequest:
    run = cli.world.runtime().get_run(Reference("cli-exec"))
    assert run is not None and run.specification.execution_evidence is not None
    parent = SQLiteExecutionRepository(cli.world.database).get_deliverable(
        Reference("cli-deliverable"), 1
    )
    snapshot = SQLiteOpportunityRepository(cli.world.database).get(Reference("op"))
    assert parent is not None and snapshot is not None
    evidence = run.specification.execution_evidence
    spec = replace(
        run.specification,
        reference=Reference("spec-" + suffix),
        execution_evidence=replace(
            evidence, evaluation=replace(evidence.evaluation, reference=Reference("eval-" + suffix))
        ),
    )
    return DataRevisionRequest(
        Reference("revision-" + suffix),
        run,
        parent,
        snapshot,
        trigger,
        Reference(trigger_reference),
        spec,
        "Repair approved names",
    )


def setup(cli: CLI) -> tuple[SQLiteRevisionRuntimeRepository, DataRevisionRequest]:
    execute_data(cli, missing=True)
    assert qa(cli)[1]["qa_outcome"] == "NEEDS_REVISION"
    return SQLiteRevisionRuntimeRepository(cli.world.database), request(cli)


def approve(repo: SQLiteRevisionRuntimeRepository, req: DataRevisionRequest) -> RevisionAllocation:
    return repo.approve(
        req.reference,
        DataRevisionApproval(
            req.reference, req.specification.actor, req.specification.approved_at, True
        ),
        ExecutionBinding(
            req.specification.reference,
            Reference(req.reference.value + ":exec"),
            Reference(req.reference.value + ":cost"),
            req.parent_deliverable.reference,
        ),
    )


def test_proposal_is_not_execution_and_approval_is_immutable(cli: CLI) -> None:
    repo, req = setup(cli)
    with pytest.raises(ValueError):
        replace(req, trigger=RevisionTrigger.OPERATOR)
    before = cli.world.current()
    assert repo.prepare(req) is True
    assert repo.prepare(req) is False
    assert repo.get_allocation(req.reference) is None
    allocation = approve(repo, req)
    assert allocation.version == 2 and approve(repo, req) == allocation
    assert cli.world.current() == before
    with pytest.raises((DomainError, ValueError)):
        repo.prepare(replace(req, reason="changed"))
    assert cli.world.current().verified_revenue.amount == 0


def test_concurrent_approvals_have_one_successor(cli: CLI) -> None:
    repo, req = setup(cli)
    other = request(cli, "other")
    repo.prepare(req)
    repo.prepare(other)

    def attempt(item: DataRevisionRequest) -> bool:
        try:
            approve(repo, item)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, (req, other))) == [False, True]


@pytest.mark.parametrize(
    "kind", ["revision_approval", "revision_successor", "revision_version", "revision_allocation"]
)
def test_allocation_rolls_back_each_write(cli: CLI, kind: str) -> None:
    repo, req = setup(cli)
    repo.prepare(req)
    original = cli.world.database.write

    def write(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        if args[1] == kind:
            raise RuntimeError("injected write failure")

    with patch.object(cli.world.database, "write", side_effect=write), pytest.raises(RuntimeError):
        approve(repo, req)
    assert repo.get_allocation(req.reference) is None
    assert approve(repo, req).version == 2


def test_start_finish_reopen_preserves_parent_and_budget(cli: CLI) -> None:
    repo, req = setup(cli)
    original_evidence = {
        (row[0], row[1]): row
        for row in rows(cli)
        if row[0] not in ("budget", "budget_audit", "opportunity")
    }
    repo.prepare(req)
    allocation = approve(repo, req)
    budget = cli.world.budget()
    zero = budget.ledger.get(Reference("ledger"))
    assert zero is not None
    from decimal import Decimal

    from agentmine.domain.money import Money

    budget.authorize(
        Money(Decimal(0), "USD"),
        CostContext(
            allocation.binding.operation_reference,
            OperationType.TASK_EXECUTION,
            cli.world.clock.now(),
            req.specification.task.reference,
            Reference("op"),
        ),
    )
    ledger = budget.ledger.get(Reference("ledger"))
    assert ledger is not None
    start = RevisionStart(allocation, req.parent_snapshot, ledger, cli.world.clock.now())
    assert repo.start(start) is True
    assert repo.start(start) is False
    # Explicit test invocation, NOT production revision orchestration.
    result = DataWorker(budget, SQLiteDataJournal(cli.world.database), llm=None).execute(
        start.run.worker.plan
    )
    retained = WorkerResult(start.run.worker, result)
    assert repo.save_result(allocation.reference, retained) is False  # worker journal already saved
    current = SQLiteOpportunityRepository(cli.world.database).get(Reference("op"))
    assert current is not None
    finish = RevisionFinish(start.run, retained, current)
    assert repo.finish(finish) is True
    reopened = SQLiteRevisionRuntimeRepository(SQLiteDatabase(cli.world.database.path))
    assert reopened.finish(finish) is False
    assert reopened.get_allocation(req.reference) == allocation
    op = cli.world.current()
    assert op.state == OpportunityState.QA_PENDING and op.qa is None and op.approval is None
    assert op.deliverable is not None and op.deliverable.version == 2
    assert (
        SQLiteExecutionRepository(cli.world.database).get_deliverable(
            req.parent_deliverable.reference, 1
        )
        == req.parent_deliverable
    )
    assert op.submission is None and op.payment is None and op.verified_revenue.amount == 0
    final = SQLiteCostLedgerRepository(cli.world.database).get(Reference("ledger"))
    assert final is not None and len(final.value.records) == 2
    current_evidence = {(row[0], row[1]): row for row in rows(cli)}
    assert all(current_evidence[key] == value for key, value in original_evidence.items())
    assert len(SQLiteExecutionRepository(cli.world.database).for_opportunity(Reference("op"))) == 2


def start_command(cli: CLI, allocation: RevisionAllocation) -> RevisionStart:
    from decimal import Decimal

    from agentmine.domain.money import Money

    manager = cli.world.budget()
    manager.authorize(
        Money(Decimal(0), "USD"),
        CostContext(
            allocation.binding.operation_reference,
            OperationType.TASK_EXECUTION,
            cli.world.clock.now(),
            allocation.request.specification.task.reference,
            Reference("op"),
        ),
    )
    ledger = manager.ledger.get(Reference("ledger"))
    assert ledger is not None
    return RevisionStart(
        allocation, allocation.request.parent_snapshot, ledger, cli.world.clock.now()
    )


def rows(cli: CLI) -> tuple[tuple[object, ...], ...]:
    with cli.world.database.transaction() as connection:
        return tuple(
            tuple(row)
            for row in connection.execute("SELECT * FROM snapshots ORDER BY kind,id").fetchall()
        )


@pytest.mark.parametrize("kind", ["revision_run", "execution", "data_plan", "opportunity"])
def test_start_rolls_back_each_write(cli: CLI, kind: str) -> None:
    repo, req = setup(cli)
    repo.prepare(req)
    start = start_command(cli, approve(repo, req))
    before = rows(cli)
    original = cli.world.database.write

    def write(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        if args[1] == kind:
            raise RuntimeError("write failed")

    with patch.object(cli.world.database, "write", side_effect=write), pytest.raises(RuntimeError):
        repo.start(start)
    assert rows(cli) == before
    assert repo.start(start)
    assert not SQLiteRevisionRuntimeRepository(SQLiteDatabase(cli.world.database.path)).start(start)


@pytest.mark.parametrize("kind", ["content", "deliverable", "opportunity", "revision_finish"])
def test_finish_rolls_back_each_write(cli: CLI, kind: str) -> None:
    repo, req = setup(cli)
    repo.prepare(req)
    allocation = approve(repo, req)
    start = start_command(cli, allocation)
    repo.start(start)
    result = DataWorker(cli.world.budget(), SQLiteDataJournal(cli.world.database)).execute(
        start.run.worker.plan
    )
    # Distinct artifact bytes exercise the content write even if records are identical.
    # This is a test-only worker-output fixture, not an asserted QA result.
    from agentmine.infrastructure.sqlite.database import IndexValues

    result = replace(
        result,
        artifacts=(
            replace(result.artifacts[0], content=result.artifacts[0].content + "\n"),
            *result.artifacts[1:],
        ),
    )
    with cli.world.database.transaction(write=True) as connection:
        cli.world.database.write(
            connection,
            "data_result",
            allocation.binding.execution_reference.value,
            result,
            1,
            IndexValues(),
        )
    snapshot = SQLiteOpportunityRepository(cli.world.database).get(Reference("op"))
    assert snapshot is not None
    finish = RevisionFinish(start.run, WorkerResult(start.run.worker, result), snapshot)
    before = rows(cli)
    original = cli.world.database.write

    def write(*args: object, **kwargs: object) -> None:
        original(*args, **kwargs)  # type: ignore[arg-type]
        if args[1] == kind:
            raise RuntimeError("write failed")

    with patch.object(cli.world.database, "write", side_effect=write), pytest.raises(RuntimeError):
        repo.finish(finish)
    assert rows(cli) == before
    assert repo.finish(finish)
    assert not repo.finish(finish)


def test_real_fail_report_is_a_supported_trigger(cli: CLI) -> None:
    from test_operational_deliverable_qa import (
        test_real_qa_engine_detects_coherently_corrupted_values_as_fail,
    )

    # Existing test-only corruption drives the real QA engine, not a fabricated PASS/FAIL API.
    test_real_qa_engine_detects_coherently_corrupted_values_as_fail(cli)
    repo = SQLiteRevisionRuntimeRepository(cli.world.database)
    req = request(cli)
    assert repo.prepare(req)
    assert approve(repo, req).version == 2


@pytest.mark.parametrize("incomplete", [False, True])
def test_operator_trigger_requires_applied_lifecycle(cli: CLI, incomplete: bool) -> None:
    from test_operational_deliverable_qa import operator_command

    from agentmine.application.errors import PortError, PortErrorCode

    execute_data(cli)
    assert qa(cli)[1]["qa_outcome"] == "PASS"
    assert (
        operator_command(
            cli,
            "review",
            "--opportunity",
            "op",
            "--review-id",
            "review",
            "--destination",
            "operator:local",
        )
        == 0
    )
    if incomplete:
        with patch.object(
            SQLiteOpportunityRepository,
            "save",
            side_effect=PortError(PortErrorCode.UNAVAILABLE, "save", "injected"),
        ):
            assert (
                operator_command(
                    cli, "decide", "--review-id", "review", "--decision", "REQUEST_REVISION"
                )
                != 0
            )
        # A forged future state cannot make the saved decision an applied transition.
        snapshot = SQLiteOpportunityRepository(cli.world.database).get(Reference("op"))
        assert snapshot is not None
        updated = snapshot.value.request_revision()
        with patch.object(
            SQLiteOpportunityRepository,
            "get",
            return_value=replace(snapshot, value=updated, revision=snapshot.revision + 1),
        ):
            req = replace(
                request(cli, trigger=RevisionTrigger.OPERATOR, trigger_reference="review"),
                trigger=RevisionTrigger.OPERATOR,
                trigger_reference=Reference("review"),
            )
        with pytest.raises(ValueError):
            SQLiteRevisionRuntimeRepository(cli.world.database).prepare(req)
        assert cli.world.current().state == OpportunityState.READY_FOR_HUMAN_REVIEW
        assert (
            operator_command(
                cli, "decide", "--review-id", "review", "--decision", "REQUEST_REVISION"
            )
            == 0
        )
    else:
        assert (
            operator_command(
                cli, "decide", "--review-id", "review", "--decision", "REQUEST_REVISION"
            )
            == 0
        )
    req = replace(
        request(cli, trigger=RevisionTrigger.OPERATOR, trigger_reference="review"),
        trigger=RevisionTrigger.OPERATOR,
        trigger_reference=Reference("review"),
    )
    with pytest.raises(ValueError):
        replace(req, trigger=RevisionTrigger.QA)
    repo = SQLiteRevisionRuntimeRepository(cli.world.database)
    assert repo.prepare(req)
    assert approve(repo, req).version == 2


@pytest.mark.parametrize("mode", ["human", "submitted"])
def test_unsupported_parent_states(cli: CLI, mode: str) -> None:
    from test_operational_deliverable_qa import operator_command

    execute_data(cli, semantic=mode == "human")
    qa(cli)
    if mode == "submitted":
        assert (
            operator_command(
                cli,
                "review",
                "--opportunity",
                "op",
                "--review-id",
                "review",
                "--destination",
                "operator:local",
            )
            == 0
        )
        assert (
            operator_command(cli, "decide", "--review-id", "review", "--decision", "APPROVE") == 0
        )
        # Domain-only synthetic receipt in this isolated test; no external gateway call.
        from agentmine.application.contracts.records import OpportunitySave
        from agentmine.domain.work import Submission

        snapshot = SQLiteOpportunityRepository(cli.world.database).get(Reference("op"))
        assert snapshot is not None
        op = snapshot.value
        assert op.deliverable is not None and op.qa is not None and op.approval is not None
        submitted = op.submit(
            Submission(
                Reference("fixture:submission"),
                op.deliverable,
                op.qa,
                op.approval,
                op.approval.target,
                Reference("fixture:receipt"),
                cli.world.clock.now(),
            )
        )
        SQLiteOpportunityRepository(cli.world.database).save(
            OpportunitySave(submitted, snapshot.revision)
        )
    with pytest.raises((ValueError, DomainError)):
        request(cli)


@pytest.mark.parametrize("case", ["criteria", "actor", "task", "source", "forecast"])
def test_frozen_scope_cannot_be_relaxed_or_rebound(cli: CLI, case: str) -> None:
    _, req = setup(cli)
    spec = req.specification
    assert spec.acceptance is not None and spec.execution_evidence is not None
    with pytest.raises((ValueError, DomainError)):
        if case == "criteria":
            criteria = replace(
                spec.acceptance,
                requirements=(replace(spec.acceptance.requirements[0], criterion="name"),),
            )
            spec = replace(spec, acceptance=criteria)
        elif case == "actor":
            spec = replace(spec, actor=Reference("other"))
        elif case == "task":
            spec = replace(spec, task=replace(spec.task, reference=Reference("other")))
        elif case == "source":
            spec = replace(
                spec,
                source_context=replace(spec.source_context, terms_reference=Reference("changed")),
            )
        else:
            spec = replace(spec, execution_evidence=req.parent_run.specification.execution_evidence)
        replace(req, specification=spec)


def test_missing_approval_and_stale_parent_never_start(cli: CLI) -> None:
    repo, req = setup(cli)
    repo.prepare(req)
    approval = DataRevisionApproval(
        req.reference, req.specification.actor, req.specification.approved_at, True
    )
    binding = ExecutionBinding(
        req.specification.reference,
        Reference("new-e"),
        Reference("new-o"),
        req.parent_deliverable.reference,
    )
    fake = RevisionAllocation(req, approval, binding)
    start = start_command(cli, fake)
    with pytest.raises(ValueError):
        repo.start(start)
    assert cli.world.current() == req.parent_snapshot.value
    from agentmine.application.contracts.records import OpportunitySave

    SQLiteOpportunityRepository(cli.world.database).save(
        OpportunitySave(req.parent_snapshot.value, req.parent_snapshot.revision)
    )
    with pytest.raises(ValueError):
        repo.approve(req.reference, approval, binding)


def test_allocation_lost_ack_reopens_original_identity(cli: CLI) -> None:
    repo, req = setup(cli)
    repo.prepare(req)
    allocation = approve(repo, req)  # Commit succeeds; caller discards its acknowledgement.
    reopened = SQLiteRevisionRuntimeRepository(SQLiteDatabase(cli.world.database.path))
    assert approve(reopened, req) == allocation
    with pytest.raises(ValueError):
        reopened.approve(
            req.reference,
            allocation.approval,
            replace(allocation.binding, execution_reference=Reference("replacement")),
        )
    assert reopened.inspect(req.reference) is not None


def test_no_worker_or_external_effect_during_prepare_and_approve(cli: CLI) -> None:
    repo, req = setup(cli)
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no dispatch")):
        repo.prepare(req)
        approve(repo, req)
    assert cli.world.current() == req.parent_snapshot.value


@pytest.mark.parametrize(
    "case", ["actor", "confirm", "version", "old-operation", "missing-trigger"]
)
def test_consent_and_allocated_identity_guards(cli: CLI, case: str) -> None:
    from agentmine.infrastructure.sqlite.database import IndexValues, composite_key

    repo, req = setup(cli)
    repo.prepare(req)
    if case == "missing-trigger":
        with cli.world.database.transaction(write=True) as connection:
            connection.execute("DELETE FROM snapshots WHERE kind='operational_qa_applied'")
    elif case == "version":
        with cli.world.database.transaction(write=True) as connection:
            cli.world.database.write(
                connection,
                "revision_version",
                composite_key("cli-deliverable", 2),
                Reference("some-other-owner"),
                1,
                IndexValues(),
            )
    with pytest.raises((ValueError, DomainError)):
        approval = DataRevisionApproval(
            req.reference,
            Reference("other") if case == "actor" else req.specification.actor,
            req.specification.approved_at,
            case != "confirm",
        )
        binding = ExecutionBinding(
            req.specification.reference,
            Reference("new-exec"),
            req.parent_run.binding.operation_reference
            if case == "old-operation"
            else Reference("new-cost"),
            req.parent_deliverable.reference,
        )
        repo.approve(req.reference, approval, binding)
    assert repo.get_allocation(req.reference) is None


def test_same_id_concurrent_approval_and_start_are_readback(cli: CLI) -> None:
    repo, req = setup(cli)
    repo.prepare(req)
    with ThreadPoolExecutor(max_workers=2) as pool:
        allocations = list(pool.map(lambda _: approve(repo, req), range(2)))
    assert allocations[0] == allocations[1]
    start = start_command(cli, allocations[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: repo.start(start), range(2))) == [False, True]


def test_unknown_ai_claim_blocks_start_and_is_visible(cli: CLI) -> None:
    from agentmine.application.contracts.data_revision import RevisionReason

    repo, req = setup(cli)
    repo.prepare(req)
    allocation = approve(repo, req)
    start = start_command(cli, allocation)
    assert SQLiteDataJournal(cli.world.database).claim_ai(start.run.worker.plan)
    with pytest.raises(ValueError):
        repo.start(start)
    view = repo.inspect(req.reference)
    assert view is not None and view.reason == RevisionReason.UNKNOWN_EFFECT


def test_domain_rework_guards_and_exact_finish_version(cli: CLI) -> None:
    from agentmine.domain.work import Deliverable

    repo, req = setup(cli)
    repo.prepare(req)
    start = start_command(cli, approve(repo, req))
    evidence = req.specification.execution_evidence
    assert evidence is not None
    parent = req.parent_snapshot.value
    execution = start.run.worker.plan.execution
    assessment = evidence.evaluation.scoring_assessment
    eligibility = evidence.evaluation.eligibility
    with pytest.raises(DomainError):
        parent.start(execution)
    updated = parent.begin_rework(req.parent_deliverable, execution, eligibility, assessment)
    assert updated.history == parent.history
    with pytest.raises(DomainError):
        updated.begin_rework(req.parent_deliverable, execution, eligibility, assessment)
    with pytest.raises(DomainError):
        parent.begin_rework(
            req.parent_deliverable, req.parent_run.plan.execution, eligibility, assessment
        )
    with pytest.raises(DomainError):
        updated.finish(
            Deliverable(
                req.parent_deliverable.reference,
                execution.reference,
                1,
                req.parent_deliverable.content_reference,
            )
        )
    assert start.allocation.version == 2


def test_acceptance_additions_are_immutable_and_allowed(cli: CLI) -> None:
    repo, req = setup(cli)
    criteria = req.specification.acceptance
    assert criteria is not None
    addition = replace(criteria.requirements[0], reference=Reference("added"), criterion="name")
    req = replace(
        req,
        specification=replace(
            req.specification,
            acceptance=replace(criteria, requirements=(*criteria.requirements, addition)),
        ),
    )
    assert repo.prepare(req)
    assert repo.get_request(req.reference) == req
