"""Opportunity snapshots/provenance plus local operational read patterns."""

from dataclasses import dataclass
from decimal import Decimal

from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.contracts.records import OpportunitySave, Versioned
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase


@dataclass(frozen=True, slots=True)
class SQLiteOpportunityRepository:
    database: SQLiteDatabase

    def get(self, reference: Reference) -> Versioned[Opportunity] | None:
        return self.database.get("opportunity", reference.value, Opportunity)

    def save(self, request: OpportunitySave) -> Versioned[Opportunity]:
        with self.database.transaction(write=True) as connection:
            return self.database.compare_and_swap(
                connection,
                "opportunity",
                request.opportunity.reference.value,
                request.opportunity,
                request.expected_revision,
                IndexValues(status=request.opportunity.state.value),
            )

    def save_observation(self, observation: OpportunityObservation) -> None:
        self.database.immutable(
            "observation",
            observation.opportunity.reference.value,
            observation,
            IndexValues(
                source=observation.source_reference.value, occurred_at=observation.observed_at
            ),
        )

    def get_observation(self, reference: Reference) -> OpportunityObservation | None:
        result = self.database.get("observation", reference.value, OpportunityObservation)
        return None if result is None else result.value

    def list_by_status(self, status: OpportunityState) -> tuple[Opportunity, ...]:
        return tuple(
            item.value
            for item in self.database.find("opportunity", Opportunity, status=status.value)
        )

    def list_eligible(self) -> tuple[Opportunity, ...]:
        return self.list_by_status(OpportunityState.ELIGIBLE)

    def list_waiting_for_budget(self) -> tuple[Opportunity, ...]:
        return self.list_by_status(OpportunityState.WAITING_FOR_BUDGET)

    def submissions_awaiting_review(self) -> tuple[Opportunity, ...]:
        return self.list_by_status(OpportunityState.READY_FOR_HUMAN_REVIEW)

    def accepted_but_unpaid(self) -> tuple[Opportunity, ...]:
        return self.list_by_status(OpportunityState.ACCEPTED)

    def list_highest_scoring(self, limit: int = 20) -> tuple[Opportunity, ...]:
        if type(limit) is not int or limit < 1:
            raise ValueError("Positive result limit required")
        items = [
            item.value
            for item in self.database.find("opportunity", Opportunity)
            if item.value.score is not None
        ]
        # Exact Decimal order; SQLite REAL would lose precision. Reference breaks ties.
        items.sort(key=lambda item: item.reference.value)
        items.sort(key=lambda item: item.score or Decimal(0), reverse=True)
        return tuple(items[:limit])

    def list_by_source(self, source_reference: Reference) -> tuple[Opportunity, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """SELECT op.* FROM snapshots op JOIN snapshots source ON
                   source.kind = 'observation' AND source.id = op.id
                   WHERE op.kind = 'opportunity' AND source.source = ? ORDER BY op.id""",
                (source_reference.value,),
            ).fetchall()
            return tuple(self.database.decode(row, Opportunity).value for row in rows)

    def verified_revenue(self, currency: str) -> Money:
        total = Money(Decimal(0), currency)
        for item in self.list_by_status(OpportunityState.PAID):
            revenue = item.verified_revenue
            if revenue.currency == currency:
                total = total + revenue
        return total
