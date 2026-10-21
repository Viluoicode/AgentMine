"""Operator read models; forecasts and recorded financial facts stay separate."""

from dataclasses import dataclass
from datetime import datetime

from agentmine.domain.budget import Budget, OperatingMode
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class OperatorSnapshot:
    """Complete consistent local workspace with exactly one budget ledger."""

    opportunities: tuple[Opportunity, ...]
    budget: Budget


@dataclass(frozen=True, slots=True)
class CurrencyEconomics:
    currency: str
    potential_reward: Money
    expected_value: Money | None
    forecast_count: int
    opportunity_count: int
    verified_revenue: Money
    costs: tuple[tuple[CostCategory, Money], ...]
    net_verified_value: Money


@dataclass(frozen=True, slots=True)
class OperatorDashboard:
    observed_at: datetime
    ledger_reference: Reference
    mode: OperatingMode
    budget_month: str
    monthly_limit: Money
    spent: Money
    reserved: Money
    remaining: Money
    daily_remaining: Money
    counts: tuple[tuple[str, int], ...]
    opportunities: tuple[Opportunity, ...]
    economics: tuple[CurrencyEconomics, ...]
    outstanding_count: int
