"""Real local CLI/SQLite budget control; only source and clock are test fakes."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from test_runtime_operator_cli import CLI, cli

from agentmine.bootstrap.operator import main
from agentmine.domain.values import Reference

__all__ = ["cli"]


def policy_file(cli: CLI, monthly: str = "30", mode: str = "full") -> Path:
    path = cli.root.parent / "policy.json"
    path.write_text(
        json.dumps(
            {
                "monthly_ai_budget": monthly,
                "daily_ai_budget": "5",
                "max_cost_per_task": "3",
                "human_approval_cost_threshold": "1",
                "saver_remaining_ratio": "0.2",
                "saver_ai_cost_factor": "0.5",
                "requested_mode": mode,
            }
        ),
        encoding="utf-8",
    )
    return path


def prepare(
    cli: CLI, change: str = "change-1", monthly: str = "30"
) -> tuple[int, dict[str, object]]:
    ledger = cli.world.budget().ledger.get(Reference("ledger"))
    assert ledger is not None
    return cli.command(
        "budget",
        "policy",
        "prepare",
        "--change-id",
        change,
        "--inputs",
        str(policy_file(cli, monthly)),
        "--expected-revision",
        str(ledger.revision),
        "--reason",
        "Operator reviewed local budget limits",
    )


def apply(cli: CLI, change: str = "change-1") -> tuple[int, dict[str, object]]:
    return cli.command("budget", "policy", "apply", "--change-id", change, "--confirm")


def test_prepare_apply_reopen_and_original_receipt(cli: CLI) -> None:
    before = cli.world.budget().ledger.get(Reference("ledger"))
    assert prepare(cli)[0] == 0
    assert cli.world.budget().ledger.get(Reference("ledger")) == before
    code, original = apply(cli)
    assert code == 0
    after = cli.world.budget().ledger.get(Reference("ledger"))
    assert before is not None and after is not None
    assert after.revision == before.revision + 1
    assert str(after.value.policy.monthly_ai_budget.amount) == "30"
    assert prepare(cli, "change-2", "40")[0] == 0
    assert apply(cli, "change-2")[0] == 0
    latest = cli.world.budget().ledger.get(Reference("ledger"))
    assert apply(cli)[1]["receipt"] == original["receipt"]
    assert cli.world.budget().ledger.get(Reference("ledger")) == latest
    assert cli.command("budget", "policy", "show", "--change-id", "change-1")[0] == 0


def test_apply_requires_confirmation(cli: CLI) -> None:
    assert prepare(cli)[0] == 0
    before = cli.world.budget().ledger.get(Reference("ledger"))
    code, output = cli.command("budget", "policy", "apply", "--change-id", "change-1")
    assert code != 0 and output["reason"] == "confirmation_required"
    assert cli.world.budget().ledger.get(Reference("ledger")) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("monthly_ai_budget", "-1"),
        ("daily_ai_budget", "NaN"),
        ("daily_ai_budget", "1e999999999"),
        ("max_cost_per_task", 2),
        ("human_approval_cost_threshold", True),
        ("saver_remaining_ratio", "1"),
        ("saver_ai_cost_factor", "0"),
        ("requested_mode", "automatic"),
        ("currency", "EUR"),
        ("calendar_timezone", "UTC"),
        ("authorization", {}),
    ],
)
def test_strict_policy_input(cli: CLI, field: str, value: object) -> None:
    path = policy_file(cli)
    data = json.loads(path.read_text(encoding="utf-8"))
    data[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    before = cli.world.budget().ledger.get(Reference("ledger"))
    assert before is not None
    code, _ = cli.command(
        "budget",
        "policy",
        "prepare",
        "--change-id",
        "invalid",
        "--inputs",
        str(path),
        "--expected-revision",
        str(before.revision),
        "--reason",
        "review",
    )
    assert code != 0
    assert cli.world.budget().ledger.get(Reference("ledger")) == before


def test_zero_data_still_runs_in_scout_only(cli: CLI) -> None:
    assert prepare(cli, monthly="0")[0] == 0
    assert apply(cli)[0] == 0
    code, view = cli.command("budget", "show")
    assert code == 0 and view["derived_mode"] == "scout_only"
    assert cli.prepare()[0] == 0
    code, result = cli.execute()
    assert code == 0 and result["opportunity_state"] == "QA_PENDING"
    code, view = cli.command("budget", "show")
    assert code == 0 and view["unmeasured_costs"] == "UNKNOWN"
    ledger = cli.world.budget().ledger.get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.records) == 1
    assert ledger.value.records[0].actual_cost.amount == 0


@pytest.mark.parametrize(
    "payload", ["{}", "[]", '{"requested_mode":"full","requested_mode":"saver"}', "x" * 16001]
)
def test_missing_duplicate_malformed_or_oversized_inputs(cli: CLI, payload: str) -> None:
    path = policy_file(cli)
    path.write_text(payload, encoding="utf-8")
    before = cli.world.budget().ledger.get(Reference("ledger"))
    assert before is not None
    code, result = cli.command(
        "budget",
        "policy",
        "prepare",
        "--change-id",
        "invalid",
        "--inputs",
        str(path),
        "--expected-revision",
        str(before.revision),
        "--reason",
        "review",
    )
    assert code != 0 and result["code"] == "budget_policy_input"
    assert cli.world.budget().ledger.get(Reference("ledger")) == before


def test_production_entrypoint_requires_actor_and_never_selects_provider(
    cli: CLI, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENTMINE_OPERATOR_ID", raising=False)
    base = ["--db", str(cli.world.database.path), "--ledger", "ledger"]
    with patch(
        "agentmine.infrastructure.llm.bedrock.create_bedrock_client",
        side_effect=AssertionError("no paid provider"),
    ):
        assert main([*base, "budget", "show"]) == 0
        assert (
            main(
                [
                    *base,
                    "budget",
                    "policy",
                    "prepare",
                    "--change-id",
                    "from-main",
                    "--inputs",
                    str(policy_file(cli)),
                    "--expected-revision",
                    "1",
                    "--reason",
                    "review",
                ]
            )
            == 2
        )
        monkeypatch.setenv("AGENTMINE_OPERATOR_ID", "operator")
        assert (
            main(
                [
                    *base,
                    "budget",
                    "policy",
                    "prepare",
                    "--change-id",
                    "from-main",
                    "--inputs",
                    str(policy_file(cli)),
                    "--expected-revision",
                    "1",
                    "--reason",
                    "review",
                ]
            )
            == 0
        )
        assert (
            main([*base, "budget", "policy", "apply", "--change-id", "from-main", "--confirm"]) == 0
        )
    assert "operator" in capsys.readouterr().out


@pytest.mark.parametrize("reason", ["", " ", "x" * 4001])
def test_reason_required_and_bounded(cli: CLI, reason: str) -> None:
    before = cli.world.budget().ledger.get(Reference("ledger"))
    assert before is not None
    assert (
        cli.command(
            "budget",
            "policy",
            "prepare",
            "--change-id",
            "bad-reason",
            "--inputs",
            str(policy_file(cli)),
            "--expected-revision",
            str(before.revision),
            "--reason",
            reason,
        )[0]
        != 0
    )
    assert cli.world.budget().ledger.get(Reference("ledger")) == before


@pytest.mark.parametrize("mode", ["saver", "scout_only"])
def test_explicit_requested_modes_and_frozen_file(cli: CLI, mode: str) -> None:
    before = cli.world.budget().ledger.get(Reference("ledger"))
    assert before is not None
    path = policy_file(cli, mode=mode)
    assert (
        cli.command(
            "budget",
            "policy",
            "prepare",
            "--change-id",
            "mode",
            "--inputs",
            str(path),
            "--expected-revision",
            str(before.revision),
            "--reason",
            "Review mode",
        )[0]
        == 0
    )
    policy_file(cli, monthly="999", mode="full")  # Editing the file cannot alter retained consent.
    assert apply(cli, "mode")[0] == 0
    code, view = cli.command("budget", "show")
    assert code == 0 and view["requested_mode"] == mode and view["derived_mode"] == mode
    after = cli.world.budget().ledger.get(Reference("ledger"))
    assert after is not None and after.value.policy.monthly_ai_budget.amount == 30
