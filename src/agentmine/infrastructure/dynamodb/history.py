"""Historical evidence and per-opportunity sequence advanced atomically."""

from dataclasses import dataclass

from agentmine.domain.history import HistoricalObservation, HistoricalQuery, latest_observations
from agentmine.domain.values import Reference
from agentmine.infrastructure.dynamodb.store import (
    DynamoStore,
    IndexValues,
    conflict,
    identity,
    key,
    timestamp,
)


@dataclass(frozen=True)
class DynamoDBHistoricalRepository:
    database: DynamoStore

    def get(self, reference: Reference) -> HistoricalObservation | None:
        return self.database.value("historical_observation", reference.value, HistoricalObservation)

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
        original = self.get(observation.reference)
        if original is not None:
            if original != observation:
                raise conflict()
            return
        identifier = observation.opportunity.reference.value
        prior = self.database.get("historical_latest", identifier, HistoricalObservation)
        if (None if prior is None else prior.value.reference) != expected_previous:
            raise conflict()
        observation.require_successor(None if prior is None else prior.value)
        items = self.database.evidence(
            "historical_observation",
            observation.reference.value,
            observation,
            IndexValues(identifier, observation.captured_at),
        )
        items.append(
            self.database.item(
                "HIST",
                timestamp(observation.captured_at) + "#" + identity(observation.reference.value),
                observation,
            )
        )
        actions = [self.database.put(item) for item in items]
        actions.append(
            self.database.put(
                self.database.item(
                    *key("historical_latest", identifier),
                    observation,
                    1 if prior is None else prior.revision + 1,
                ),
                revision=None if prior is None else prior.revision,
            )
        )
        self.database.transact(actions)

    def latest(self, query: HistoricalQuery) -> tuple[HistoricalObservation, ...]:
        return latest_observations(
            tuple(
                self.database.decode(item, HistoricalObservation).value
                for item in self.database.query("HIST")
            ),
            query,
        )
