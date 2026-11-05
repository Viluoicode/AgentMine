"""Offline C3 composition: real SQLite/BudgetManager/DataWorker, test-only clock."""

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import cast

from fakes import FakeClock
from test_data_partition import CaseFixture, plan_for

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.data import DataPlan, LookupEntry
from agentmine.application.contracts.records import BudgetCommit
from agentmine.application.workers.data import DataWorker
from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.money import Money
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository


class ArtifactCase(CaseFixture):
    variant: str
    inventory: list[str]


FIXTURES = Path(__file__).resolve().parents[2] / "contract/fixtures/data_partition_c3"
CASES = cast(list[ArtifactCase], json.loads((FIXTURES / "cases.json").read_text()))


def artifact_plan(case: ArtifactCase) -> DataPlan:
    plan = plan_for(case)
    cols = list(plan.columns)
    if case["variant"] == "negative":
        cols[3] = replace(cols[3], minimum=None)
    elif case["variant"] == "lookup":
        cols[1] = replace(
            cols[1],
            lookup=(LookupEntry("acc", "accessory"),),
            lookup_evidence=Reference("fixture:approved-title-map"),
        )
    elif case["variant"] == "nested":
        cols = [replace(c, path=("product", c.name)) for c in cols]
    return replace(plan, columns=tuple(cols))


@dataclass
class World:
    database: SQLiteDatabase
    budget: BudgetManager
    clock: FakeClock
    plan: DataPlan

    def worker(self) -> DataWorker:
        return DataWorker(self.budget, SQLiteDataJournal(self.database), llm=None)


def world(path: Path, case: ArtifactCase) -> World:
    plan = artifact_plan(case)
    clock = FakeClock(plan.execution.started_at)
    database = SQLiteDatabase(path / "artifacts.sqlite3")
    ledger = SQLiteCostLedgerRepository(database)
    zero = Money(Decimal(0), "USD")
    budget = Budget(BudgetPolicy(zero, zero, zero, zero), OperatingMode.SCOUT_ONLY)
    ledger.commit(BudgetCommit(Reference("ledger"), budget, None, None))
    manager = BudgetManager(ledger, Reference("ledger"), clock)
    decision = manager.authorize(zero, plan.execution.authorization.request.context)
    assert decision.authorization is not None
    plan = replace(
        plan,
        execution=replace(plan.execution, authorization=decision.authorization, mode=decision.mode),
    )
    return World(database, manager, clock, plan)
