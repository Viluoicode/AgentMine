"""Read-only operator summary using domain financial and budget semantics."""

from dataclasses import dataclass
from decimal import Decimal

from agentmine.application.contracts.dashboard import CurrencyEconomics, OperatorDashboard
from agentmine.application.ports.operator import OperatorReadRepository
from agentmine.application.ports.services import Clock
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.scoring import Recommendation
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class GetOperatorDashboard:
    repository: OperatorReadRepository
    clock: Clock

    def execute(self, ledger_reference: Reference) -> OperatorDashboard:
        snapshot = self.repository.read(ledger_reference)
        at = self.clock.now()
        budget, opportunities = snapshot.budget, snapshot.opportunities
        spent = budget.ai_spent(at, monthly=True)
        committed = budget.ai_committed(at, monthly=True)
        economics: list[CurrencyEconomics] = []
        currencies = {op.currency for op in opportunities} | {spent.currency}
        for currency in sorted(currencies):
            zero = Money(Decimal(0), currency)
            matching = tuple(op for op in opportunities if op.currency == currency)
            potential = revenue = expected = zero
            forecasts = 0
            for op in matching:
                potential += op.potential_reward.amount
                revenue += op.verified_revenue
                if op.expected_value is not None:
                    expected += op.expected_value.amount
                    forecasts += 1
            costs = {category: zero for category in CostCategory}
            for record in budget.records:
                if record.actual_cost.currency == currency:
                    costs[record.cost.category] += record.actual_cost
            net = revenue
            for amount in costs.values():
                net -= amount
            economics.append(
                CurrencyEconomics(
                    currency,
                    potential,
                    expected if forecasts else None,
                    forecasts,
                    len(matching),
                    revenue,
                    tuple(costs.items()),
                    net,
                )
            )
        states = (
            ("Discovered", OpportunityState.DISCOVERED),
            ("Eligible", OpportunityState.ELIGIBLE),
            ("Waiting for budget", OpportunityState.WAITING_FOR_BUDGET),
            ("In progress", OpportunityState.IN_PROGRESS),
            ("QA pending", OpportunityState.QA_PENDING),
            ("Human review pending", OpportunityState.READY_FOR_HUMAN_REVIEW),
        )
        counts = tuple(
            (name, sum(op.state == state for op in opportunities)) for name, state in states
        )
        recommended = sum(
            op.state == OpportunityState.SCORED
            and op.scoring_assessment is not None
            and op.scoring_assessment.recommendation
            in (
                Recommendation.RECOMMEND,
                Recommendation.ATTEMPT,
            )
            for op in opportunities
        )
        return OperatorDashboard(
            at,
            ledger_reference,
            budget.operating_mode(at),
            at.astimezone(budget.policy.calendar_timezone).strftime("%Y-%m (%Z)"),
            budget.policy.monthly_ai_budget,
            spent,
            committed - spent,
            budget.policy.monthly_ai_budget - committed,
            budget.policy.daily_ai_budget - budget.ai_committed(at),
            (*counts, ("Recommended (scored queue)", recommended)),
            opportunities,
            tuple(economics),
            len(budget.outstanding),
        )
