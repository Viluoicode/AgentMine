"""Real local CLI commands, persistent decisions and honest recorded-value reporting."""

import io
from pathlib import Path

import pytest
from local_cases import snapshots
from test_operator_approval import ready
from test_use_cases import World, usd, world

from agentmine.application.contracts.records import BudgetCommit, OpportunitySave
from agentmine.bootstrap.local import open_local_repositories
from agentmine.bootstrap.operator import compose_operator, main
from agentmine.domain.approval import OperatorDecision
from agentmine.domain.finance import CostCategory
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.infrastructure.marketplaces.disabled import DisabledOpportunitySource
from agentmine.presentation.operator_cli import OperatorServices, run_cli

__all__ = ["world"]


def seed(world: World, path: Path) -> OperatorServices:
    ready(world)
    repos = open_local_repositories(path)
    repos.opportunities.save(OpportunitySave(world.current(), None))
    observation = world.opportunities.get_observation(world.reference)
    assert observation is not None
    repos.opportunities.save_observation(observation)
    deliverable = world.current().deliverable
    assert deliverable is not None
    content = world.executions.get_content(deliverable.content_reference)
    assert content is not None
    repos.executions.save_content(content)
    budget = world.ledger.snapshots[Reference("ledger")].value
    repos.ledger.commit(BudgetCommit(Reference("ledger"), budget, None, None))
    return compose_operator(
        path, Reference("ledger"), Reference("alice"), world.clock, world.source
    )


def invoke(services: OperatorServices, *command: str) -> tuple[int, str]:
    output = io.StringIO()
    code = run_cli(["--db", "unused", "--ledger", "ledger", *command], services, output)
    return code, output.getvalue()


def prepare(services: OperatorServices) -> None:
    code, text = invoke(
        services,
        "review",
        "--opportunity",
        "opportunity",
        "--review-id",
        "review",
        "--destination",
        "destination",
    )
    assert code == 0
    for label in (
        "Potential Reward (NOT revenue)",
        "Expected Value",
        "Estimated cost",
        "Actual cost so far",
        "Eligibility",
        "Score",
        "QA result",
        "Deliverable",
        "Risks",
        "Destination",
        "DELIVERABLE CONTENT",
    ):
        assert label in text


@pytest.mark.parametrize(
    "decision,state",
    [
        (OperatorDecision.APPROVE, OpportunityState.APPROVED_FOR_SUBMISSION),
        (OperatorDecision.REJECT, OpportunityState.SKIPPED),
        (OperatorDecision.REQUEST_REVISION, OpportunityState.IN_PROGRESS),
    ],
)
def test_all_decisions_persist_and_retry_without_submission(
    world: World,
    tmp_path: Path,
    decision: OperatorDecision,
    state: OpportunityState,
) -> None:
    path = tmp_path / "operator.sqlite3"
    services = seed(world, path)
    prepare(services)
    code, text = invoke(services, "dashboard")
    assert code == 0 and "Human review pending: 1" in text
    for _ in range(2):
        services = compose_operator(
            path, Reference("ledger"), Reference("alice"), world.clock, world.source
        )
        code, text = invoke(
            services,
            "decide",
            "--review-id",
            "review",
            "--decision",
            decision.value,
            "--reason",
            "Read evidence",
        )
        assert code == 0 and '"submitted": false' in text
    stored = services.approvals.get_decision(Reference("review"))
    assert stored is not None and stored.actor == Reference("alice")
    assert stored.reason == "Read evidence" and stored.decided_at == world.clock.now()
    op = services.opportunities.get(world.reference)
    assert op is not None and op.value.state == state and op.value.submission is None
    assert world.gateway.submits == 0
    code, text = invoke(services, "show-review", "--review-id", "review")
    assert code == 0 and decision.value in text and "alice" in text
    other = "REJECT" if decision == OperatorDecision.APPROVE else "APPROVE"
    assert invoke(services, "decide", "--review-id", "review", "--decision", other)[0] == 1


