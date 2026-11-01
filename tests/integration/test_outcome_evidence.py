"""B3 offline acceptance: real B2/SQLite; authoritative verifier exists only in tests."""

import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest
from test_manual_handoff import cli, prepare, receipt_command
from test_runtime_operator_cli import CLI

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.outcome_evidence import (
    OutcomeEvent,
    OutcomeEventType,
    OutcomeVerification,
    OutcomeVerificationRequest,
    ReportOutcomeEvent,
    VerificationStatus,
)
from agentmine.application.contracts.records import OpportunitySave
from agentmine.application.errors import PortError
from agentmine.application.use_cases.context import content_reference
from agentmine.application.use_cases.outcome_evidence import OutcomeEvidenceWorkflow
from agentmine.bootstrap.operator import compose_operator
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.outcome_evidence import SQLiteOutcomeEvidenceRepository
from agentmine.presentation.operator_cli import run_cli

__all__ = ["cli"]


def test_outcome_vocabulary_does_not_confuse_selection_with_acceptance(cli: CLI) -> None:
    services, view = prepare(cli)
    services.confirm.execute(view.draft.reference, confirm=True)
    assert services.record.execute(receipt_command(cli)).applied
    assert len({OutcomeEventType.APPLICATION_SELECTED, OutcomeEventType.DELIVERABLE_ACCEPTED}) == 2
    assert cli.world.current().outcome is None


@dataclass
class TestOnlyAuthoritativeVerifier:
    __test__ = False
    world_cli: CLI
    status: VerificationStatus = VerificationStatus.VERIFIED
    barrier: Barrier | None = None
    calls: int = 0

    def accepts(self, decision: OutcomeVerification) -> bool:
        return decision.authority == Reference("TEST_ONLY:independent-authenticated-contract")

    def verify(self, request: OutcomeVerificationRequest) -> OutcomeVerification:
        self.calls += 1
        if self.barrier is not None:
            self.barrier.wait(timeout=20)
        return OutcomeVerification(
            request,
            self.status,
            Reference("TEST_ONLY:independent-authenticated-contract")
            if self.status == VerificationStatus.VERIFIED
            else None,
            "TEST ONLY independent fixture outcome; no real marketplace proof",
            self.world_cli.world.clock.now(),
        )


def workflow(cli: CLI, actor: str = "operator", ledger: str = "ledger") -> OutcomeEvidenceWorkflow:
    services = compose_operator(
        cli.world.database.path,
        Reference(ledger),
        Reference(actor),
        cli.world.clock,
        cli.world.source,
    )
    assert (
        services.submission_context is not None and services.submission_context.outcomes is not None
    )
    return services.submission_context.outcomes


def submitted(cli: CLI) -> OutcomeEvidenceWorkflow:
    svc, view = prepare(cli)
    svc.confirm.execute(view.draft.reference, confirm=True)
    svc.record.execute(receipt_command(cli))
    return workflow(cli)


def report(
    cli: CLI, event: OutcomeEventType = OutcomeEventType.DELIVERABLE_ACCEPTED
) -> ReportOutcomeEvent:
    capture = "TEST ONLY provider-looking report, never independent authority"
    return ReportOutcomeEvent(
        Reference("handoff-1"),
        Reference("outcome-1"),
        Reference("provider-event-1"),
        event,
        cli.world.clock.now(),
        cli.world.clock.now(),
        Reference("operator:report"),
        ReferencedText(content_reference(capture), capture),
    )


def dump(cli: CLI) -> tuple[str, ...]:
    with cli.world.database.transaction() as connection:
        return tuple(connection.iterdump())


def financial_rows(cli: CLI) -> tuple[tuple[object, ...], ...]:
    with cli.world.database.transaction() as connection:
        return tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM snapshots WHERE kind IN "
                "('budget','budget_audit','payment','payment_evidence',"
                "'manual_handoff_claim','manual_handoff_external_owner') ORDER BY kind,id"
            )
        )


@pytest.mark.parametrize("event", list(OutcomeEventType))
def test_all_operator_reports_remain_provisional(cli: CLI, event: OutcomeEventType) -> None:
    flow = submitted(cli)
    before = financial_rows(cli)
    stored = flow.record(report(cli, event))
    result = flow.verify(Reference("verification-1"), stored.reference)
    assert result.diagnostic == "BLOCKED" and not result.applied
    assert cli.world.current().outcome is None and cli.world.current().state.name == "SUBMITTED"
    assert cli.world.current().payment is None and cli.world.current().verified_revenue.amount == 0
    assert financial_rows(cli) == before
    assert workflow(cli).verify(Reference("verification-1"), stored.reference) == result


