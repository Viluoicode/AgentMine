"""Real-file historical persistence, atomicity, as-of queries and currency grouping."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from history_fakes import MemoryHistory, make_world, progress
from test_use_cases import usd

from agentmine.application.errors import PortError
from agentmine.application.ports.history import HistoricalRepository
from agentmine.application.use_cases.history import (
    CaptureHistoricalObservation,
    GetHistoricalStatistics,
)
from agentmine.domain.history import HistoricalObservation, HistoricalQuery
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.codec import SnapshotCodec
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.history import SQLiteHistoricalRepository


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_application_switches_history_backend_and_keeps_audit(tmp_path: Path, backend: str) -> None:
    world = make_world("tracked")
    progress(world, OpportunityState.PAID)
    path = tmp_path / "history.db"
    history: HistoricalRepository = (
        MemoryHistory() if backend == "memory" else SQLiteHistoricalRepository(SQLiteDatabase(path))
    )
    capture = CaptureHistoricalObservation(
        world.opportunities, world.evaluations, world.ledger, history, world.clock
    )
    first = capture.execute(
        Reference("first"), world.reference, Reference("ledger"), Reference("market")
    )
    world.clock.instant += timedelta(seconds=1)
    second = capture.execute(
        Reference("second"), world.reference, Reference("ledger"), Reference("market")
    )
    if backend == "sqlite":
        history = SQLiteHistoricalRepository(SQLiteDatabase(path))
    assert history.get(first.reference) == first
    assert history.for_opportunity(world.reference) == (first, second)
    assert history.latest(HistoricalQuery()) == (second,)
    assert history.latest(HistoricalQuery(as_of=first.captured_at)) == (first,)
    stats = GetHistoricalStatistics(history).execute()
    assert stats.research.attempts == 1 and stats.research.accepted == 1
    assert stats.costs[0].average_actual_cost == usd("1")
    assert second.verified_reward is not None and second.verified_reward.amount == usd("85")
    with pytest.raises(PortError):
        history.append(replace(first, source=Reference("other-market")), None)
    assert history.for_opportunity(world.reference) == (first, second)


def initial(tmp_path: Path) -> tuple[SQLiteHistoricalRepository, HistoricalObservation]:
    world = make_world("one")
    progress(world, OpportunityState.ACCEPTED)
    repo = SQLiteHistoricalRepository(SQLiteDatabase(tmp_path / "history.db"))
    observation = CaptureHistoricalObservation(
        world.opportunities, world.evaluations, world.ledger, repo, world.clock
    ).execute(Reference("first"), world.reference, Reference("ledger"), Reference("market"))
    return repo, observation


def test_concurrent_sequence_is_single_writer(tmp_path: Path) -> None:
    repo, first = initial(tmp_path)

    def append(index: int) -> bool:
        candidate = replace(first, reference=Reference(f"next-{index}"), sequence=2)
        store = SQLiteHistoricalRepository(SQLiteDatabase(tmp_path / "history.db"))
        try:
            store.append(candidate, first.reference)
            return True
        except PortError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(append, (1, 2))) == [False, True]
    assert len(repo.for_opportunity(first.opportunity.reference)) == 2
    assert repo.latest(HistoricalQuery())[0].sequence == 2


def test_latest_write_failure_rolls_back_observation(tmp_path: Path) -> None:
    repo, first = initial(tmp_path)
    second = replace(first, reference=Reference("second"), sequence=2)
    with repo.database.transaction(write=True) as connection:
        connection.execute(
            "CREATE TRIGGER fail_history BEFORE INSERT ON snapshots "
            "WHEN NEW.kind = 'historical_latest' "
            "BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(PortError):
        repo.append(second, first.reference)
    assert repo.get(second.reference) is None
    assert repo.latest(HistoricalQuery()) == (first,)
    with repo.database.transaction(write=True) as connection:
        connection.execute("DROP TRIGGER fail_history")
    repo.append(second, first.reference)
    repo.append(second, first.reference)
    assert repo.latest(HistoricalQuery()) == (second,)


def test_currency_cohorts_never_blend(tmp_path: Path) -> None:
    repo, usd_observation = initial(tmp_path)
    # Synthetic second fixture uses the same arithmetic with an explicit EUR currency.
    codec = SnapshotCodec()
    payload = codec.dumps(usd_observation).replace('"USD"', '"EUR"').replace('"one"', '"euro-one"')
    euro = codec.loads(payload, HistoricalObservation)
    euro = replace(euro, reference=Reference("euro-first"))
    repo.append(euro, None)
    costs = GetHistoricalStatistics(repo).execute().costs
    assert tuple(item.currency for item in costs) == ("EUR", "USD")
    assert all(item.actual_samples == 1 and item.predicted_samples == 1 for item in costs)
