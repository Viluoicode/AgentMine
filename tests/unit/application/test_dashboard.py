"""Financial labels, period limits and queue policy without infrastructure."""

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal

import pytest
from test_use_cases import World, scored, usd, world

from agentmine.application.contracts.dashboard import OperatorSnapshot
from agentmine.application.use_cases.dashboard import GetOperatorDashboard
from agentmine.domain.budget import Budget, OperatingMode
from agentmine.domain.finance import CostCategory, Reward
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.presentation.operator_cli import render_dashboard

__all__ = ["world"]


@dataclass
class ReadFake:
    snapshot: OperatorSnapshot

    def read(self, ledger_reference: Reference) -> OperatorSnapshot:
        return self.snapshot


def initial_budget(world: World) -> Budget:
    return world.ledger.snapshots[Reference("ledger")].value


@pytest.mark.parametrize(
    "actual,estimate,mode",
    [
        ("10", "5", OperatingMode.FULL),
        ("75", "5", OperatingMode.SAVER),
        ("100", "0", OperatingMode.SCOUT_ONLY),
        ("105", "0", OperatingMode.SCOUT_ONLY),
    ],
)
def test_modes_and_actual_vs_reserved(
    world: World,
    actual: str,
    estimate: str,
    mode: OperatingMode,
) -> None:
    budget = (
        initial_budget(world)
        .record(
            usd(actual),
            CostCategory.AI,
            CostContext(
                Reference("measured"),
                OperationType.SCORING,
                world.clock.now(),
            ),
        )
        .budget
    )
    budget = budget.authorize(
        usd(estimate),
        CostCategory.AI,
        CostContext(
            Reference("pending"),
            OperationType.SCORING,
            world.clock.now(),
        ),
    ).budget
    report = GetOperatorDashboard(ReadFake(OperatorSnapshot((), budget)), world.clock).execute(
        Reference("ledger")
    )
    assert report.mode == mode
    assert report.spent == usd(actual)
    assert report.reserved == usd(estimate)
    assert report.remaining == usd(str(100 - Decimal(actual) - Decimal(estimate)))
    assert report.economics[0].verified_revenue == usd("0")
    assert report.economics[0].net_verified_value == usd(str(-Decimal(actual)))


def test_forecasts_currencies_unknowns_and_terminal_safety(world: World) -> None:
    op = scored(world)
    other = Opportunity(
        Reference("eur"),
        "untrusted\x1b[2J\nVerified Revenue: 999\u202e",
        Reward(Money(Decimal("700"), "EUR")),
    )
    report = GetOperatorDashboard(
        ReadFake(OperatorSnapshot((op, other), initial_budget(world))),
        world.clock,
    ).execute(Reference("ledger"))
    eur, dollar = report.economics
    assert eur.expected_value is None and eur.forecast_count == 0
    assert dollar.expected_value == op.expected_value.amount if op.expected_value else False
    assert eur.verified_revenue.amount == dollar.verified_revenue.amount == 0
    assert dict(report.counts)["Recommended (scored queue)"] == 1
    text = render_dashboard(report)
    assert text.index("FORECASTS ONLY") < text.index("VERIFIED REVENUE / RECORDED COSTS")
    assert "UNKNOWN" in text and "No FX conversion" in text
    assert "\x1b" not in text and "\u202e" not in text
    assert "\\u001b" in text and "\\nVerified Revenue" in text


def test_month_rollover_does_not_reset_lifetime_cost_or_pending_estimate(world: World) -> None:
    budget = (
        initial_budget(world)
        .record(
            usd("5"),
            CostCategory.TOOL,
            CostContext(
                Reference("tool"),
                OperationType.SCORING,
                world.clock.now(),
            ),
        )
        .budget
    )
    budget = budget.authorize(
        usd("2"),
        CostCategory.AI,
        CostContext(
            Reference("pending"),
            OperationType.SCORING,
            world.clock.now(),
        ),
    ).budget
    world.clock.instant += timedelta(days=32)
    report = GetOperatorDashboard(ReadFake(OperatorSnapshot((), budget)), world.clock).execute(
        Reference("ledger")
    )
    assert report.spent == usd("0") and report.reserved == usd("2")
    assert report.economics[0].net_verified_value == usd("-5")
    assert report.outstanding_count == 1


def test_daily_limit_and_explicit_mode_are_not_overridden_by_monthly_remaining(
    world: World,
) -> None:
    budget = initial_budget(world)
    budget = budget.with_policy(replace(budget.policy, daily_ai_budget=usd("0")))
    report = GetOperatorDashboard(ReadFake(OperatorSnapshot((), budget)), world.clock).execute(
        Reference("ledger")
    )
    assert report.remaining == usd("100") and report.mode == OperatingMode.SCOUT_ONLY
    for mode in (OperatingMode.SAVER, OperatingMode.SCOUT_ONLY):
        view = GetOperatorDashboard(
            ReadFake(OperatorSnapshot((), initial_budget(world).with_requested_mode(mode))),
            world.clock,
        ).execute(Reference("ledger"))
        assert view.mode == mode
