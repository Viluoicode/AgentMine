"""Immutable evaluations with chronological opportunity history."""

from dataclasses import dataclass

from agentmine.application.contracts.records import EvaluationRecord
from agentmine.domain.values import Reference
from agentmine.infrastructure.dynamodb.store import DynamoStore, IndexValues


@dataclass(frozen=True, slots=True)
class DynamoDBEvaluationRepository:
    database: DynamoStore

    def save(self, evaluation: EvaluationRecord) -> None:
        self.database.immutable(
            "evaluation",
            evaluation.reference.value,
            evaluation,
            IndexValues(
                parent=evaluation.opportunity_reference.value, occurred_at=evaluation.evaluated_at
            ),
        )

    def get(self, reference: Reference) -> EvaluationRecord | None:
        result = self.database.get("evaluation", reference.value, EvaluationRecord)
        return None if result is None else result.value

    def for_opportunity(self, reference: Reference) -> tuple[EvaluationRecord, ...]:
        return tuple(
            item.value
            for item in self.database.find("evaluation", EvaluationRecord, parent=reference.value)
        )
