"""Application owns immutable review snapshots and one final decision per review."""

from typing import Protocol

from agentmine.application.contracts.operator import OperatorReview
from agentmine.domain.approval import ApprovalDecision
from agentmine.domain.values import Reference


class ApprovalRepository(Protocol):
    def save_review(self, review: OperatorReview) -> None: ...
    def get_review(self, reference: Reference) -> OperatorReview | None: ...
    def save_decision(self, decision: ApprovalDecision) -> None:
        """Atomic first-decision wins; identical retry allowed, changed decision conflicts."""
        ...

    def get_decision(self, reference: Reference) -> ApprovalDecision | None: ...
