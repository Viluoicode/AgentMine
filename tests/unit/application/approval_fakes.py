"""Test-only approval audit with immutable decisions."""

from dataclasses import dataclass, field

from fakes import put

from agentmine.application.contracts.operator import OperatorReview
from agentmine.domain.approval import ApprovalDecision
from agentmine.domain.values import Reference


@dataclass
class MemoryApprovals:
    reviews: dict[Reference, OperatorReview] = field(default_factory=dict)
    decisions: dict[Reference, ApprovalDecision] = field(default_factory=dict)

    def save_review(self, review: OperatorReview) -> None:
        put(self.reviews, review.reference, review)

    def get_review(self, reference: Reference) -> OperatorReview | None:
        return self.reviews.get(reference)

    def save_decision(self, decision: ApprovalDecision) -> None:
        put(self.decisions, decision.review_reference, decision)

    def get_decision(self, reference: Reference) -> ApprovalDecision | None:
        return self.decisions.get(reference)
