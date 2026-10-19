"""Authoritative aggregate writes and sparse operational access patterns."""

from dataclasses import dataclass
from decimal import Decimal

from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.contracts.records import OpportunitySave, Versioned
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.infrastructure.dynamodb.store import DynamoStore, conflict, identity, key, wire


@dataclass(frozen=True)
class DynamoDBOpportunityRepository:
    database: DynamoStore

    def get(self, reference: Reference) -> Versioned[Opportunity] | None:
        return self.database.get("opportunity", reference.value, Opportunity)

    def save(self, request: OpportunitySave) -> Versioned[Opportunity]:
        op = request.opportunity
        previous = self.get(op.reference)
        if (None if previous is None else previous.revision) != request.expected_revision:
            raise conflict()
        revision = (request.expected_revision or 0) + 1
        item = self.database.item(*key("opportunity", op.reference.value), op, revision)
        item.update({"GSI1PK": "STATE#" + op.state.value, "GSI1SK": identity(op.reference.value)})
        if op.score is not None:
            # No Decimal.normalize(): its context can round long exact scores.
            integer, _, fraction = format(op.score, "f").partition(".")
            item.update(
                {
                    "GSI3PK": "SCORE",
                    "GSI3SK": integer.zfill(3)
                    + "."
                    + fraction.rstrip("0")
                    + "#"
                    + identity(op.reference.value),
                }
            )
        actions = [self.database.put(item, revision=request.expected_revision)]
        if previous is not None and previous.value.currency != op.currency:
            actions.append(
                {
                    "Delete": {
                        "TableName": self.database.table,
                        "Key": wire(
                            {
                                "PK": "PAID#" + previous.value.currency,
                                "SK": identity(op.reference.value),
                            }
                        ),
                    }
                }
            )
        paid_pk, paid_sk = "PAID#" + op.currency, identity(op.reference.value)
        if op.state == OpportunityState.PAID:
            # No separate mutable counter: authoritative paid projections retain proof.
            projection = self.database.item(paid_pk, paid_sk, op, revision)
            actions.append({"Put": {"TableName": self.database.table, "Item": wire(projection)}})
        else:
            actions.append(
                {
                    "Delete": {
                        "TableName": self.database.table,
                        "Key": wire({"PK": paid_pk, "SK": paid_sk}),
                    }
                }
            )
        self.database.transact(actions)
        return Versioned(op, revision)

    def save_observation(self, observation: OpportunityObservation) -> None:
        item = self.database.item(
            *key("observation", observation.opportunity.reference.value), observation
        )
        item.update(
            {
                "GSI2PK": "SOURCE#" + identity(observation.source_reference.value),
                "GSI2SK": identity(observation.opportunity.reference.value),
            }
        )
        # Same evidence remains immutable; index attributes are deterministic.
        self.database.transact([self.database.put(item, identical=True)])

    def get_observation(self, reference: Reference) -> OpportunityObservation | None:
        return self.database.value("observation", reference.value, OpportunityObservation)

    def list_by_status(self, status: OpportunityState) -> tuple[Opportunity, ...]:
        result = []
        for index_item in self.database.query("STATE#" + status.value, index="GSI1"):
            item = self.database.raw(str(index_item["PK"]), str(index_item["SK"]))
            if item is not None:
                op = self.database.decode(item, Opportunity).value
                if op.state == status:
                    result.append(op)
        return tuple(sorted(result, key=lambda op: op.reference.value))

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
        result = []
        for index_item in self.database.query("SCORE", index="GSI3"):
            item = self.database.raw(str(index_item["PK"]), str(index_item["SK"]))
            if item is not None:
                op = self.database.decode(item, Opportunity).value
                if op.score is not None:
                    result.append(op)
        result.sort(key=lambda op: op.reference.value)
        result.sort(key=lambda op: op.score or Decimal(0), reverse=True)
        return tuple(result[:limit])

    def list_by_source(self, source_reference: Reference) -> tuple[Opportunity, ...]:
        result = []
        for index_item in self.database.query(
            "SOURCE#" + identity(source_reference.value), index="GSI2"
        ):
            item = self.database.raw(str(index_item["PK"]), str(index_item["SK"]))
            if item is not None:
                observation = self.database.decode(item, OpportunityObservation).value
                op = self.get(observation.opportunity.reference)
                if op is not None:
                    result.append(op.value)
        return tuple(sorted(result, key=lambda op: op.reference.value))

    def verified_revenue(self, currency: str) -> Money:
        total = Money(Decimal(0), currency)
        for item in self.database.query("PAID#" + currency):
            total += self.database.decode(item, Opportunity).value.verified_revenue
        return total
