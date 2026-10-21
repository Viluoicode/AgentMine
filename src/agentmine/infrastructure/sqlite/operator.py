"""One SQLite transaction supplies a complete operator reporting snapshot."""

from dataclasses import dataclass

from agentmine.application.contracts.dashboard import OperatorSnapshot
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.budget import Budget
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class SQLiteOperatorReadRepository:
    database: SQLiteDatabase

    def read(self, ledger_reference: Reference) -> OperatorSnapshot:
        with self.database.transaction() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM snapshots WHERE kind = 'budget'"
            ).fetchone()[0]
            if count != 1:
                raise PortError(
                    PortErrorCode.UNSUPPORTED,
                    "dashboard",
                    "Dashboard requires exactly one workspace budget ledger",
                )
            budget = self.database.read(connection, "budget", ledger_reference.value, Budget)
            if budget is None:
                raise PortError(PortErrorCode.UNAVAILABLE, "dashboard", "Budget ledger missing")
            rows = connection.execute(
                "SELECT * FROM snapshots WHERE kind = 'opportunity' ORDER BY id"
            ).fetchall()
            return OperatorSnapshot(
                tuple(self.database.decode(row, Opportunity).value for row in rows), budget.value
            )
