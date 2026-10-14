"""Persisted spending coordination; no model, SDK or pricing policy."""

from dataclasses import dataclass, replace
from datetime import datetime

from agentmine.application.contracts.records import BudgetCommit, Versioned
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.repositories import CostLedgerRepository
from agentmine.application.ports.services import Clock
from agentmine.domain.budget import AuthorizationDecision, Budget, BudgetAuthorization
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import AuthorizationStatus, CostContext, CostRecord
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class BudgetManager:
    ledger: CostLedgerRepository
    ledger_reference: Reference
    clock: Clock

    def _load(self) -> Versioned[Budget]:
        snapshot = self.ledger.get(self.ledger_reference)
        if snapshot is None:
            raise PortError(PortErrorCode.UNAVAILABLE, "budget", "Budget ledger missing")
        return snapshot

    def authorize(
        self, estimated_cost: Money, context: CostContext, category: CostCategory = CostCategory.AI
    ) -> AuthorizationDecision:
        snapshot = self._load()
        decision = snapshot.value.authorize(
            estimated_cost, category, replace(context, occurred_at=self.clock.now())
        )
        self.ledger.commit(
            BudgetCommit(self.ledger_reference, decision.budget, snapshot.revision, decision)
        )
        return decision

    def require_authorized(
        self,
        authorization: BudgetAuthorization,
        minimum: Money,
        category: CostCategory = CostCategory.AI,
    ) -> None:
        snapshot = self._load()
        request = authorization.request
        request.estimated_cost.require_same_currency(minimum)
        if (
            authorization not in snapshot.value.outstanding
            or request.category != category
            or request.estimated_cost.amount < minimum.amount
            or request.context.occurred_at > self.clock.now()
        ):
            raise PortError(
                PortErrorCode.CONFLICT, "budget", "Persisted sufficient authorization required"
            )
        decision = self.authorize(request.estimated_cost, request.context, category)
        if (
            decision.status != AuthorizationStatus.AUTHORIZED
            or decision.authorization != authorization
        ):
            raise PortError(PortErrorCode.CONFLICT, "budget", "Current budget denies dispatch")

    def record(self, authorization: BudgetAuthorization, actual: Money, at: datetime) -> CostRecord:
        snapshot = self._load()
        recording = snapshot.value.record(
            actual,
            authorization.request.category,
            replace(authorization.request.context, occurred_at=at),
        )
        if recording.budget is snapshot.value:
            return recording.record
        self.ledger.commit(
            BudgetCommit(self.ledger_reference, recording.budget, snapshot.revision, recording)
        )
        return recording.record
