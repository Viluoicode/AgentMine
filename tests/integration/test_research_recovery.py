"""Research recovery with durable checkpoints and the real local cost ledger."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from test_research_worker import make_world

from agentmine.application.contracts.records import BudgetCommit
from agentmine.application.contracts.research import ResearchClaim
from agentmine.application.errors import PortError
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.research import SQLiteResearchJournal


def test_worker_reopen_reuses_artifacts_and_costs(tmp_path: Path) -> None:
    path = tmp_path / "research.sqlite"
    database = SQLiteDatabase(path)
    journal = SQLiteResearchJournal(database)
    world = make_world(journal)
    ledger = SQLiteCostLedgerRepository(database)
    ledger.commit(
        BudgetCommit(
            Reference("ledger"), world.ledger.snapshots[Reference("ledger")].value, None, None
        )
    )
    worker = replace(world.worker, budget=replace(world.worker.budget, ledger=ledger))
    result = worker.execute(world.plan)
    reopened = SQLiteDatabase(path)
    recovered = replace(
        worker,
        journal=SQLiteResearchJournal(reopened),
        budget=replace(worker.budget, ledger=SQLiteCostLedgerRepository(reopened)),
    )
    assert recovered.execute(world.plan) == result
    assert len(world.tool.calls) == len(world.llm.calls) == 1
    snapshot = ledger.get(Reference("ledger"))
    assert snapshot is not None and len(snapshot.value.records) == 2


def test_unknown_claim_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "research.sqlite"
    world = make_world(SQLiteResearchJournal(SQLiteDatabase(path)))
    world.tool.fail = True
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    worker = replace(world.worker, journal=SQLiteResearchJournal(SQLiteDatabase(path)))
    with pytest.raises(PortError):
        worker.execute(world.plan)
    assert len(world.tool.calls) == 1


def test_concurrent_claim_has_one_owner(tmp_path: Path) -> None:
    path = tmp_path / "research.sqlite"
    world = make_world()
    SQLiteDatabase(path)
    claim = ResearchClaim(world.plan, world.plan.sources[0].operation_reference)

    def compete(_: int) -> bool:
        return SQLiteResearchJournal(SQLiteDatabase(path)).claim(claim)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(compete, range(2))) == [False, True]


def test_conflicting_snapshot_rejected(tmp_path: Path) -> None:
    journal = SQLiteResearchJournal(SQLiteDatabase(tmp_path / "research.sqlite"))
    world = make_world(journal)
    journal.save_plan(world.plan)
    with pytest.raises(PortError):
        journal.save_plan(replace(world.plan, questions=("Different question",)))
