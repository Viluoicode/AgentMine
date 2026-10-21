"""Atomic budget state/audit commits and exact actual-cost read patterns."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from agentmine.application.contracts.records import BudgetCommit, Versioned
from agentmine.domain.budget import Budget
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key


@dataclass(frozen=True, slots=True)
class SQLiteCostLedgerRepository:
    database: SQLiteDatabase

    def count(self) -> int:
        """Local composition guard for the single-ledger operator interface."""
        with self.database.transaction() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE kind = 'budget'"
                ).fetchone()[0]
            )

    def get(self, ledger_reference: Reference) -> Versioned[Budget] | None:
        return self.database.get("budget", ledger_reference.value, Budget)

    def commit(self, request: BudgetCommit) -> Versioned[Budget]:
        with self.database.transaction(write=True) as connection:
            result = self.database.compare_and_swap(
                connection,
                "budget",
                request.ledger_reference.value,
                request.budget,
                request.expected_revision,
            )
            # History includes initialization, policy changes and release-only commits.
            self.database.write(
                connection,
                "budget_audit",
                composite_key(request.ledger_reference.value, result.revision),
                request,
                result.revision,
                IndexValues(parent=request.ledger_reference.value),
            )
            return result

    def history(self, ledger_reference: Reference) -> tuple[Versioned[BudgetCommit], ...]:
        return tuple(
            sorted(
                self.database.find("budget_audit", BudgetCommit, parent=ledger_reference.value),
                key=lambda item: item.revision,
            )
        )

    def costs_by_period(
        self,
        ledger_reference: Reference,
        start: datetime,
        end: datetime,
        category: CostCategory | None = None,
    ) -> tuple[CostRecord, ...]:
        require_aware_timestamp(start)
        require_aware_timestamp(end)
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        if end <= start:
            raise ValueError("Period must be nonempty and increasing")
        snapshot = self.get(ledger_reference)
        if snapshot is None:
            return ()
        return tuple(
            sorted(
                (
                    record
                    for record in snapshot.value.records
                    if start <= record.context.occurred_at.astimezone(UTC) < end
                    and (category is None or record.cost.category == category)
                ),
                key=lambda record: (
                    record.context.occurred_at.astimezone(UTC),
                    record.cost.reference.value,
                ),
            )
        )

    def monthly_cost(
        self,
        ledger_reference: Reference,
        year: int,
        month: int,
        category: CostCategory | None = None,
    ) -> Money | None:
        # Period is the budget's configured local calendar; actuals only, all categories
        # unless requested otherwise. Missing ledger is not a zero-cost report.
        datetime(year, month, 1)  # Validate caller's calendar inputs.
        snapshot = self.get(ledger_reference)
        if snapshot is None:
            return None
        budget = snapshot.value
        total = Money(Decimal(0), budget.policy.monthly_ai_budget.currency)
        for record in budget.records:
            local = record.context.occurred_at.astimezone(budget.policy.calendar_timezone)
            if (local.year, local.month) == (year, month) and (
                category is None or record.cost.category == category
            ):
                total = total + record.actual_cost
        return total
