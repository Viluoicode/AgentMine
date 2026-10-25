"""SQLite atomic first-run ownership and evidence persistence; never executes a worker."""

import sqlite3
from dataclasses import dataclass

from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    RuntimeStatus,
    WorkerResult,
    WorkerRun,
    WorkerRunFinish,
    WorkerRunStart,
    WorkSpecification,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.budget import Budget
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key


def conflict() -> PortError:
    return PortError(
        PortErrorCode.CONFLICT, "worker_runtime", "Runtime identity or snapshot changed"
    )


@dataclass(frozen=True, slots=True)
class SQLiteWorkerRuntimeRepository:
    database: SQLiteDatabase

    def _keep(
        self,
        connection: sqlite3.Connection,
        kind: str,
        reference: str,
        value: object,
        indexes: IndexValues | None = None,
    ) -> bool:
        old = self.database.read(connection, kind, reference, type(value))
        if old is not None:
            if old.value != value:
                raise conflict()
            return False
        self.database.write(connection, kind, reference, value, 1, indexes or IndexValues())
        return True

    def save_specification(self, specification: WorkSpecification) -> bool:
        with self.database.transaction(write=True) as connection:
            old = self.database.read(
                connection, "work_specification", specification.reference.value, WorkSpecification
            )
            if old is not None:
                if old.value != specification:
                    raise conflict()
                return False
            op = self.database.read(
                connection,
                "opportunity",
                specification.task.opportunity_reference.value,
                Opportunity,
            )
            observation = self.database.read(
                connection,
                "observation",
                specification.task.opportunity_reference.value,
                OpportunityObservation,
            )
            if (
                op is None
                or op.value.state != OpportunityState.PLANNED
                or op.value.task != specification.task
                or observation is None
                or observation.value.source_reference
                != specification.source_context.source_reference
            ):
                raise conflict()
            return self._keep(
                connection,
                "work_specification",
                specification.reference.value,
                specification,
                IndexValues(parent=specification.task.opportunity_reference.value),
            )

    def get_specification(self, reference: Reference) -> WorkSpecification | None:
        value = self.database.get("work_specification", reference.value, WorkSpecification)
        return None if value is None else value.value

    def get_run(self, execution_reference: Reference) -> WorkerRun | None:
        with self.database.transaction() as connection:
            return self._run(connection, execution_reference)

    def _run(
        self, connection: sqlite3.Connection, execution_reference: Reference
    ) -> WorkerRun | None:
        binding = self.database.read(
            connection, "runtime_run", execution_reference.value, ExecutionBinding
        )
        if binding is None:
            return None
        specification = self.database.read(
            connection,
            "work_specification",
            binding.value.specification_reference.value,
            WorkSpecification,
        )
        plan = self.database.read(connection, "data_plan", execution_reference.value, DataPlan)
        if specification is None or plan is None:
            raise conflict()
        return WorkerRun(binding.value, specification.value, plan.value)

    def start(self, command: WorkerRunStart) -> bool:
        run = command.run
        binding = run.binding
        with self.database.transaction(write=True) as connection:
            old = self._run(connection, binding.execution_reference)
            if old is not None:
                if old != run:
                    raise conflict()
                return False  # Readback does not grant a second dispatch or lifecycle change.
            spec = self.database.read(
                connection,
                "work_specification",
                run.specification.reference.value,
                WorkSpecification,
            )
            op = self.database.read(
                connection,
                "opportunity",
                run.specification.task.opportunity_reference.value,
                Opportunity,
            )
            ledger = self.database.read(
                connection, "budget", run.specification.ledger_reference.value, Budget
            )
            if (
                spec is None
                or spec.value != run.specification
                or op != command.opportunity_snapshot
                or ledger != command.ledger_snapshot
            ):
                raise conflict()
            owner = self.database.read(
                connection,
                "runtime_owner",
                run.specification.task.reference.value,
                ExecutionBinding,
            )
            if owner is not None:
                raise conflict()
            # A new binding cannot adopt evidence from another execution path.
            collision = connection.execute(
                "SELECT 1 FROM snapshots WHERE "
                "(kind IN ('execution','data_plan','data_result','work_request','work_response') "
                "AND id=?) OR (kind='deliverable' AND id=?) LIMIT 1",
                (
                    binding.execution_reference.value,
                    composite_key(binding.deliverable_reference.value, 1),
                ),
            ).fetchone()
            if collision is not None:
                raise conflict()
            self._keep(connection, "runtime_owner", run.specification.task.reference.value, binding)
            self._keep(
                connection,
                "runtime_run",
                binding.execution_reference.value,
                binding,
                IndexValues(
                    parent=run.specification.task.opportunity_reference.value,
                    occurred_at=command.started_at,
                ),
            )
            self._keep(
                connection,
                "execution",
                binding.execution_reference.value,
                run.plan.execution,
                IndexValues(
                    parent=run.specification.task.opportunity_reference.value,
                    occurred_at=command.started_at,
                ),
            )
            self._keep(connection, "data_plan", binding.execution_reference.value, run.plan)
            self.database.compare_and_swap(
                connection,
                "opportunity",
                command.opportunity.reference.value,
                command.opportunity,
                command.opportunity_snapshot.revision,
                IndexValues(status=command.opportunity.state.value),
            )
            return True

    def save_result(self, result: WorkerResult) -> bool:
        reference = result.run.binding.execution_reference.value
        with self.database.transaction(write=True) as connection:
            run = self._run(connection, result.run.binding.execution_reference)
            if run is None or run != result.run:
                raise conflict()
            old = self.database.read(connection, "data_result", reference, DataResult)
            if old is not None:
                if old.value != result.result:
                    raise conflict()
                return False
            op = self.database.read(
                connection,
                "opportunity",
                result.run.specification.task.opportunity_reference.value,
                Opportunity,
            )
            if (
                op is None
                or op.value.state != OpportunityState.IN_PROGRESS
                or op.value.execution != result.run.plan.execution
                or op.value.qa is not None
            ):
                raise conflict()
            return self._keep(connection, "data_result", reference, result.result)

    def finish(self, command: WorkerRunFinish) -> bool:
        record = command.retained
        reference = record.run.binding.execution_reference.value
        content = bundle_content(record.result)
        deliverable = command.deliverable
        with self.database.transaction(write=True) as connection:
            run = self._run(connection, record.run.binding.execution_reference)
            result = self.database.read(connection, "data_result", reference, DataResult)
            if run is None or run != record.run or result is None or result.value != record.result:
                raise conflict()
            completed = self.database.read(connection, "runtime_finish", reference, Deliverable)
            if completed is not None:
                if completed.value != deliverable:
                    raise conflict()
                return False
            op = self.database.read(
                connection, "opportunity", command.opportunity.reference.value, Opportunity
            )
            if op != command.opportunity_snapshot:
                raise conflict()
            self._keep(connection, "content", content.reference.value, content)
            self._keep(
                connection,
                "deliverable",
                composite_key(deliverable.reference.value, 1),
                deliverable,
            )
            self.database.compare_and_swap(
                connection,
                "opportunity",
                command.opportunity.reference.value,
                command.opportunity,
                command.opportunity_snapshot.revision,
                IndexValues(status=command.opportunity.state.value),
            )
            self._keep(connection, "runtime_finish", reference, deliverable)
            return True

    def _inspect(
        self, connection: sqlite3.Connection, execution_reference: Reference
    ) -> RuntimeStatus | None:
        run = self._run(connection, execution_reference)
        if run is None:
            return None
        op = self.database.read(
            connection,
            "opportunity",
            run.specification.task.opportunity_reference.value,
            Opportunity,
        )
        if op is None:
            raise conflict()
        result = self.database.read(
            connection, "data_result", execution_reference.value, DataResult
        )
        completed = self.database.read(
            connection, "runtime_finish", execution_reference.value, Deliverable
        )
        if result is not None:
            WorkerResult(run, result.value)
        return RuntimeStatus(
            run, op, None if result is None else result.value, completed is not None
        )

    def inspect(self, execution_reference: Reference) -> RuntimeStatus | None:
        with self.database.transaction() as connection:
            return self._inspect(connection, execution_reference)

    def incomplete(self) -> tuple[RuntimeStatus, ...]:
        # One consistent local read, using the existing snapshot primary keys.
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT id FROM snapshots WHERE kind='runtime_run' ORDER BY id"
            ).fetchall()
            views = tuple(self._inspect(connection, Reference(row["id"])) for row in rows)
            return tuple(view for view in views if view is not None and not view.finished)