@pytest.mark.parametrize(
    "kind",
    [
        OutcomeEventType.DELIVERABLE_ACCEPTED,
        OutcomeEventType.DELIVERABLE_REJECTED,
        OutcomeEventType.APPLICATION_SELECTED,
        OutcomeEventType.UNKNOWN,
    ],
)
def test_test_only_authority_finalizes_only_deliverable_stage(
    cli: CLI, kind: OutcomeEventType
) -> None:
    flow = submitted(cli)
    event = flow.record(report(cli, kind))
    before = financial_rows(cli)
    verifier = TestOnlyAuthoritativeVerifier(cli)
    flow = replace(flow, verifier=verifier)
    result = flow.verify(Reference("verification-1"), event.reference)
    final = kind in (OutcomeEventType.DELIVERABLE_ACCEPTED, OutcomeEventType.DELIVERABLE_REJECTED)
    assert result.applied == final
    assert cli.world.current().state.name == (
        "ACCEPTED"
        if kind == OutcomeEventType.DELIVERABLE_ACCEPTED
        else "REJECTED"
        if kind == OutcomeEventType.DELIVERABLE_REJECTED
        else "SUBMITTED"
    )
    if kind == OutcomeEventType.DELIVERABLE_REJECTED:
        outcome = cli.world.current().outcome
        assert outcome is not None and outcome.rejection_reason is not None
    assert cli.world.current().payment is None and cli.world.current().verified_revenue.amount == 0
    assert cli.world.current().accepted_reward is None
    old = dump(cli)
    assert flow.verify(Reference("verification-1"), event.reference) == result
    assert verifier.calls == 1 and dump(cli) == old and financial_rows(cli) == before


@pytest.mark.parametrize(
    "change", ["digest", "event", "account", "submission", "actor", "ledger", "version", "listing"]
)
def test_wrong_identity_cannot_become_authoritative(cli: CLI, change: str) -> None:
    flow = submitted(cli)
    event = flow.record(report(cli))
    before = cli.world.current()
    if change in ("actor", "ledger"):
        with pytest.raises(PortError):
            workflow(
                cli,
                "wrong" if change == "actor" else "operator",
                "wrong" if change == "ledger" else "ledger",
            ).get(event.reference)
    elif change == "digest":
        with pytest.raises(PortError):
            flow.record(
                replace(
                    report(cli), capture=ReferencedText(Reference("sha256:" + "0" * 64), "changed")
                )
            )
    elif change == "event":
        with pytest.raises(PortError):
            flow.record(replace(report(cli), provider_event=Reference("other-event")))
    elif change in ("account", "submission"):
        with pytest.raises(PortError):
            flow.repository.record(
                replace(
                    event,
                    metadata=(
                        replace(event.metadata, account=Reference("wrong"))
                        if change == "account"
                        else replace(event.metadata, submission=Reference("wrong"))
                    ),
                )
            )
    else:
        draft = event.receipt.claim.draft
        with pytest.raises((PortError, ValueError)):
            if change == "version":
                altered = replace(
                    draft.envelope, deliverable=replace(draft.envelope.deliverable, version=99)
                )
            else:
                altered = replace(
                    draft.envelope,
                    request=replace(
                        draft.envelope.request,
                        channel=replace(
                            draft.envelope.request.channel, listing=Reference("wrong-listing")
                        ),
                    ),
                )
            flow.repository.record(
                replace(
                    event,
                    receipt=replace(
                        event.receipt,
                        claim=replace(event.receipt.claim, draft=replace(draft, envelope=altered)),
                    ),
                )
            )
    assert cli.world.current() == before


def test_event_identity_conflicts_and_duplicate_provider_event(cli: CLI) -> None:
    flow = submitted(cli)
    command = report(cli)
    event = flow.record(command)
    cli.world.clock.instant += timedelta(seconds=1)
    assert flow.record(command) == event
    with pytest.raises(PortError):
        flow.record(replace(command, reference=Reference("outcome-2")))
    with pytest.raises(PortError):
        flow.record(replace(command, event_type=OutcomeEventType.DELIVERABLE_REJECTED))
    assert flow.get(event.reference) == event


