"""Fresh economic view after outcomes/payments or late cost recording; no cached totals."""

from dataclasses import dataclass

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.repositories import CostLedgerRepository, OpportunityRepository
from agentmine.application.use_cases.context import load
from agentmine.domain.metrics import EconomicMetrics
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class GetEconomicMetrics:
    opportunities: OpportunityRepository
    ledger: CostLedgerRepository

    def execute(self, reference: Reference, ledger_reference: Reference) -> EconomicMetrics:
        opportunity = load(self.opportunities, reference).value
        snapshot = self.ledger.get(ledger_reference)
        if snapshot is None:
            raise PortError(PortErrorCode.UNAVAILABLE, "metrics", "Cost ledger unavailable")
        return EconomicMetrics(
            opportunity,
            tuple(
                record
                for record in snapshot.value.records
                if record.context.opportunity_reference == reference
            ),
            tuple(
                auth.request.context.operation_reference
                for auth in snapshot.value.outstanding
                if auth.request.context.opportunity_reference == reference
            ),
        )
