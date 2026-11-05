"""Internal SQLite contract tests only: operational v2 preflight remains blocked."""

import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from partition_artifact_fakes import CASES, ArtifactCase, artifact_plan
from test_partition_contracts import acceptance
from test_worker_execution_runtime import World, build_world, usd

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.records import BudgetCommit
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    InputEvidence,
    RecoveryReason,
    WorkerResult,
    WorkerRunFinish,
    WorkerRunStart,
)
from agentmine.application.contracts.worker_execution import (
    ExecuteWorkerRequest,
    WorkerExecutionReason,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.workers.data import DataWorker
from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.errors import DomainError
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase
from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository


def started(path: Path, case: ArtifactCase) -> tuple[World, WorkerRunStart, BudgetManager]:
    w = build_world(path)
    plan = artifact_plan(case)
    ledger = SQLiteCostLedgerRepository(w.database)
    previous = ledger.get(Reference("ledger"))
    assert previous is not None
    zero = usd("0")
    ledger.commit(
        BudgetCommit(
            Reference("ledger"),
            Budget(BudgetPolicy(zero, zero, zero, zero), OperatingMode.SCOUT_ONLY),
            previous.revision,
            None,
        )
    )
    criteria = replace(acceptance(), partition_acceptance=plan.partition_acceptance)
    spec = replace(
        w.specification,
        reference=Reference("v2-spec"),
        sources=plan.sources,
        input_evidence=tuple(
            InputEvidence(s.reference, Reference("sha256:" + s.digest)) for s in plan.sources
        ),
        columns=plan.columns,
        unique_by=plan.unique_by,
        min_records=plan.min_records,
        max_records=plan.max_records,
        acceptance=criteria,
        output_policy=plan.output_policy,
    )
    w.runtime().save_specification(spec)
    binding = ExecutionBinding(
        spec.reference, Reference("v2-exec"), Reference("v2-op"), Reference("v2-deliverable")
    )
    blocked = replace(w.use_case(), operator=Reference("unapproved")).execute(
        ExecuteWorkerRequest(binding, w.request.expected_opportunity_revision)
    )
    assert blocked.reason == WorkerExecutionReason.APPROVAL_DENIED
    assert w.runtime().get_run(binding.execution_reference) is None
    manager = w.budget()
    manager.authorize(
        zero,
        CostContext(
            binding.operation_reference,
            OperationType.TASK_EXECUTION,
            w.clock.now(),
            spec.task.reference,
            spec.task.opportunity_reference,
        ),
    )
    op = w.use_case().opportunities.get(spec.task.opportunity_reference)
    budget = ledger.get(Reference("ledger"))
    assert op is not None and budget is not None
    command = WorkerRunStart(spec, binding, op, budget, w.clock.now())
    # Explicit TEST-ONLY internal persistence command; not a CLI/preflight bypass in production.
    assert w.runtime().start(command)
    return w, command, manager


@pytest.mark.parametrize("case_name", ["all_valid", "partial_malformed"])
@pytest.mark.parametrize(
    "failed_kind", [None, "content", "deliverable", "opportunity", "runtime_finish"]
)
def test_cost_durable_before_atomic_finish_and_rollback(
    tmp_path: Path, case_name: str, failed_kind: str | None
) -> None:
    w, start, manager = started(tmp_path, next(c for c in CASES if c["name"] == case_name))
    run = start.run
    result = DataWorker(manager, SQLiteDataJournal(w.database), llm=None).execute(run.plan)
    retained = WorkerResult(run, result)
    assert not w.runtime().save_result(retained)  # Worker result already durable in shared journal.
    view = w.runtime().inspect(run.binding.execution_reference)
    assert view is not None and view.reason == RecoveryReason.FINISH_PENDING
    snapshot = manager.ledger.get(Reference("ledger"))
    assert snapshot is not None and len(snapshot.value.records) == 1
    finish = WorkerRunFinish(retained, view.opportunity_snapshot)
    original = SQLiteDatabase.write

    def fail(
        self: SQLiteDatabase,
        connection: sqlite3.Connection,
        kind: str,
        key: str,
        value: object,
        revision: int,
        indexes: IndexValues,
    ) -> None:
        original(self, connection, kind, key, value, revision, indexes)
        if kind == failed_kind:
            raise PortError(PortErrorCode.UNAVAILABLE, "test", "after write")

    if failed_kind is not None:
        with patch.object(SQLiteDatabase, "write", fail), pytest.raises(PortError):
            w.runtime().finish(finish)
        pending = w.runtime().inspect(run.binding.execution_reference)
        assert pending is not None and not pending.finished
        assert pending.opportunity_snapshot == view.opportunity_snapshot
        assert (
            SQLiteExecutionRepository(w.database).get_content(bundle_content(result).reference)
            is None
        )
    repo = SQLiteWorkerRuntimeRepository(SQLiteDatabase(w.database.path))
    assert repo.finish(finish)
    assert not repo.finish(finish)
    completed = repo.inspect(run.binding.execution_reference)
    assert completed is not None and completed.finished
    assert completed.opportunity_snapshot.value.state == OpportunityState.QA_PENDING
    assert completed.opportunity_snapshot.value.approval is None
    assert completed.opportunity_snapshot.value.submission is None
    assert completed.opportunity_snapshot.value.verified_revenue.amount == 0
    assert manager.ledger.get(Reference("ledger")) == snapshot
    assert SQLiteExecutionRepository(w.database).get_content(
        bundle_content(result).reference
    ) == bundle_content(result)
    assert (
        completed.deliverable is not None
        and completed.deliverable.content_reference == bundle_content(result).reference
    )


def test_finished_transaction_lost_acknowledgement_is_read_back(tmp_path: Path) -> None:
    w, start, manager = started(tmp_path, CASES[0])
    run = start.run
    result = DataWorker(manager, SQLiteDataJournal(w.database), llm=None).execute(run.plan)
    view = w.runtime().inspect(run.binding.execution_reference)
    assert view is not None
    command = WorkerRunFinish(WorkerResult(run, result), view.opportunity_snapshot)
    original = SQLiteWorkerRuntimeRepository.finish

    def lost(self: SQLiteWorkerRuntimeRepository, value: WorkerRunFinish) -> bool:
        original(self, value)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "test", "lost acknowledgement")

    with patch.object(SQLiteWorkerRuntimeRepository, "finish", lost), pytest.raises(PortError):
        w.runtime().finish(command)
    assert not SQLiteWorkerRuntimeRepository(SQLiteDatabase(w.database.path)).finish(command)
    snapshot = manager.ledger.get(Reference("ledger"))
    assert snapshot is not None and len(snapshot.value.records) == 1


@pytest.mark.parametrize("case_name", ["all_valid", "partial_malformed"])
def test_version_bound_artifact_inventory_is_strict(tmp_path: Path, case_name: str) -> None:
    w, start, manager = started(tmp_path, next(c for c in CASES if c["name"] == case_name))
    run = start.run
    result = DataWorker(manager, SQLiteDataJournal(w.database), llm=None).execute(run.plan)
    WorkerResult(run, result)
    from agentmine.application.contracts.data import DataArtifact

    for bad in (
        replace(
            result,
            artifacts=(*result.artifacts, DataArtifact("extra.json", "application/json", "{}")),
        ),
        replace(result, cost=None),
        replace(result, partition=None),
    ):
        with pytest.raises(DomainError):
            WorkerResult(run, bad)
    if case_name == "all_valid":
        with pytest.raises(DomainError):
            WorkerResult(run, replace(result, artifacts=tuple(reversed(result.artifacts))))
    # Legacy contracts continue to reject v2 artifact names and partition evidence.
    legacy_spec = replace(run.specification, output_policy=None, acceptance=None)
    legacy_run = replace(run, specification=legacy_spec, plan=legacy_spec.plan(run.plan.execution))
    with pytest.raises(DomainError):
        WorkerResult(legacy_run, result)