def test_stale_revision_retains_decision_and_blocks_finalization(cli: CLI) -> None:
    flow = submitted(cli)
    event = flow.record(report(cli))
    verifier = TestOnlyAuthoritativeVerifier(cli)
    original = SQLiteOutcomeEvidenceRepository.retain

    def stale(
        self: SQLiteOutcomeEvidenceRepository, decision: OutcomeVerification
    ) -> OutcomeVerification:
        saved = original(self, decision)
        repo = SQLiteOpportunityRepository(cli.world.database)
        current = repo.get(Reference("op"))
        assert current is not None
        repo.save(OpportunitySave(current.value, current.revision))
        return saved

    with patch.object(SQLiteOutcomeEvidenceRepository, "retain", stale), pytest.raises(PortError):
        replace(flow, verifier=verifier).verify(Reference("verification-1"), event.reference)
    view = workflow(cli).status(Reference("verification-1"))
    assert view.decision is not None and view.diagnostic == "CONFLICT" and not view.applied
    assert cli.world.current().outcome is None


@pytest.mark.parametrize(
    "kind",
    [
        "submission_evidence",
        "submission_capture",
        "outcome_event_owner",
        "outcome_event",
        "outcome_verification_request",
        "outcome_verification",
        "outcome",
        "opportunity",
        "outcome_application",
    ],
)
def test_crash_at_each_write_and_same_id_recovery(cli: CLI, kind: str) -> None:
    flow = submitted(cli)
    original = SQLiteDatabase.write
    command = report(cli)

    def crash(
        self: SQLiteDatabase,
        connection: sqlite3.Connection,
        stored_kind: str,
        key: str,
        value: object,
        revision: int,
        indexes: IndexValues,
    ) -> None:
        original(self, connection, stored_kind, key, value, revision, indexes)
        if kind == stored_kind:
            raise RuntimeError("TEST injected crash after write")

    positive = replace(flow, verifier=TestOnlyAuthoritativeVerifier(cli))
    with patch.object(SQLiteDatabase, "write", crash), pytest.raises(RuntimeError):
        event = positive.record(command)
        positive.verify(Reference("verification-1"), event.reference)
    assert cli.world.current().outcome is None and cli.world.current().verified_revenue.amount == 0
    event = positive.record(command)
    assert positive.verify(Reference("verification-1"), event.reference).applied
    assert workflow(cli).status(Reference("verification-1")).applied


def test_lost_ack_after_capture_and_final_apply(cli: CLI) -> None:
    flow = submitted(cli)
    command = report(cli)
    original = SQLiteOutcomeEvidenceRepository.record

    def lost(self: SQLiteOutcomeEvidenceRepository, event: OutcomeEvent) -> OutcomeEvent:
        original(self, event)
        raise RuntimeError("lost event acknowledgement")

    with patch.object(SQLiteOutcomeEvidenceRepository, "record", lost), pytest.raises(RuntimeError):
        flow.record(command)
    event = flow.record(command)
    original_apply = SQLiteOutcomeEvidenceRepository.apply

    def lost_apply(self: SQLiteOutcomeEvidenceRepository, decision: OutcomeVerification) -> None:
        original_apply(self, decision)
        raise RuntimeError("lost completion acknowledgement")

    with (
        patch.object(SQLiteOutcomeEvidenceRepository, "apply", lost_apply),
        pytest.raises(RuntimeError),
    ):
        replace(flow, verifier=TestOnlyAuthoritativeVerifier(cli)).verify(
            Reference("verification-1"), event.reference
        )
    old = dump(cli)
    assert (
        workflow(cli).verify(Reference("verification-1"), event.reference).applied
        and dump(cli) == old
    )


def test_concurrent_verification_has_one_outcome(cli: CLI) -> None:
    flow = submitted(cli)
    event = flow.record(report(cli))
    fixture = TestOnlyAuthoritativeVerifier(cli, barrier=Barrier(2))
    flow = replace(flow, verifier=fixture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: flow.verify(Reference("verification-1"), event.reference), range(2))
        )
    assert all(result.applied for result in results)
    assert results[0].decision == results[1].decision
    assert cli.world.current().verified_revenue.amount == 0


def test_terminal_outcome_and_verification_identity_are_immutable(cli: CLI) -> None:
    flow = submitted(cli)
    event = flow.record(report(cli))
    flow = replace(flow, verifier=TestOnlyAuthoritativeVerifier(cli))
    first = flow.verify(Reference("verification-1"), event.reference)
    other = flow.record(
        replace(
            report(cli, OutcomeEventType.DELIVERABLE_REJECTED),
            reference=Reference("outcome-2"),
            provider_event=Reference("event-2"),
        )
    )
    with pytest.raises(PortError):
        flow.verify(Reference("verification-1"), other.reference)
    with pytest.raises(PortError):
        flow.verify(Reference("verification-2"), other.reference)
    assert flow.status(Reference("verification-1")).decision == first.decision
    assert cli.world.current().state.name == "ACCEPTED"