@pytest.mark.parametrize("failure", ["offline", "closed", "stale_budget"])
def test_approval_guards_remain_effective(world: World, tmp_path: Path, failure: str) -> None:
    path = tmp_path / "operator.sqlite3"
    services = seed(world, path)
    prepare(services)
    if failure == "offline":
        services = compose_operator(
            path, Reference("ledger"), Reference("alice"), world.clock, DisabledOpportunitySource()
        )
    elif failure == "closed":
        world.source.is_open = False
    else:
        ledger = open_local_repositories(path).ledger
        original = ledger.get(Reference("ledger"))
        assert original is not None
        ledger.commit(BudgetCommit(Reference("ledger"), original.value, original.revision, None))
    assert invoke(services, "decide", "--review-id", "review", "--decision", "APPROVE")[0] == 1
    assert services.approvals.get_decision(Reference("review")) is None


def test_accepted_not_paid_and_all_cost_categories(world: World, tmp_path: Path) -> None:
    path = tmp_path / "operator.sqlite3"
    services = seed(world, path)
    repos = open_local_repositories(path)
    for state in (
        OpportunityState.ACCEPTED,
        OpportunityState.PAID,
        OpportunityState.WAITING_FOR_BUDGET,
        OpportunityState.QA_PENDING,
    ):
        repos.opportunities.save(OpportunitySave(snapshots(state.value)[state], None))
    budget = repos.ledger.get(Reference("ledger"))
    assert budget is not None
    updated = budget.value
    for category in CostCategory:
        updated = updated.record(
            usd("2"),
            category,
            CostContext(
                Reference("cost:" + category.value),
                OperationType.SCORING,
                world.clock.now(),
            ),
        ).budget
    repos.ledger.commit(BudgetCommit(Reference("ledger"), updated, budget.revision, None))
    view = services.dashboard.execute(Reference("ledger"))
    assert view.economics[0].potential_reward == usd("500")
    assert view.economics[0].verified_revenue == usd("85")
    assert view.economics[0].net_verified_value == usd("76")  # 1 existing + 4*2 actual costs
    assert dict(view.counts)["Waiting for budget"] == dict(view.counts)["QA pending"] == 1
    assert dict(view.counts)["Human review pending"] == 1
    code, text = invoke(services, "dashboard")
    assert code == 0 and "Verified Revenue: 85 USD" in text
    assert "Potential Reward Discovered: 500 USD" in text
    assert "Net Verified Value (recorded-cost basis): 76 USD" in text


def test_missing_or_multiple_ledgers_never_become_zero_profit(world: World, tmp_path: Path) -> None:
    path = tmp_path / "operator.sqlite3"
    services = seed(world, path)
    unknown = compose_operator(
        path, Reference("absent"), Reference("alice"), world.clock, world.source
    )
    assert invoke(unknown, "dashboard")[0] == 1
    repos = open_local_repositories(path)
    budget = repos.ledger.get(Reference("ledger"))
    assert budget is not None
    repos.ledger.commit(BudgetCommit(Reference("other"), budget.value, None, None))
    code, text = invoke(services, "dashboard")
    assert code == 1 and "exactly one" in text


def test_entrypoint_is_offline_and_requires_explicit_identity(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "operator.sqlite3"
    services = seed(world, path)
    prepare(services)
    monkeypatch.delenv("AGENTMINE_OPERATOR_ID", raising=False)
    args = ["--db", str(path), "--ledger", "ledger"]
    assert main([*args, "dashboard"]) == 0
    assert "Operating Mode: FULL" in capsys.readouterr().out
    assert main([*args, "decide", "--review-id", "review", "--decision", "REJECT"]) == 2
    monkeypatch.setenv("AGENTMINE_OPERATOR_ID", "alice")
    assert main([*args, "decide", "--review-id", "review", "--decision", "REJECT"]) == 0
    missing = tmp_path / "missing.db"
    assert main(["--db", str(missing), "--ledger", "ledger", "dashboard"]) == 2
    assert not missing.exists()
