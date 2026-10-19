"""Budget CAS, audit and cost projections form one atomic transaction."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from agentmine.application.contracts.records import BudgetCommit, Versioned
from agentmine.domain.budget import Budget
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.infrastructure.dynamodb.store import (
    DynamoStore,
    collection,
    conflict,
    identity,
    key,
    timestamp,
)


@dataclass(frozen=True)
class DynamoDBCostLedgerRepository:
    database: DynamoStore

    def get(self, ledger_reference: Reference) -> Versioned[Budget] | None:
        return self.database.get("budget", ledger_reference.value, Budget)

    def commit(self, request: BudgetCommit) -> Versioned[Budget]:
        old = self.get(request.ledger_reference)
        if (None if old is None else old.revision) != request.expected_revision:
            raise conflict()
        previous = (
            {} if old is None else {record.cost.reference: record for record in old.value.records}
        )
        current = {record.cost.reference: record for record in request.budget.records}
        if any(current.get(ref) != value for ref, value in previous.items()):
            raise conflict()  # Never erase or rewrite an actual cost projection.
        revision = (request.expected_revision or 0) + 1
        ledger = request.ledger_reference.value
        actions = [
            self.database.put(
                self.database.item(*key("budget", ledger), request.budget, revision),
                revision=request.expected_revision,
            ),
            self.database.put(
                self.database.item(
                    collection("budget_audit", ledger), str(revision).zfill(20), request, revision
                )
            ),
        ]
        for ref, record in current.items():
            if ref not in previous:
                actions.append(
                    self.database.put(
                        self.database.item(
                            collection("cost", ledger),
                            timestamp(record.context.occurred_at) + "#" + identity(ref.value),
                            record,
                        )
                    )
                )
        self.database.transact(actions)
        return Versioned(request.budget, revision)

    def history(self, ledger_reference: Reference) -> tuple[Versioned[BudgetCommit], ...]:
        return tuple(
            self.database.decode(item, BudgetCommit)
            for item in self.database.query(collection("budget_audit", ledger_reference.value))
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
            raise ValueError("Increasing nonempty period required")
        records = (
            self.database.decode(item, CostRecord).value
            for item in self.database.query(
                collection("cost", ledger_reference.value),
                start=timestamp(start),
                end=timestamp(end),
            )
        )
        return tuple(
            sorted(
                (
                    record
                    for record in records
                    if start <= record.context.occurred_at < end
                    and (category is None or record.cost.category == category)
                ),
                key=lambda record: (record.context.occurred_at, record.cost.reference.value),
            )
        )

    def monthly_cost(
        self,
        ledger_reference: Reference,
        year: int,
        month: int,
        category: CostCategory | None = None,
    ) -> Money | None:
        datetime(year, month, 1)
        snapshot = self.get(ledger_reference)
        if snapshot is None:
            return None
        zone = snapshot.value.policy.calendar_timezone
        start = datetime(year, month, 1, tzinfo=zone)
        end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=zone)
        total = Money(Decimal(0), snapshot.value.policy.monthly_ai_budget.currency)
        for record in self.costs_by_period(ledger_reference, start, end, category):
            total += record.actual_cost
        return total
