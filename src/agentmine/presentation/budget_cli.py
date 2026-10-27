"""Explicit local policy commands; parsing/rendering only, no financial mutation."""

import argparse
import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from agentmine.application.contracts.budget_control import BudgetControlError
from agentmine.application.use_cases.budget_control import (
    ApplyBudgetPolicyChange,
    GetBudgetPolicyChange,
    InspectBudgetRecovery,
    PrepareBudgetPolicyChange,
)
from agentmine.domain.budget import BudgetPolicy, OperatingMode
from agentmine.domain.errors import DomainError
from agentmine.domain.money import Money
from agentmine.domain.values import Reference
from agentmine.presentation.runtime_cli import encode


@dataclass(frozen=True, slots=True)
class BudgetServices:
    inspect: InspectBudgetRecovery
    prepare: PrepareBudgetPolicyChange
    get: GetBudgetPolicyChange
    apply: ApplyBudgetPolicyChange


def add_budget_parsers(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    budget = commands.add_parser(
        "budget", help="Inspect budget and explicitly approve policy changes"
    )
    actions = budget.add_subparsers(dest="budget_action", required=True)
    actions.add_parser("show")
    policy = actions.add_parser("policy")
    policy_actions = policy.add_subparsers(dest="policy_action", required=True)
    for action in ("prepare", "show", "apply"):
        command = policy_actions.add_parser(action)
        command.add_argument("--change-id", required=True)
        if action == "prepare":
            command.add_argument("--inputs", required=True)
            command.add_argument("--expected-revision", required=True, type=int)
            command.add_argument("--reason", required=True)
        if action == "apply":
            command.add_argument("--confirm", action="store_true")


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate policy field")
        result[key] = value
    return result


def read_policy(path: Path, current: BudgetPolicy) -> tuple[BudgetPolicy, OperatingMode]:
    with path.open("rb") as stream:
        raw = stream.read(16_001)
    if len(raw) > 16_000:
        raise ValueError("Policy input exceeds bound")
    values = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    names = {
        "monthly_ai_budget",
        "daily_ai_budget",
        "max_cost_per_task",
        "human_approval_cost_threshold",
        "saver_remaining_ratio",
        "saver_ai_cost_factor",
        "requested_mode",
    }
    if (
        not isinstance(values, dict)
        or set(values) != names
        or any(
            not isinstance(value, str) or not value.strip() or len(value) > 100
            for value in values.values()
        )
    ):
        raise ValueError("Exact policy fields and decimal strings required")
    if any(
        re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", values[name]) is None
        for name in names - {"requested_mode"}
    ):
        raise ValueError("Bounded plain decimal notation required")
    currency = current.monthly_ai_budget.currency
    policy = replace(
        current,
        monthly_ai_budget=Money(Decimal(values["monthly_ai_budget"]), currency),
        daily_ai_budget=Money(Decimal(values["daily_ai_budget"]), currency),
        max_cost_per_task=Money(Decimal(values["max_cost_per_task"]), currency),
        human_approval_cost_threshold=Money(
            Decimal(values["human_approval_cost_threshold"]), currency
        ),
        saver_remaining_ratio=Decimal(values["saver_remaining_ratio"]),
        saver_ai_cost_factor=Decimal(values["saver_ai_cost_factor"]),
    )
    return policy, OperatingMode(values["requested_mode"])


def run_budget_command(args: argparse.Namespace, services: BudgetServices, output: TextIO) -> int:
    try:
        if args.budget_action == "show":
            view = encode(services.inspect.execute())
            assert isinstance(view, dict)
            view["unmeasured_costs"] = "UNKNOWN"
            print(json.dumps(view, ensure_ascii=True), file=output)
            return 0
        reference = Reference(args.change_id)
        if args.policy_action == "prepare":
            policy, mode = read_policy(Path(args.inputs), services.inspect.execute().policy)
            services.prepare.execute(reference, policy, mode, args.expected_revision, args.reason)
        elif args.policy_action == "apply":
            services.apply.execute(reference, confirm=args.confirm)
        print(json.dumps(encode(services.get.execute(reference)), ensure_ascii=True), file=output)
        return 0
    except BudgetControlError as error:
        print(
            json.dumps(
                {"status": "failed", "code": error.code.value, "reason": error.reason.value}
            ),
            file=output,
        )
        return 1
    except DomainError:
        raise
    except (OSError, ValueError, InvalidOperation, OverflowError):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "budget_policy_input",
                    "message": "Invalid bounded local policy input",
                }
            ),
            file=output,
        )
        return 2
