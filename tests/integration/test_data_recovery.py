"""Local data execution, durable replay and recovery without paid providers."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from data_fakes import make_data_world

from agentmine.application.contracts.records import BudgetCommit
from agentmine.application.errors import PortError
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository


@pytest.mark.parametrize("semantic", [False, True])
def test_data_worker_uses_sqlite_and_replays_after_restart(tmp_path: Path, semantic: bool) -> None:
    path = tmp_path / "data.sqlite"
    database = SQLiteDatabase(path)
    world = make_data_world(semantic=semantic, journal=SQLiteDataJournal(database))
    ledger = SQLiteCostLedgerRepository(database)
    ledger.commit(
        BudgetCommit(
            Reference("ledger"), world.ledger.snapshots[Reference("ledger")].value, None, None
        )
    )
    worker = replace(world.worker, budget=replace(world.worker.budget, ledger=ledger))
    result = worker.execute(world.plan)
    snapshot = ledger.get(Reference("ledger"))
    assert result.valid and snapshot is not None and len(snapshot.value.records) == 1
    world.clock.instant += timedelta(days=2)
    reopened = SQLiteDatabase(path)
    resumed = replace(
        worker,
        journal=SQLiteDataJournal(reopened),
        budget=replace(worker.budget, ledger=SQLiteCostLedgerRepository(reopened)),
    )
    assert resumed.execute(world.plan) == result
    assert ledger.get(Reference("ledger")) == snapshot
    assert len(world.llm.calls) == int(semantic)


def test_unknown_semantic_dispatch_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    world = make_data_world(semantic=True, journal=SQLiteDataJournal(SQLiteDatabase(path)))
    world.llm.fail = True
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    resumed = replace(world.worker, journal=SQLiteDataJournal(SQLiteDatabase(path)))
    with pytest.raises(PortError):
        resumed.execute(world.plan)
    assert len(world.llm.calls) == 1


def test_saved_model_response_recovers_failed_ledger_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    world = make_data_world(semantic=True, journal=SQLiteDataJournal(SQLiteDatabase(path)))
    world.llm.break_ledger = world.ledger
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    world.ledger.fail_commit = False
    world.clock.instant += timedelta(days=2)
    resumed = replace(world.worker, journal=SQLiteDataJournal(SQLiteDatabase(path)))
    assert resumed.execute(world.plan).valid
    assert len(world.llm.calls) == 1


def test_concurrent_semantic_claim_has_one_owner(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    SQLiteDatabase(path)
    plan = make_data_world(semantic=True).plan

    def claim(_: int) -> bool:
        return SQLiteDataJournal(SQLiteDatabase(path)).claim_ai(plan)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, range(2))) == [False, True]


def test_plan_changes_cannot_reuse_execution_identity(tmp_path: Path) -> None:
    journal = SQLiteDataJournal(SQLiteDatabase(tmp_path / "data.sqlite"))
    world = make_data_world(journal=journal)
    world.worker.execute(world.plan)
    with pytest.raises(PortError):
        world.worker.execute(replace(world.plan, min_records=0))
