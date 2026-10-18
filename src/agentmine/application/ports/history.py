"""Business-owned historical storage and a read-only future scoring boundary."""

from typing import Protocol

from agentmine.domain.history import HistoricalObservation, HistoricalQuery
from agentmine.domain.history_statistics import HistoricalStatistics
from agentmine.domain.values import Reference


class HistoricalRepository(Protocol):
    def get(self, reference: Reference) -> HistoricalObservation | None: ...
    def for_opportunity(self, reference: Reference) -> tuple[HistoricalObservation, ...]: ...
    def append(
        self, observation: HistoricalObservation, expected_previous: Reference | None
    ) -> None:
        """Atomically retain immutable observation and advance latest; reject stale writers.

        Enforce require_successor before writing; identical ID retries are idempotent.
        """
        ...

    def latest(self, query: HistoricalQuery) -> tuple[HistoricalObservation, ...]:
        """One observation per opportunity, as known at query.as_of, then apply filters."""
        ...


class HistoricalPerformance(Protocol):
    def statistics(self, query: HistoricalQuery) -> HistoricalStatistics:
        """Descriptive rates/counts, not an automatically calibrated scoring signal."""
        ...
