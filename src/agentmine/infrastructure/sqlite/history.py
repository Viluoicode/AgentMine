"""Immutable historical snapshots with an atomic per-opportunity sequence."""

from dataclasses import dataclass

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.history import HistoricalObservation, HistoricalQuery, latest_observations
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase


@dataclass(frozen=True, slots=True)
class SQLiteHistoricalRepository:
    database: SQLiteDatabase

    def get(self, reference: Reference) -> HistoricalObservation | None:
        item = self.database.get("historical_observation", reference.value, HistoricalObservation)
        return None if item is None else item.value

    def for_opportunity(self, reference: Reference) -> tuple[HistoricalObservation, ...]:
        return tuple(
            sorted(
                (
                    item.value
                    for item in self.database.find(
                        "historical_observation", HistoricalObservation, parent=reference.value
                    )
                ),
                key=lambda item: item.sequence,
            )
        )

    def append(
        self, observation: HistoricalObservation, expected_previous: Reference | None
    ) -> None:
        with self.database.transaction(write=True) as connection:
            original = self.database.read(
                connection,
                "historical_observation",
                observation.reference.value,
                HistoricalObservation,
            )
            if original is not None:
                if original.value != observation:
                    raise PortError(
                        PortErrorCode.CONFLICT, "history", "Observation identity changed"
                    )
                return
            key = observation.opportunity.reference.value
            prior = self.database.read(connection, "historical_latest", key, HistoricalObservation)
            if (None if prior is None else prior.value.reference) != expected_previous:
                raise PortError(
                    PortErrorCode.CONFLICT,
                    "history",
                    "Historical sequence changed; reload before capture",
                )
            observation.require_successor(None if prior is None else prior.value)
            indexes = IndexValues(
                parent=key, occurred_at=observation.captured_at, source=observation.source.value
            )
            self.database.write(
                connection,
                "historical_observation",
                observation.reference.value,
                observation,
                1,
                indexes,
            )
            self.database.compare_and_swap(
                connection,
                "historical_latest",
                key,
                observation,
                None if prior is None else prior.revision,
                indexes,
            )

    def latest(self, query: HistoricalQuery) -> tuple[HistoricalObservation, ...]:
        items = tuple(
            item.value
            for item in self.database.find("historical_observation", HistoricalObservation)
        )
        return latest_observations(items, query)