def test_default_cli_reports_blocked_and_has_no_authority_flag(cli: CLI, tmp_path: Path) -> None:
    submitted(cli)
    path = tmp_path / "outcome.json"
    command = report(cli)
    path.write_text(
        json.dumps(
            {
                "provider_event": command.provider_event.value,
                "event_type": command.event_type.value,
                "event_at": command.event_at.isoformat(),
                "observed_at": command.observed_at.isoformat(),
                "provenance": command.provenance.value,
                "text": command.capture.text,
            }
        )
    )
    services = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )

    def invoke(args: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        code = run_cli(
            [
                "--db",
                str(cli.world.database.path),
                "--ledger",
                "ledger",
                "submission",
                "outcome",
                *args,
            ],
            services,
            output,
        )
        return code, json.loads(output.getvalue())

    assert (
        invoke(
            [
                "record",
                "--handoff-id",
                "handoff-1",
                "--evidence-id",
                "outcome-1",
                "--inputs",
                str(path),
            ]
        )[0]
        == 0
    )
    assert invoke(["show", "--evidence-id", "outcome-1"])[1]["verification_status"] == "UNVERIFIED"
    assert (
        invoke(["verify", "--evidence-id", "outcome-1", "--verification-id", "verification-1"])[1][
            "diagnostic"
        ]
        == "BLOCKED"
    )
    with pytest.raises(SystemExit):
        invoke(
            [
                "verify",
                "--evidence-id",
                "outcome-1",
                "--verification-id",
                "verification-1",
                "--authoritative",
            ]
        )
    data = json.loads(path.read_text())
    data["trust"] = "VERIFIED"
    path.write_text(json.dumps(data))
    assert (
        invoke(
            [
                "record",
                "--handoff-id",
                "handoff-1",
                "--evidence-id",
                "outcome-2",
                "--inputs",
                str(path),
            ]
        )[0]
        != 0
    )
    assert cli.world.current().outcome is None


def test_retained_verified_decision_cannot_activate_default_composition(cli: CLI) -> None:
    flow = submitted(cli)
    event = flow.record(report(cli))
    with (
        patch.object(
            SQLiteOutcomeEvidenceRepository, "apply", side_effect=RuntimeError("before final apply")
        ),
        pytest.raises(RuntimeError),
    ):
        replace(flow, verifier=TestOnlyAuthoritativeVerifier(cli)).verify(
            Reference("verification-1"), event.reference
        )
    before = dump(cli)
    with pytest.raises(PortError):
        workflow(cli).verify(Reference("verification-1"), event.reference)
    assert dump(cli) == before and cli.world.current().outcome is None
    assert (
        replace(flow, verifier=TestOnlyAuthoritativeVerifier(cli))
        .verify(Reference("verification-1"), event.reference)
        .applied
    )


def test_unknown_decision_and_wrong_verifier_binding(cli: CLI) -> None:
    flow = submitted(cli)
    event = flow.record(report(cli))
    result = replace(
        flow, verifier=TestOnlyAuthoritativeVerifier(cli, VerificationStatus.UNKNOWN)
    ).verify(Reference("unknown-verification"), event.reference)
    assert result.diagnostic == "UNKNOWN" and not result.applied
    original = TestOnlyAuthoritativeVerifier.verify

    def wrong(
        self: TestOnlyAuthoritativeVerifier, request: OutcomeVerificationRequest
    ) -> OutcomeVerification:
        return original(self, replace(request, reference=Reference("wrong-verification")))

    with patch.object(TestOnlyAuthoritativeVerifier, "verify", wrong), pytest.raises(PortError):
        replace(flow, verifier=TestOnlyAuthoritativeVerifier(cli)).verify(
            Reference("verification-2"), event.reference
        )
    assert cli.world.current().outcome is None


def test_unrelated_opportunity_snapshot_and_corrupt_retained_capture_fail(cli: CLI) -> None:
    from copy import copy

    from agentmine.application.contracts.records import Versioned

    flow = submitted(cli)
    event = flow.record(report(cli))
    snapshot = flow.handoffs.execute(Reference("handoff-1")).opportunity
    assert snapshot is not None
    unrelated = copy(snapshot.value)
    object.__setattr__(unrelated, "reference", Reference("unrelated"))
    request = OutcomeVerificationRequest(
        Reference("unrelated-request"), event, Versioned(unrelated, snapshot.revision)
    )
    with pytest.raises(PortError):
        flow.repository.prepare(request)
    with cli.world.database.transaction(write=True) as connection:
        connection.execute(
            "DELETE FROM snapshots WHERE kind='submission_capture' AND id='outcome-1'"
        )
    with pytest.raises(PortError):
        flow.get(event.reference)
    assert cli.world.current().outcome is None
