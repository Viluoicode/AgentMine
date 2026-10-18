"""Realized metrics derived from current outcomes and recorded costs, not forecasts."""

from dataclasses import dataclass
from decimal import Decimal

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference, require_reference


@dataclass(frozen=True, slots=True)
class EconomicMetrics:
    opportunity: Opportunity
    actual_costs: tuple[CostRecord, ...]
    outstanding_operations: tuple[Reference, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.actual_costs, tuple)
            or any(not isinstance(item, CostRecord) for item in self.actual_costs)
            or len({item.context.operation_reference for item in self.actual_costs})
            != len(self.actual_costs)
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "metrics", "Unique actual cost operations required"
            )
        if not isinstance(self.outstanding_operations, tuple):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "metrics", "Immutable outstanding identities required"
            )
        for reference in self.outstanding_operations:
            require_reference(reference, "outstanding_operation")
        for record in self.actual_costs:
            if record.context.opportunity_reference != self.opportunity.reference:
                raise DomainError(
                    ErrorCode.EVIDENCE_MISMATCH, "metrics", "Cost opportunity mismatch"
                )
            self.opportunity.potential_reward.amount.require_same_currency(record.actual_cost)

    def cost(self, category: CostCategory) -> Money:
        if not isinstance(category, CostCategory):
            raise DomainError(ErrorCode.INVALID_VALUE, "category", "Known cost category required")
        total = Money(Decimal(0), self.opportunity.currency)
        for record in self.actual_costs:
            if record.cost.category == category:
                total += record.actual_cost
        return total

    @property
    def total_actual_cost(self) -> Money:
        total = Money(Decimal(0), self.opportunity.currency)
        for category in CostCategory:
            total += self.cost(category)
        return total

    @property
    def verified_revenue(self) -> Money:
        return self.opportunity.verified_revenue

    @property
    def net_verified_value(self) -> Money:
        """Recorded-cost basis; outstanding/unmeasured charges may still change this value."""
        return self.verified_revenue - self.total_actual_cost
