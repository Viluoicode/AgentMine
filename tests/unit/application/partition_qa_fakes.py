"""C4 test-only retained evidence; real worker/SQLite/bootstrap, fake source and clock."""

from dataclasses import dataclass, replace
from pathlib import Path

from partition_artifact_fakes import CASES, artifact_plan
from test_partition_contracts import acceptance
from test_worker_execution_runtime import World, build_world, usd

from agentmine.application.contracts.data import DataResult, PartitionAcceptance
from agentmine.application.contracts.qa import CoverageKind, QARequirement
from agentmine.application.contracts.records import BudgetCommit
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    InputEvidence,
    WorkerResult,
    WorkerRunFinish,
    WorkerRunStart,
)
from agentmine.application.contracts.worker_execution import (
    ExecuteWorkerRequest,
    WorkerExecutionReason,
)
from agentmine.application.use_cases.operational_qa import RunOperationalDataQA
from agentmine.application.workers.data import DataWorker
from agentmine.bootstrap.local_runtime import compose_local_runtime
from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository


@dataclass
class QAWorld:
    world: World
    start: WorkerRunStart
    result: DataResult

    def qa(self) -> RunOperationalDataQA:
        w = self.world
        return compose_local_runtime(
            w.database, Reference("ledger"), Reference("operator"), w.clock, w.source, None, None
        ).qa

    def reopen(self) -> None:
        self.world.database = SQLiteDatabase(self.world.database.path)


def retained(
    path: Path,
    name: str = "all_valid",
    minimum: int = 1,
    maximum: int = 2,
    *,
    coverage: CoverageKind = CoverageKind.FIELD_PRESENT,
    criterion: str = "id",
    content: str | None = None,
) -> QAWorld:
    w = build_world(path)
    plan = artifact_plan(next(c for c in CASES if c["name"] == name))
    plan = replace(plan, partition_acceptance=PartitionAcceptance(2, minimum, maximum))
    if content is not None:
        plan = replace(plan, sources=(replace(plan.sources[0], content=content),))
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
    criteria = replace(
        acceptance(),
        partition_acceptance=plan.partition_acceptance,
        requirements=(QARequirement(Reference("field"), "clean.json", coverage, criterion),),
    )
    spec = replace(
        w.specification,
        reference=Reference("c4-spec"),
        sources=plan.sources,
        input_evidence=tuple(
            InputEvidence(s.reference, Reference("sha256:" + s.digest)) for s in plan.sources
        ),
        columns=plan.columns,
        unique_by=plan.unique_by,
        min_records=plan.min_records,
        max_records=plan.max_records,
        constraints=plan.constraints,
        acceptance=criteria,
        output_policy=plan.output_policy,
    )
    w.runtime().save_specification(spec)
    binding = ExecutionBinding(
        spec.reference, Reference("c4-exec"), Reference("c4-op"), Reference("c4-deliverable")
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
    snapshot = ledger.get(Reference("ledger"))
    assert op is not None and snapshot is not None
    start = WorkerRunStart(spec, binding, op, snapshot, w.clock.now())
    # Explicitly TEST-ONLY internal C3 persistence setup, never a production dispatch path.
    assert w.runtime().start(start)
    result = DataWorker(manager, SQLiteDataJournal(w.database), llm=None).execute(start.run.plan)
    view = w.runtime().inspect(binding.execution_reference)
    assert view is not None
    assert w.runtime().finish(
        WorkerRunFinish(WorkerResult(start.run, result), view.opportunity_snapshot)
    )
    return QAWorld(w, start, result)
