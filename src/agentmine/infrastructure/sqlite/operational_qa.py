"""Atomic version ownership and conditional QA application on the shared SQLite file."""

import sqlite3
from dataclasses import dataclass

from agentmine.application.contracts.operational_qa import QAApplicationBinding, QACompletion
from agentmine.application.contracts.qa import QAInspection, lifecycle_qa_result
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.qa import QAReport
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key


def conflict() -> PortError:
    return PortError(
        PortErrorCode.CONFLICT,
        "operational_qa",
        "QA identity, evidence or Opportunity revision changed",
    )


@dataclass(frozen=True, slots=True)
class SQLiteOperationalQARepository:
    database: SQLiteDatabase

    def _keep(
        self,
        connection: sqlite3.Connection,
        kind: str,
        reference: str,
        value: object,
        indexes: IndexValues | None = None,
    ) -> None:
        existing = self.database.read(connection, kind, reference, type(value))
        if existing is not None:
            if existing.value != value:
                raise conflict()
            return
        self.database.write(connection, kind, reference, value, 1, indexes or IndexValues())

    def get_binding(self, inspection: Reference) -> QAApplicationBinding | None:
        row = self.database.get("operational_qa_binding", inspection.value, QAApplicationBinding)
        return None if row is None else row.value

    def for_execution(self, execution: Reference) -> QAApplicationBinding | None:
        rows = self.database.find(
            "operational_qa_binding", QAApplicationBinding, parent=execution.value
        )
        if len(rows) > 1:
            raise conflict()
        return None if not rows else rows[0].value

    def get_inspection(self, inspection: Reference) -> QAInspection | None:
        row = self.database.get("qa_inspection", inspection.value, QAInspection)
        return None if row is None else row.value

    def applied(self, inspection: Reference) -> bool:
        row = self.database.get("operational_qa_applied", inspection.value, Reference)
        if row is not None and row.value != inspection:
            raise conflict()
        return row is not None

    def claim(self, binding: QAApplicationBinding, inspection: QAInspection) -> bool:
        if (
            inspection.reference != binding.reference
            or inspection.deliverable != binding.deliverable
            or inspection.plan.execution != binding.opportunity_snapshot.value.execution
        ):
            raise conflict()
        with self.database.transaction(write=True) as connection:
            old = self.database.read(
                connection, "operational_qa_binding", binding.reference.value, QAApplicationBinding
            )
            retained = self.database.read(
                connection, "qa_inspection", binding.reference.value, QAInspection
            )
            if old is not None:
                if old.value != binding or retained is None or retained.value != inspection:
                    raise conflict()
                return False
            current = self.database.read(
                connection,
                "opportunity",
                binding.opportunity_snapshot.value.reference.value,
                Opportunity,
            )
            if current != binding.opportunity_snapshot or retained is not None:
                raise conflict()
            version = composite_key(
                binding.deliverable.reference.value, binding.deliverable.version
            )
            occupied = connection.execute(
                "SELECT 1 FROM snapshots WHERE (kind='operational_qa_owner' AND id=?) "
                "OR (kind='qa' AND id=?) OR (kind='qa_report' AND id=?) "
                "OR (kind='qa_ai_response' AND id=?) LIMIT 1",
                (version, version, binding.reference.value, binding.reference.value),
            ).fetchone()
            if occupied is not None:
                raise conflict()
            self._keep(connection, "operational_qa_owner", version, binding.reference)
            self._keep(connection, "qa_inspection", binding.reference.value, inspection)
            self._keep(
                connection,
                "operational_qa_binding",
                binding.reference.value,
                binding,
                IndexValues(
                    parent=binding.execution_reference.value, occurred_at=binding.requested_at
                ),
            )
            return True

    def complete(self, completion: QACompletion) -> bool:
        binding = completion.binding
        with self.database.transaction(write=True) as connection:
            retained = self.database.read(
                connection, "operational_qa_binding", binding.reference.value, QAApplicationBinding
            )
            inspection = self.database.read(
                connection, "qa_inspection", binding.reference.value, QAInspection
            )
            report = self.database.read(connection, "qa_report", binding.reference.value, QAReport)
            if (
                retained is None
                or retained.value != binding
                or inspection is None
                or inspection.value != completion.inspection
                or report is None
                or report.value != completion.report
            ):
                raise conflict()
            marker = self.database.read(
                connection, "operational_qa_applied", binding.reference.value, Reference
            )
            if marker is not None:
                if marker.value != binding.reference:
                    raise conflict()
                return False
            current = self.database.read(
                connection,
                "opportunity",
                binding.opportunity_snapshot.value.reference.value,
                Opportunity,
            )
            if current != binding.opportunity_snapshot:
                raise conflict()
            result = lifecycle_qa_result(completion.report)
            if result is not None:
                self._keep(
                    connection,
                    "qa",
                    composite_key(binding.deliverable.reference.value, binding.deliverable.version),
                    result,
                )
                updated = completion.opportunity
                self.database.compare_and_swap(
                    connection,
                    "opportunity",
                    updated.reference.value,
                    updated,
                    binding.opportunity_snapshot.revision,
                    IndexValues(status=updated.state.value),
                )
            self._keep(
                connection, "operational_qa_applied", binding.reference.value, binding.reference
            )
            return True
