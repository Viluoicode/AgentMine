"""Durable operator review/decision audit with atomic immutable decisions."""

from dataclasses import dataclass

from agentmine.application.contracts.operator import OperatorReview
from agentmine.domain.approval import ApprovalDecision
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class SQLiteApprovalRepository:
    database: SQLiteDatabase

    def save_review(self, review: OperatorReview) -> None:
        self.database.immutable("operator_review", review.reference.value, review)

    def get_review(self, reference: Reference) -> OperatorReview | None:
        item = self.database.get("operator_review", reference.value, OperatorReview)
        return None if item is None else item.value

    def save_decision(self, decision: ApprovalDecision) -> None:
        self.database.immutable("operator_decision", decision.review_reference.value, decision)

    def get_decision(self, reference: Reference) -> ApprovalDecision | None:
        item = self.database.get("operator_decision", reference.value, ApprovalDecision)
        return None if item is None else item.value
