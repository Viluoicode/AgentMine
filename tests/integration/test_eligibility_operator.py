"""Operator CLI parses evidence, delegates decisions, and never grants submission consent."""

import io
import json
from pathlib import Path

import pytest
from test_eligibility_use_case import Case, case

from agentmine.application.contracts.records import OpportunitySave
from agentmine.bootstrap.local import open_local_repositories
from agentmine.bootstrap.operator import compose_operator, main
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.presentation.operator_cli import run_cli

__all__ = ["case"]


def test_cli_manual_eligibility_prepare_show_and_decide(case: Case, tmp_path: Path) -> None:
    path = tmp_path / "operator.sqlite"
    stores = open_local_repositories(path)
    ref = case.request.facts.opportunity_reference
    op = case.repository.get(ref)
    observation = case.repository.get_observation(ref)
    assert op is not None and observation is not None
    stores.opportunities.save(OpportunitySave(op.value, None))
    stores.opportunities.save_observation(observation)
    case.source.terms_reference = Reference("terms:version-1")
    case.source.requirements = "Manual requirements \x1b[31m remain untrusted data"
    facts = tmp_path / "facts.json"
    facts.write_text(
        json.dumps(
            {
                "facts": {
                    "ai_policy": "allowed",
                    "geography": {"allowed": [], "excluded": []},
                    "account": "not_required",
                    "identity": "not_required",
                    "physical_presence": "not_required",
                    "task_type": "research",
                    "required_skills": [],
                    "submission": "manual",
                    "payment": {"upfront_fee": False, "secret_credentials": False},
                    "prohibited_actions": [],
                },
                "profile": {},
            }
        ),
        encoding="utf-8",
    )
    services = compose_operator(
        path, Reference("local"), Reference("alice"), case.clock, case.source
    )

    def command(*args: str) -> tuple[int, str]:
        output = io.StringIO()
        result = run_cli(
            ["--db", str(path), "--ledger", "local", "eligibility", *args], services, output
        )
        return result, output.getvalue()

    code, text = command(
        "prepare",
        "--review-id",
        "review",
        "--opportunity",
        ref.value,
        "--facts",
        str(facts),
        "--minimum-time-seconds",
        "3600",
    )
    assert code == 0 and "MANUAL_SUBMISSION_REQUIRED" in text
    assert "Facts:" in text and "Participant:" in text and "terms:version-1" in text
    assert "\x1b" not in text and "\\u001b" in text
    assert command("show", "--review-id", "review")[0] == 0
    code, text = command(
        "decide", "--review-id", "review", "--decision", "APPROVE", "--reason", "Checked"
    )
    assert code == 1 and "invalid_value" in text  # Missing evidence cannot become consent.
    code, text = command(
        "decide",
        "--review-id",
        "review",
        "--decision",
        "APPROVE",
        "--reason",
        "Checked",
        "--manual-destination",
        "manual:target",
        "--instructions-evidence",
        "capture:instructions",
        "--access-evidence",
        "capture:access",
        "--requirements-evidence",
        "capture:requirements",
        "--manual-requirements-met",
    )
    assert code == 0 and "alice" in text
    restored = open_local_repositories(path).opportunities.get(ref)
    assert restored is not None and restored.value.state == OpportunityState.ELIGIBLE
    assert restored.value.approval is None and restored.value.submission is None


def test_main_requires_operator_identity_for_eligibility_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENTMINE_OPERATOR_ID", raising=False)
    path = tmp_path / "must-not-be-created.sqlite"
    assert (
        main(
            [
                "--db",
                str(path),
                "--ledger",
                "local",
                "eligibility",
                "decide",
                "--review-id",
                "review",
                "--decision",
                "REJECT",
                "--reason",
                "Declined",
            ]
        )
        == 2
    )
    assert "Operator identity required" in capsys.readouterr().out
    assert not path.exists()
