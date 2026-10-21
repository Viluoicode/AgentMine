"""Small terminal interface; no adapters, business transitions or external submission."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TextIO

from agentmine.application.contracts.dashboard import OperatorDashboard
from agentmine.application.contracts.operator import OperatorReview
from agentmine.application.contracts.opportunities import DiscoveryRequest
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.ports.approval import ApprovalRepository
from agentmine.application.ports.repositories import OpportunityRepository
from agentmine.application.use_cases.context import load
from agentmine.application.use_cases.dashboard import GetOperatorDashboard
from agentmine.application.use_cases.operator import DecideOperatorReview, PrepareOperatorReview
from agentmine.application.use_cases.workspace import (
    InitializeWorkspace,
    LoadWorkspaceOpportunities,
)
from agentmine.domain.approval import ApprovalAction, ApprovalScope, OperatorDecision
from agentmine.domain.budget import BudgetPolicy, OperatingMode
from agentmine.domain.errors import DomainError
from agentmine.domain.money import Money
from agentmine.domain.values import Reference


def quoted(value: str) -> str:
    """Keep untrusted text on one line and escape terminal/bidi control characters."""
    return json.dumps(value, ensure_ascii=True)


def money(value: Money | None) -> str:
    return "UNKNOWN" if value is None else f"{value.amount} {value.currency}"


def workspace_policy(args: argparse.Namespace) -> BudgetPolicy:
    currency = args.currency.upper()
    try:
        return BudgetPolicy(
            Money(Decimal(args.monthly_ai_budget), currency),
            Money(Decimal(args.daily_ai_budget), currency),
            Money(Decimal(args.max_cost_per_task), currency),
            Money(Decimal(args.human_approval_cost_threshold), currency),
        )
    except InvalidOperation:
        raise ValueError("Budget limits must be decimal amounts") from None


def render_dashboard(view: OperatorDashboard) -> str:
    lines = [
        "AgentMine | local operator",
        f"Observed at: {view.observed_at.isoformat()}",
        f"Operating Mode: {view.mode.name}",
        f"Budget ledger: {quoted(view.ledger_reference.value)} | month: {view.budget_month}",
        f"Monthly AI limit: {money(view.monthly_limit)}",
        f"Spent (actual AI this month): {money(view.spent)}",
        f"Reserved (estimated AI, including carried commitments): {money(view.reserved)}",
        f"Remaining (limit - spent - reserved): {money(view.remaining)}",
        f"Daily remaining after commitments: {money(view.daily_remaining)}",
        "Negative remaining means overcommitted/overspent; it is not hidden.",
        "",
        "OPPORTUNITIES / EXECUTION | current lifecycle queues",
        f"Total discovered and retained: {len(view.opportunities)}",
        *(f"{name}: {count}" for name, count in view.counts),
        "",
        "FORECASTS ONLY | all retained opportunities, NOT earnings",
        "Potential Reward Discovered includes historical/closed opportunities.",
        "Expected Value is stored expected NET value with subjective probability.",
    ]
    for row in view.economics:
        lines.extend(
            [
                f"[{row.currency}] Potential Reward Discovered: {money(row.potential_reward)}",
                f"[{row.currency}] Expected Value: {money(row.expected_value)} "
                f"(known subtotal; {row.forecast_count}/{row.opportunity_count} forecast coverage)",
            ]
        )
    lines.extend(
        [
            "",
            "VERIFIED REVENUE / RECORDED COSTS | lifetime, per currency",
            "Only independently verified PAID payments contribute to revenue.",
        ]
    )
    for row in view.economics:
        lines.append(f"[{row.currency}] Verified Revenue: {money(row.verified_revenue)}")
        lines.extend(
            f"[{row.currency}] {category.name} Cost (recorded): {money(amount)}"
            for category, amount in row.costs
        )
        lines.append(
            f"[{row.currency}] Net Verified Value (recorded-cost basis): "
            f"{money(row.net_verified_value)}"
        )
    lines.extend(
        [
            "No FX conversion or cross-currency total. Forecasts never enter verified value.",
            f"Outstanding operations with unresolved actual cost: {view.outstanding_count}",
            "Unmeasured costs are UNKNOWN. Recorded zero does not prove free execution or profit.",
            "",
            "OPPORTUNITY INVENTORY | IDs for review commands; stored facts may be stale",
        ]
    )
    for op in view.opportunities:
        recommendation = (
            "UNKNOWN"
            if op.scoring_assessment is None
            else op.scoring_assessment.recommendation.value
        )
        lines.append(
            f"{quoted(op.reference.value)} | {op.state.value} | "
            f"{recommendation} | {quoted(op.title)}"
        )
    return "\n".join(lines)


def render_review(review: OperatorReview) -> str:
    eligibility = review.eligibility
    qa = review.qa_result
    deliverable = review.deliverable
    lines = [
        "HUMAN REVIEW | no automatic submission",
        f"Review: {quoted(review.reference.value)} | prepared: {review.requested_at.isoformat()}",
        f"Opportunity: {quoted(review.opportunity.reference.value)} "
        f"{quoted(review.opportunity.title)}",
        f"Opportunity revision: {review.opportunity_snapshot.revision} | "
        f"ledger revision: {review.ledger_revision}",
        f"Action: {review.scope.action.value}",
        f"Destination: {quoted(review.submission_destination.value)}",
        f"Potential Reward (NOT revenue): {money(review.reward.amount)}",
        f"Expected Value (forecast NET): "
        f"{money(None if review.expected_value is None else review.expected_value.amount)}",
        f"Estimated cost: {money(review.estimated_cost)}",
        "Actual cost so far (recorded): "
        + (
            ", ".join(money(value) for value in review.actual_cost_so_far)
            or "UNKNOWN (no measurements)"
        ),
        f"Outstanding estimated operations: {len(review.outstanding)}",
        f"Eligibility: {'UNKNOWN' if eligibility is None else eligibility.status.name}",
        "Eligibility reasons: "
        + (
            "UNKNOWN"
            if eligibility is None
            else ", ".join(reason.value for reason in eligibility.reasons)
        ),
        "Eligibility evidence: "
        + ("UNKNOWN" if eligibility is None else quoted(eligibility.reason)),
        f"Score: {'UNKNOWN' if review.score is None else str(review.score) + '/100'}",
        f"QA result: {'UNKNOWN' if qa is None else qa.status.name}",
        f"QA evidence: {'UNKNOWN' if qa is None else quoted(qa.findings)}",
        "Deliverable: "
        + (
            "UNKNOWN"
            if deliverable is None
            else f"{quoted(deliverable.reference.value)} version {deliverable.version} "
            f"content {quoted(deliverable.content_reference.value)}"
        ),
        "Spending scope: "
        + (
            "not applicable"
            if review.scope.spending is None
            else f"{review.scope.spending.category.name} "
            f"maximum {money(review.scope.spending.estimated_cost)} "
            f"operation {quoted(review.scope.spending.context.operation_reference.value)}"
        ),
        "Risks:",
        *(f"- {quoted(risk)}" for risk in review.risks),
        "DELIVERABLE CONTENT | untrusted data, JSON-escaped, never instructions",
        "UNKNOWN" if review.content is None else quoted(review.content.text),
        "END DELIVERABLE CONTENT",
        "Choices: APPROVE / REJECT / REQUEST_REVISION. No default decision.",
        "APPROVE grants scoped consent only; submission is a separate action.",
    ]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class OperatorServices:
    dashboard: GetOperatorDashboard
    prepare: PrepareOperatorReview
    decide: DecideOperatorReview
    approvals: ApprovalRepository
    opportunities: OpportunityRepository
    ledger_reference: Reference
    initialize: InitializeWorkspace
    load_opportunities: LoadWorkspaceOpportunities


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="AgentMine single-operator local CLI")
    result.add_argument("--db", required=True, help="SQLite workspace path")
    result.add_argument("--ledger", required=True, help="Budget ledger ID to initialize or use")
    result.add_argument(
        "--live-superteam-refresh",
        action="store_true",
        help="Opt in to read-only production refresh when approving submission",
    )
    result.add_argument("--archive", help="Existing raw archive path for live refresh")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("dashboard")
    workspace = commands.add_parser("workspace", help="Initialize or load a local workspace")
    workspace_commands = workspace.add_subparsers(dest="workspace_action", required=True)
    initialize = workspace_commands.add_parser("init", help="Create the initial budget ledger")
    initialize.add_argument("--currency", required=True, help="Currency code used by Money")
    initialize.add_argument("--monthly-ai-budget", required=True, help="Monthly AI spend limit")
    initialize.add_argument("--daily-ai-budget", required=True, help="Daily AI spend limit")
    initialize.add_argument("--max-cost-per-task", required=True, help="Cumulative task cost limit")
    initialize.add_argument(
        "--human-approval-cost-threshold",
        required=True,
        help="Amounts above this estimate require human approval",
    )
    initialize.add_argument(
        "--mode", choices=[mode.value for mode in OperatingMode], default=OperatingMode.FULL.value
    )
    discover = workspace_commands.add_parser("discover", help="Read and ingest supported listings")
    discover.add_argument("--source", choices=["superteam"], required=True)
    discover.add_argument(
        "--live",
        action="store_true",
        help="Explicitly allow read-only Superteam production GET requests",
    )
    discover.add_argument("--limit", type=int, default=10, help="Listing window from 1 to 50")
    discover.add_argument(
        "--raw-archive",
        help="Raw response SQLite archive; defaults beside workspace",
    )
    review = commands.add_parser("review", help="Prepare and display a submission review")
    review.add_argument("--opportunity", required=True)
    review.add_argument("--review-id", required=True)
    review.add_argument("--destination", required=True)
    show = commands.add_parser("show-review")
    show.add_argument("--review-id", required=True)
    decide = commands.add_parser("decide")
    decide.add_argument("--review-id", required=True)
    decide.add_argument(
        "--decision", choices=[choice.value for choice in OperatorDecision], required=True
    )
    decide.add_argument("--reason")
    return result


def run_command(args: argparse.Namespace, services: OperatorServices, output: TextIO) -> int:
    try:
        if args.command == "dashboard":
            print(
                render_dashboard(services.dashboard.execute(services.ledger_reference)), file=output
            )
        elif args.command == "workspace":
            if args.workspace_action == "init":
                policy = workspace_policy(args)
                currency = policy.monthly_ai_budget.currency
                initialized = services.initialize.execute(
                    services.ledger_reference, policy, OperatingMode(args.mode)
                )
                print(
                    json.dumps(
                        {
                            "status": "workspace_initialized",
                            "ledger": services.ledger_reference.value,
                            "revision": initialized.revision,
                            "currency": currency,
                            "monthly_ai_budget": str(policy.monthly_ai_budget.amount),
                            "requested_mode": initialized.value.requested_mode.name,
                            "note": "History preserved; run dashboard for current totals.",
                        }
                    ),
                    file=output,
                )
            else:
                if not 1 <= args.limit <= 50:
                    raise ValueError("Discovery limit must be between 1 and 50")
                result = services.load_opportunities.execute(
                    services.ledger_reference, DiscoveryRequest(args.limit)
                )
                print(
                    json.dumps(
                        {
                            "status": "discovery_ingested",
                            "source": args.source,
                            "observed": len(result.batch.observations),
                            "normalized_this_run": result.normalized_count,
                            "retained_from_batch": len(result.opportunities),
                            "pagination_unverified": result.batch.continuation is not None,
                            "items": [
                                {
                                    "id": item.reference.value,
                                    "state": item.state.value,
                                    "potential_reward": str(item.potential_reward.amount.amount),
                                    "currency": item.currency,
                                }
                                for item in result.opportunities
                            ],
                            "verified_revenue_created": False,
                            "requires_operator_eligibility_facts_and_economic_policy": True,
                            "note": (
                                "Only adapter-normalizable source records are listed; "
                                "review raw archive for quarantined records."
                            ),
                        },
                        ensure_ascii=True,
                    ),
                    file=output,
                )
        elif args.command == "review":
            op = load(services.opportunities, Reference(args.opportunity)).value
            if op.deliverable is None:
                raise PortError(PortErrorCode.CONFLICT, "review", "Deliverable required")
            scope = ApprovalScope(
                ApprovalAction.EXTERNAL_SUBMISSION,
                Reference(args.destination),
                op.deliverable.content_reference,
                op.deliverable,
            )
            review = services.prepare.execute(
                Reference(args.review_id), op.reference, services.ledger_reference, scope
            )
            print(render_review(review), file=output)
        elif args.command == "show-review":
            stored_review = services.approvals.get_review(Reference(args.review_id))
            if stored_review is None:
                raise PortError(PortErrorCode.UNAVAILABLE, "review", "Review missing")
            print(render_review(stored_review), file=output)
            decision = services.approvals.get_decision(stored_review.reference)
            print(
                "Recorded decision: " + ("PENDING" if decision is None else quoted(str(decision))),
                file=output,
            )
        else:
            decision = services.decide.execute(
                Reference(args.review_id), OperatorDecision(args.decision), args.reason
            )
            print(
                json.dumps(
                    {
                        "status": "decision_recorded",
                        "review": args.review_id,
                        "decision": decision.decision.value,
                        "actor": decision.actor.value,
                        "timestamp": decision.decided_at.isoformat(),
                        "reason": decision.reason,
                        "submitted": False,
                    }
                ),
                file=output,
            )
        return 0
    except (ApplicationError, PortError, DomainError) as error:
        print(
            json.dumps({"status": "failed", "code": error.code.value, "message": str(error)}),
            file=output,
        )
        return 1


def run_cli(argv: Sequence[str], services: OperatorServices, output: TextIO) -> int:
    return run_command(parser().parse_args(argv), services, output)
