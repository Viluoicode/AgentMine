"""Validate persisted operator consent before protected application actions."""

from dataclasses import dataclass, replace

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.approval import ApprovalRepository
from agentmine.application.ports.services import Clock
from agentmine.domain.approval import ApprovalAction, ApprovalScope, OperatorDecision
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostContext
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class ApprovalGuard:
    approvals: ApprovalRepository
    clock: Clock

    def require(self, reference: Reference, scope: ApprovalScope) -> None:
        review = self.approvals.get_review(reference)
        decision = self.approvals.get_decision(reference)
        if (
            review is None
            or decision is None
            or review.reference != reference
            or decision.review_reference != reference
            or review.scope != scope
            or decision.decision != OperatorDecision.APPROVE
            or not review.requested_at <= decision.decided_at <= self.clock.now()
        ):
            raise PortError(
                PortErrorCode.CONFLICT, "approval", "Matching recorded operator approval required"
            )

    def require_spending(
        self,
        reference: Reference,
        ledger: Reference,
        amount: Money,
        category: CostCategory,
        context: CostContext,
    ) -> None:
        review = self.approvals.get_review(reference)
        if review is None or review.scope.action != ApprovalAction.SPENDING:
            raise PortError(PortErrorCode.CONFLICT, "approval", "Spending approval required")
        self.require(reference, review.scope)
        request = review.scope.spending
        assert request is not None
        request.estimated_cost.require_same_currency(amount)
        if (
            review.scope.destination != ledger
            or request.category != category
            or not request.context.matches_operation(replace(context, human_approval=None))
            or amount.amount > request.estimated_cost.amount
        ):
            raise PortError(
                PortErrorCode.CONFLICT, "approval", "Spending scope exceeds approved request"
            )
