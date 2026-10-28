"""B2 acceptance: real SQLite/DataWorker; explicitly test-only source and clock."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from test_data_revision_foundation import setup
from test_runtime_operator_cli import CLI, cli

from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.contracts.data_revision import DataRevisionRequest, RevisionAllocation
from agentmine.application.contracts.local_runtime import ApprovedDataInput, PrepareDataRequest
from agentmine.application.contracts.revision_execution import PrepareRevisionRequest
from agentmine.application.contracts.runtime import ExecutionBinding
from agentmine.application.contracts.worker_execution import WorkerExecutionStatus
from agentmine.application.use_cases.data_revision import (
    ApproveDataRevision,
    GetDataRevision,
    PrepareDataRevision,
)
from agentmine.application.use_cases.revision_execution import (
    ExecuteDataRevision,
    RecoverDataRevision,
)
from agentmine.application.workers.data import DataWorker
from agentmine.domain.values import Reference
from agentmine.infrastructure.local_data_inputs import LocalDataInputReader
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.data_revision import SQLiteRevisionRuntimeRepository
from agentmine.infrastructure.sqlite.evaluations import SQLiteEvaluationRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

__all__ = ["cli"]


def prepare_case(
    cli: CLI, mode: str = "needs_revision"
) -> tuple[SQLiteRevisionRuntimeRepository, PrepareDataRevision, PrepareRevisionRequest]:
    if mode == "needs_revision":
        repo, template = setup(cli)
    else:
        from test_data_revision_foundation import request as retained_request
        from test_operational_deliverable_qa import (
            execute_data,
            operator_command,
            qa,
            test_real_qa_engine_detects_coherently_corrupted_values_as_fail,
        )

        from agentmine.application.contracts.data_revision import RevisionTrigger

        if mode == "fail":
            test_real_qa_engine_detects_coherently_corrupted_values_as_fail(cli)
            template = retained_request(cli)
        else:
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
                    "operator:fixture",
                )
                == 0
            )
            assert (
                operator_command(
                    cli, "decide", "--review-id", "review", "--decision", "REQUEST_REVISION"
                )
                == 0
            )
            template = retained_request(
                cli, trigger=RevisionTrigger.OPERATOR, trigger_reference="review"
            )
        repo = SQLiteRevisionRuntimeRepository(cli.world.database)
    spec = template.specification
    evidence = spec.execution_evidence
    assert evidence is not None and spec.acceptance is not None
    source = spec.sources[0]
    input_request = ApprovedDataInput(
        source.reference,
        "input.json",
        source.format,
        source.locator,
        source.collected_at,
        Reference("sha256:" + source.digest),
    )
    work = PrepareDataRequest(
        spec.reference,
        Reference("op"),
        evidence.evaluation.reference,
        evidence.eligibility_request,
        evidence.eligibility_policy,
        (input_request,),
        spec.columns,
        spec.unique_by,
        spec.min_records,
        spec.max_records,
        spec.constraints,
        evidence.eligibility_review_reference,
        spec.acceptance,
    )
    scoring = evidence.evaluation.scoring_assessment
    request = PrepareRevisionRequest(
        template.reference,
        Reference("cli-exec"),
        template.trigger,
        template.trigger_reference,
        work,
        scoring.economics.inputs,
        scoring.signals,
        scoring.policy,
        "Repair the approved data",
        evidence.evaluation.evidence,
    )
    use_case = PrepareDataRevision(
        repo,
        SQLiteOpportunityRepository(cli.world.database),
        cli.world.source,
        cli.world.clock,
        Reference("operator"),
        Reference("ledger"),
        LocalDataInputReader(cli.root),
    )
    return repo, use_case, request


def executor(cli: CLI, repo: SQLiteRevisionRuntimeRepository) -> ExecuteDataRevision:
    return ExecuteDataRevision(
        repo,
        SQLiteOpportunityRepository(cli.world.database),
        SQLiteEvaluationRepository(cli.world.database),
        cli.world.budget(),
        SQLiteDataJournal(cli.world.database),
        cli.world.source,
        Reference("operator"),
    )


def approved(
    cli: CLI, mode: str = "needs_revision"
) -> tuple[SQLiteRevisionRuntimeRepository, DataRevisionRequest, RevisionAllocation]:
    repo, prepare, command = prepare_case(cli, mode)
    request = prepare.execute(command)
    review = GetDataRevision(repo, Reference("operator"), Reference("ledger")).execute(
        request.reference
    )
    assert review.request == request and review.allocation is None
    binding = ExecutionBinding(
        request.specification.reference,
        Reference("revision:exec"),
        Reference("revision:cost"),
        request.parent_deliverable.reference,
    )
    use_case = ApproveDataRevision(
        repo,
        SQLiteOpportunityRepository(cli.world.database),
        SQLiteEvaluationRepository(cli.world.database),
        cli.world.source,
        cli.world.clock,
        Reference("operator"),
        Reference("ledger"),
    )
    allocation = use_case.execute(request, binding, confirm=True)
    assert use_case.execute(request, binding, confirm=True) == allocation
    return repo, request, allocation


@pytest.mark.parametrize("mode", ["needs_revision", "fail", "operator"])
def test_prepare_approve_execute_and_recover(cli: CLI, mode: str) -> None:
    repo, request, allocation = approved(cli, mode)
    use_case = executor(cli, repo)
    original = DataWorker.execute
    with patch.object(DataWorker, "execute", autospec=True, side_effect=original) as worker:
        result = use_case.execute(request.reference, confirm=True)
        assert result.status == WorkerExecutionStatus.COMPLETED
        assert worker.call_count == 1
        recovered = RecoverDataRevision(use_case).execute(request.reference, confirm=True)
        assert recovered.status == WorkerExecutionStatus.COMPLETED and worker.call_count == 1
    deliverable = cli.world.current().deliverable
    assert deliverable is not None
    assert deliverable.version == allocation.version == 2
    assert (
        cli.world.current().submission is None and cli.world.current().verified_revenue.amount == 0
    )


@pytest.mark.parametrize("change", ["unavailable", "terms", "deadline"])
def test_fresh_preflight_blocks_changed_source(cli: CLI, change: str) -> None:
    from datetime import timedelta

    repo, request, _ = approved(cli)
    if change == "terms":
        cli.world.source.requirements = "new terms"
    elif change == "deadline":
        cli.world.clock.instant += timedelta(days=3)
    else:
        cli.world.source.is_open = None
    with patch.object(DataWorker, "execute", side_effect=AssertionError("must block")):
        outcome = executor(cli, repo).execute(request.reference, confirm=True)
    assert outcome.status == WorkerExecutionStatus.BLOCKED


def test_result_before_accounting_recovers_without_worker(cli: CLI) -> None:
    from agentmine.application.budget_manager import BudgetManager
    from agentmine.application.errors import PortError, PortErrorCode

    repo, request, _ = approved(cli)
    use_case = executor(cli, repo)
    with patch.object(
        BudgetManager,
        "record",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "record", "injected"),
    ):
        assert (
            use_case.execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.RECOVERABLE
        )
    view = repo.inspect(request.reference)
    assert view is not None and view.result is not None
    with patch.object(DataWorker, "execute", side_effect=AssertionError("reuse result")):
        assert (
            RecoverDataRevision(use_case).execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.COMPLETED
        )


@pytest.mark.parametrize(
    "case", ["ineligible", "unknown", "manual", "missing-trigger", "inputs", "criteria"]
)
def test_preparation_fails_closed(cli: CLI, case: str) -> None:
    from agentmine.application.errors import PortError
    from agentmine.domain.eligibility import AIParticipationPolicy, SubmissionSupport
    from agentmine.domain.errors import DomainError

    repo, prepare, command = prepare_case(cli)
    work = command.work
    if case in ("ineligible", "unknown", "manual"):
        facts = work.eligibility.facts
        facts = (
            replace(facts, submission=SubmissionSupport.MANUAL)
            if case == "manual"
            else replace(
                facts,
                ai_policy=AIParticipationPolicy.PROHIBITED
                if case == "ineligible"
                else AIParticipationPolicy.UNKNOWN,
            )
        )
        command = replace(
            command, work=replace(work, eligibility=replace(work.eligibility, facts=facts))
        )
    elif case == "missing-trigger":
        with cli.world.database.transaction(write=True) as connection:
            connection.execute("DELETE FROM snapshots WHERE kind='operational_qa_applied'")
    elif case == "inputs":
        (cli.root / "input.json").write_text("changed unapproved bytes", encoding="utf-8")
    else:
        assert work.acceptance is not None
        criterion = replace(work.acceptance.requirements[0], criterion="name")
        command = replace(
            command,
            work=replace(work, acceptance=replace(work.acceptance, requirements=(criterion,))),
        )
    with pytest.raises((ValueError, DomainError, PortError)):
        prepare.execute(command)
    assert repo.get_request(command.reference) is None


def test_preparation_immutable_and_approval_requires_exact_review(cli: CLI) -> None:
    repo, prepare, command = prepare_case(cli)
    request = prepare.execute(command)
    assert prepare.execute(command) == request
    with pytest.raises(ValueError):
        prepare.execute(replace(command, reason="silently changed"))
    binding = ExecutionBinding(
        request.specification.reference,
        Reference("new-exec"),
        Reference("new-cost"),
        request.parent_deliverable.reference,
    )
    approve = ApproveDataRevision(
        repo,
        SQLiteOpportunityRepository(cli.world.database),
        SQLiteEvaluationRepository(cli.world.database),
        cli.world.source,
        cli.world.clock,
        Reference("operator"),
        Reference("ledger"),
    )
    with pytest.raises(ValueError):
        approve.execute(request, binding, confirm=False)
    with pytest.raises(ValueError):
        approve.execute(replace(request, reason="different scope"), binding, confirm=True)
    assert (
        executor(cli, repo).execute(request.reference, confirm=True).status
        == WorkerExecutionStatus.BLOCKED
    )


def test_scout_only_authorizes_before_real_worker_and_retains_parent(cli: CLI) -> None:
    from agentmine.application.contracts.records import BudgetCommit
    from agentmine.domain.budget import OperatingMode
    from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository

    repo, request, allocation = approved(cli)
    manager = cli.world.budget()
    snapshot = manager.ledger.get(Reference("ledger"))
    assert snapshot is not None
    before_costs = snapshot.value.records
    manager.ledger.commit(
        BudgetCommit(
            Reference("ledger"),
            snapshot.value.with_requested_mode(OperatingMode.SCOUT_ONLY),
            snapshot.revision,
            None,
        )
    )
    original = DataWorker.execute

    def work(worker: DataWorker, plan: DataPlan) -> DataResult:
        view = repo.inspect(request.reference)
        ledger = manager.ledger.get(Reference("ledger"))
        assert view is not None and view.run is not None and ledger is not None
        assert plan.execution.authorization in ledger.value.outstanding
        assert plan.execution.authorization.request.estimated_cost.amount == 0
        return original(worker, plan)

    with patch.object(DataWorker, "execute", work):
        assert (
            executor(cli, repo).execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.COMPLETED
        )
    final = manager.ledger.get(Reference("ledger"))
    assert (
        final is not None
        and final.value.records[:-1] == before_costs
        and len(final.value.records) == 2
    )
    assert (
        SQLiteExecutionRepository(cli.world.database).get_deliverable(
            request.parent_deliverable.reference, 1
        )
        == request.parent_deliverable
    )
    assert cli.world.runtime().get_run(Reference("cli-exec")) == request.parent_run
    assert allocation.version == 2


@pytest.mark.parametrize(
    "window", ["before-start", "after-start", "before-finish", "after-finish", "worker"]
)
def test_crash_recovery_preserves_original_ids(cli: CLI, window: str) -> None:
    from agentmine.application.errors import PortError, PortErrorCode

    repo, request, allocation = approved(cli)
    use_case = executor(cli, repo)
    if window in ("before-start", "after-start"):
        original = repo.start

        def start(*args: object, **kwargs: object) -> bool:
            if window == "after-start":
                original(*args, **kwargs)  # type: ignore[arg-type]
            raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "start", "lost acknowledgement")

        with patch.object(SQLiteRevisionRuntimeRepository, "start", side_effect=start):
            assert (
                use_case.execute(request.reference, confirm=True).status
                == WorkerExecutionStatus.RECOVERABLE
            )
    elif window in ("before-finish", "after-finish"):
        original_finish = repo.finish

        def finish(*args: object, **kwargs: object) -> bool:
            if window == "after-finish":
                original_finish(*args, **kwargs)  # type: ignore[arg-type]
            raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "finish", "lost acknowledgement")

        with patch.object(SQLiteRevisionRuntimeRepository, "finish", side_effect=finish):
            assert (
                use_case.execute(request.reference, confirm=True).status
                == WorkerExecutionStatus.RECOVERABLE
            )
    else:
        with patch.object(DataWorker, "execute", side_effect=RuntimeError("halfway failure")):
            assert (
                use_case.execute(request.reference, confirm=True).status
                == WorkerExecutionStatus.RECOVERABLE
            )
    from agentmine.infrastructure.sqlite.database import SQLiteDatabase

    reopened = SQLiteRevisionRuntimeRepository(SQLiteDatabase(cli.world.database.path))
    recovery = executor(cli, reopened)
    assert (
        RecoverDataRevision(recovery).execute(request.reference, confirm=True).status
        == WorkerExecutionStatus.COMPLETED
    )
    assert reopened.get_allocation(request.reference) == allocation
    final = cli.world.budget().ledger.get(Reference("ledger"))
    assert final is not None and len(final.value.records) == 2


def test_ledger_race_after_authorization_keeps_commitment(cli: CLI) -> None:
    from decimal import Decimal

    from agentmine.domain.money import Money
    from agentmine.domain.spending import CostContext, OperationType

    repo, request, allocation = approved(cli)
    original = repo.start

    def race(*args: object, **kwargs: object) -> bool:
        cli.world.budget().authorize(
            Money(Decimal(0), "USD"),
            CostContext(Reference("other:reserved"), OperationType.SCORING, cli.world.clock.now()),
        )
        return original(*args, **kwargs)  # type: ignore[arg-type]

    with (
        patch.object(SQLiteRevisionRuntimeRepository, "start", side_effect=race),
        patch.object(DataWorker, "execute", side_effect=AssertionError("no dispatch")),
    ):
        assert (
            executor(cli, repo).execute(request.reference, confirm=True).status
            != WorkerExecutionStatus.COMPLETED
        )
    ledger = cli.world.budget().ledger.get(Reference("ledger"))
    assert ledger is not None and any(
        a.request.context.operation_reference == allocation.binding.operation_reference
        for a in ledger.value.outstanding
    )
    assert (
        RecoverDataRevision(executor(cli, repo)).execute(request.reference, confirm=True).status
        == WorkerExecutionStatus.COMPLETED
    )


def test_unknown_claim_blocks_recovery(cli: CLI) -> None:
    repo, request, _ = approved(cli)
    with patch.object(DataWorker, "execute", side_effect=RuntimeError("interrupted")):
        executor(cli, repo).execute(request.reference, confirm=True)
    view = repo.inspect(request.reference)
    assert view is not None and view.run is not None
    assert SQLiteDataJournal(cli.world.database).claim_ai(view.run.worker.plan)
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no paid replay")):
        outcome = RecoverDataRevision(executor(cli, repo)).execute(request.reference, confirm=True)
    assert outcome.status == WorkerExecutionStatus.BLOCKED


def test_frozen_inputs_and_changed_forecast_evidence(cli: CLI) -> None:
    repo, request, _ = approved(cli)
    (cli.root / "input.json").write_text("unapproved edit", encoding="utf-8")
    evidence = request.specification.execution_evidence
    assert evidence is not None
    with patch.object(
        SQLiteEvaluationRepository,
        "get",
        return_value=replace(evidence.evaluation, evidence=(Reference("changed"),)),
    ):
        assert (
            executor(cli, repo).execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.BLOCKED
        )
    assert (
        executor(cli, repo).execute(request.reference, confirm=True).status
        == WorkerExecutionStatus.COMPLETED
    )


def test_concurrent_execution_and_same_id_recovery(cli: CLI) -> None:
    from concurrent.futures import ThreadPoolExecutor

    repo, request, allocation = approved(cli)
    use_case = executor(cli, repo)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: use_case.execute(request.reference, confirm=True), range(2))
        )
    assert any(
        result.status
        in (
            WorkerExecutionStatus.COMPLETED,
            WorkerExecutionStatus.RECOVERABLE,
        )
        for result in results
    )
    assert (
        RecoverDataRevision(use_case).execute(request.reference, confirm=True).status
        == WorkerExecutionStatus.COMPLETED
    )
    assert repo.get_allocation(request.reference) == allocation
    ledger = cli.world.budget().ledger.get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.records) == 2


@pytest.mark.parametrize("same", [True, False])
def test_explicit_concurrent_approvals(cli: CLI, same: bool) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from agentmine.application.contracts.data_revision import RevisionError

    repo, prepare, command = prepare_case(cli)
    request = prepare.execute(command)
    use_case = ApproveDataRevision(
        repo,
        SQLiteOpportunityRepository(cli.world.database),
        SQLiteEvaluationRepository(cli.world.database),
        cli.world.source,
        cli.world.clock,
        Reference("operator"),
        Reference("ledger"),
    )
    first = ExecutionBinding(
        request.specification.reference,
        Reference("exec:one"),
        Reference("cost:one"),
        request.parent_deliverable.reference,
    )
    second = (
        first
        if same
        else replace(
            first,
            execution_reference=Reference("exec:two"),
            operation_reference=Reference("cost:two"),
        )
    )

    def attempt(binding: ExecutionBinding) -> RevisionAllocation | None:
        try:
            return use_case.execute(request, binding, confirm=True)
        except RevisionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (first, second)))
    assert sum(value is not None for value in outcomes) == (2 if same else 1)
    allocation = repo.get_allocation(request.reference)
    assert allocation is not None
    assert use_case.execute(request, allocation.binding, confirm=True) == allocation


def test_missing_result_replay_requires_fresh_source(cli: CLI) -> None:
    repo, request, allocation = approved(cli)
    use_case = executor(cli, repo)
    with patch.object(DataWorker, "execute", side_effect=RuntimeError("interrupted")):
        use_case.execute(request.reference, confirm=True)
    cli.world.source.is_open = None
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no stale replay")):
        assert (
            RecoverDataRevision(use_case).execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.BLOCKED
        )
    assert repo.get_allocation(request.reference) == allocation


def test_retained_result_needs_no_source_but_rejects_changed_state(cli: CLI) -> None:
    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.errors import PortError, PortErrorCode

    repo, request, _ = approved(cli)
    use_case = executor(cli, repo)
    with patch.object(
        SQLiteRevisionRuntimeRepository,
        "finish",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "finish", "failure"),
    ):
        assert (
            use_case.execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.RECOVERABLE
        )
    snapshot = SQLiteOpportunityRepository(cli.world.database).get(Reference("op"))
    assert snapshot is not None
    SQLiteOpportunityRepository(cli.world.database).save(
        OpportunitySave(snapshot.value, snapshot.revision)
    )
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no repeat")):
        assert (
            use_case.execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.BLOCKED
        )


def test_retained_result_finishes_during_source_outage(cli: CLI) -> None:
    from agentmine.application.errors import PortError, PortErrorCode

    repo, request, _ = approved(cli)
    use_case = executor(cli, repo)
    with patch.object(
        SQLiteRevisionRuntimeRepository,
        "finish",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "finish", "failure"),
    ):
        use_case.execute(request.reference, confirm=True)
    cli.world.source.is_open = None
    with (
        patch.object(DataWorker, "execute", side_effect=AssertionError("no repeat")),
        patch.object(
            type(cli.world.source), "refresh", side_effect=AssertionError("local evidence recovery")
        ),
    ):
        assert (
            RecoverDataRevision(use_case).execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.COMPLETED
        )


def test_completed_recovery_preserves_later_qa_state(cli: CLI) -> None:
    from agentmine.application.contracts.operational_qa import QAApplicationBinding
    from agentmine.application.contracts.qa import QAInspection
    from agentmine.application.use_cases.deliverable_qa import DeliverableQA
    from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
    from agentmine.infrastructure.sqlite.operational_qa import SQLiteOperationalQARepository
    from agentmine.infrastructure.sqlite.qa import SQLiteQAJournal

    repo, request, _ = approved(cli)
    use_case = executor(cli, repo)
    assert (
        use_case.execute(request.reference, confirm=True).status == WorkerExecutionStatus.COMPLETED
    )
    view = repo.inspect(request.reference)
    assert (
        view is not None
        and view.run is not None
        and view.result is not None
        and view.deliverable is not None
    )
    current = SQLiteOpportunityRepository(cli.world.database).get(Reference("op"))
    assert current is not None and request.specification.acceptance is not None
    criteria = request.specification.acceptance
    inspection = QAInspection(
        Reference("test:qa-v2"),
        view.deliverable,
        view.run.worker.plan,
        view.result.result,
        criteria.formats,
        criteria.requirements,
    )
    binding = QAApplicationBinding(
        inspection.reference,
        view.run.worker.binding.execution_reference,
        view.deliverable,
        current,
        Reference("operator"),
        cli.world.clock.now(),
    )
    # Direct test-only composition of the existing QA engine; no operational QA CLI added.
    DeliverableQA(
        SQLiteOpportunityRepository(cli.world.database),
        SQLiteExecutionRepository(cli.world.database),
        SQLiteQAJournal(cli.world.database),
        cli.world.clock,
        lifecycle=SQLiteOperationalQARepository(cli.world.database),
    ).execute(inspection, binding=binding)
    after = SQLiteOpportunityRepository(cli.world.database).get(Reference("op"))
    assert after is not None and after != current
    parent = repo.parent(view.run.worker.binding.execution_reference)
    assert (
        parent is not None and parent.deliverable == view.deliverable and parent.snapshot == after
    )
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no rework dispatch")):
        assert (
            RecoverDataRevision(use_case).execute(request.reference, confirm=True).status
            == WorkerExecutionStatus.COMPLETED
        )
    assert SQLiteOpportunityRepository(cli.world.database).get(Reference("op")) == after


def test_human_pending_cannot_prepare_revision(cli: CLI) -> None:
    from test_operational_deliverable_qa import execute_data, qa

    from agentmine.application.contracts.data_revision import RevisionTrigger

    execute_data(cli, semantic=True)
    assert qa(cli)[1]["qa_outcome"] == "REQUIRES_HUMAN_REVIEW"
    run = cli.world.runtime().get_run(Reference("cli-exec"))
    assert run is not None and run.specification.execution_evidence is not None
    spec = run.specification
    evidence = run.specification.execution_evidence
    source = spec.sources[0]
    scoring = evidence.evaluation.scoring_assessment
    work = PrepareDataRequest(
        Reference("proposal:spec"),
        Reference("op"),
        Reference("proposal:eval"),
        evidence.eligibility_request,
        evidence.eligibility_policy,
        (
            ApprovedDataInput(
                source.reference,
                "input.json",
                source.format,
                source.locator,
                source.collected_at,
                Reference("sha256:" + source.digest),
            ),
        ),
        spec.columns,
        spec.unique_by,
        spec.min_records,
        spec.max_records,
        spec.constraints,
        evidence.eligibility_review_reference,
        spec.acceptance,
    )
    command = PrepareRevisionRequest(
        Reference("proposal"),
        Reference("cli-exec"),
        RevisionTrigger.QA,
        Reference("qa-001"),
        work,
        scoring.economics.inputs,
        scoring.signals,
        scoring.policy,
        "Cannot bypass human QA",
        evidence.evaluation.evidence,
    )
    repo = SQLiteRevisionRuntimeRepository(cli.world.database)
    prepare = PrepareDataRevision(
        repo,
        SQLiteOpportunityRepository(cli.world.database),
        cli.world.source,
        cli.world.clock,
        Reference("operator"),
        Reference("ledger"),
        LocalDataInputReader(cli.root),
    )
    with pytest.raises(ValueError):
        prepare.execute(command)
    assert repo.get_request(command.reference) is None
