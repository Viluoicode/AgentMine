"""Offline B5 acceptance; no payment provider or settlement authority."""

import socket
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from inspect import unwrap
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from test_outcome_evidence import TestOnlyAuthoritativeVerifier, submitted
from test_outcome_evidence import report as outcome_report
from test_runtime_operator_cli import CLI
from test_runtime_operator_cli import cli as base_cli

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.payment_evidence import (
    PaymentEvidenceStatus,
    PaymentObservation,
    PaymentReportRequest,
)
from agentmine.application.contracts.records import OpportunitySave
from agentmine.application.contracts.submission import (
    PaymentStatus,
    PaymentVerificationRequest,
    PaymentVerificationResult,
)
from agentmine.application.errors import PortError
from agentmine.application.use_cases.context import content_reference
from agentmine.application.use_cases.settlement import VerifyPayment
from agentmine.bootstrap.operator import compose_operator
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.payment_evidence import SQLitePaymentEvidenceRepository
from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository
from agentmine.presentation.payment_evidence_cli import PaymentEvidenceServices


def test_payment_evidence_has_no_verified_authority_status() -> None:
    assert "VERIFIED" not in PaymentEvidenceStatus.__members__


@pytest.fixture(scope="module")
def payment_template(tmp_path_factory: pytest.TempPathFactory) -> CLI:
    root = tmp_path_factory.mktemp("B5_ISOLATED_TEST_ONLY")
    creator = cast(Callable[[Path], CLI], unwrap(base_cli))
    # Explicitly test-only source/clock/authority; real worker, QA, approval, B2 and B3.
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("no network")),
        patch.object(socket, "create_connection", side_effect=AssertionError("no network")),
    ):
        cli = creator(root)
        flow = submitted(cli)
        with (
            sqlite3.connect(cli.world.database.path) as source,
            sqlite3.connect(root / "before-outcome.sqlite3") as target,
        ):
            source.backup(target)
        event = flow.record(outcome_report(cli))
        assert (
            replace(flow, verifier=TestOnlyAuthoritativeVerifier(cli))
            .verify(Reference("verification-1"), event.reference)
            .applied
        )
    assert cli.world.current().payment is None and cli.world.current().verified_revenue.amount == 0
    return cli


@pytest.fixture
def payment_cli(payment_template: CLI, tmp_path: Path) -> CLI:
    path = tmp_path / "B5_TEST_ONLY.sqlite3"
    with (
        sqlite3.connect(payment_template.world.database.path) as source,
        sqlite3.connect(path) as target,
    ):
        source.backup(target)
    clock = replace(payment_template.world.clock)
    world = replace(
        payment_template.world,
        database=SQLiteDatabase(path),
        clock=clock,
        source=replace(payment_template.world.source, clock=clock),
    )
    return replace(payment_template, world=world)


def services(cli: CLI, actor: str = "operator", ledger: str = "ledger") -> PaymentEvidenceServices:
    composed = compose_operator(
        cli.world.database.path,
        Reference(ledger),
        Reference(actor),
        cli.world.clock,
        cli.world.source,
    )
    assert (
        composed.submission_context is not None and composed.submission_context.payments is not None
    )
    return composed.submission_context.payments


def request(cli: CLI) -> PaymentReportRequest:
    text = "TEST ONLY operator payment statement; no authenticated settlement facts"
    outcome = cli.world.current().outcome
    assert outcome is not None
    return PaymentReportRequest(
        Reference("payment-report-1"),
        Reference("handoff-1"),
        outcome.evidence,
        None,
        cli.world.clock.now(),
        Reference("operator:unverified-statement"),
        ReferencedText(content_reference(text), text),
    )


def dump(cli: CLI) -> tuple[str, ...]:
    with cli.world.database.transaction() as connection:
        return tuple(connection.iterdump())


def protected(cli: CLI) -> tuple[tuple[object, ...], ...]:
    with cli.world.database.transaction() as connection:
        return tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM snapshots WHERE kind NOT IN "
                "('provisional_payment_report','provisional_payment_observation',"
                "'submission_evidence','submission_capture') ORDER BY kind,id"
            )
        )


def test_unknown_facts_and_exact_accepted_lineage(payment_cli: CLI) -> None:
    cli = payment_cli
    svc = services(cli)
    before = protected(cli)
    view = svc.record.execute(request(cli))
    assert (
        view.status == PaymentEvidenceStatus.UNVERIFIED
        and view.report is not None
        and view.observation is not None
    )
    assert view.report.source_snapshot.value.outcome == cli.world.current().outcome
    assert view.report.source_snapshot.value.submission == cli.world.current().submission
    assert view.observation.metadata.trust.name == "OPERATOR_REPORTED"
    assert view.observation.metadata.state.name == "UNVERIFIED"
    assert all(
        getattr(view.report.request, name) is None
        for name in (
            "asset_hint",
            "network_hint",
            "recipient_hint",
            "amount_hint",
            "transaction_hint",
        )
    )
    assert (
        cli.world.current().accepted_reward is None
        and cli.world.current().verified_revenue.amount == 0
    )
    assert protected(cli) == before
    assert services(cli).get.execute(view.reference) == view


@pytest.mark.parametrize(
    "field",
    ["asset_hint", "network_hint", "recipient_hint", "amount_hint", "transaction_hint", "url_hint"],
)
def test_hints_never_choose_actual_settlement(payment_cli: CLI, field: str) -> None:
    cli = payment_cli
    command = request(cli)
    hint = (
        "https://example.test/operator-reference"
        if field == "url_hint"
        else "TEST_ONLY_UNVERIFIED_HINT"
    )
    if field == "asset_hint":
        command = replace(command, asset_hint=hint)
    elif field == "network_hint":
        command = replace(command, network_hint=hint)
    elif field == "recipient_hint":
        command = replace(command, recipient_hint=hint)
    elif field == "amount_hint":
        command = replace(command, amount_hint=hint)
    elif field == "transaction_hint":
        command = replace(command, transaction_hint=hint)
    else:
        command = replace(command, url_hint=hint)
    view = services(cli).record.execute(command)
    assert view.status == PaymentEvidenceStatus.UNVERIFIED and cli.world.current().payment is None
    assert cli.world.current().verified_revenue.amount == 0
    assert not hasattr(view.observation, "reward")


@pytest.mark.parametrize("owner", ["actor", "ledger"])
def test_wrong_owner_rejected_on_record_and_read(payment_cli: CLI, owner: str) -> None:
    cli = payment_cli
    services(cli).record.execute(request(cli))
    bad = services(
        cli, "wrong" if owner == "actor" else "operator", "wrong" if owner == "ledger" else "ledger"
    )
    with pytest.raises(PortError):
        bad.get.execute(Reference("payment-report-1"))
    with pytest.raises(PortError):
        bad.record.execute(request(cli))


@pytest.mark.parametrize("field", ["outcome", "account", "version", "submission"])
def test_conflicting_binding_is_rejected(payment_cli: CLI, field: str) -> None:
    cli = payment_cli
    svc = services(cli)
    command = request(cli)
    if field == "outcome":
        with pytest.raises(PortError):
            svc.record.execute(replace(command, outcome_reference=Reference("unrelated-outcome")))
    else:
        report = svc.record.execute(command).report
        assert report is not None
        with pytest.raises((PortError, ValueError)):
            if field == "account":
                changed = replace(
                    report, account=replace(report.account, reference=Reference("wrong-account"))
                )
            else:
                from copy import copy

                from agentmine.application.contracts.records import Versioned

                op = copy(report.source_snapshot.value)
                assert op.submission is not None
                submission = (
                    replace(op.submission, reference=Reference("wrong-submission"))
                    if field == "submission"
                    else replace(
                        op.submission, deliverable=replace(op.submission.deliverable, version=99)
                    )
                )
                object.__setattr__(op, "submission", submission)
                changed = replace(
                    report, source_snapshot=Versioned(op, report.source_snapshot.revision)
                )
            svc.record.repository.prepare(changed)
    assert cli.world.current().verified_revenue.amount == 0


def test_duplicate_payload_conflict_and_original_timestamp(payment_cli: CLI) -> None:
    cli = payment_cli
    svc = services(cli)
    command = request(cli)
    view = svc.record.execute(command)
    cli.world.clock.instant += timedelta(seconds=10)
    before = dump(cli)
    assert svc.record.execute(command) == view and dump(cli) == before
    with pytest.raises(PortError):
        svc.record.execute(replace(command, amount_hint="TEST_ONLY_DIFFERENT"))
    text = "Different raw capture"
    with pytest.raises(PortError):
        svc.record.execute(replace(command, capture=ReferencedText(content_reference(text), text)))
    assert dump(cli) == before


@pytest.mark.parametrize(
    "kind",
    [
        "provisional_payment_report",
        "submission_capture",
        "submission_evidence",
        "provisional_payment_observation",
    ],
)
def test_write_crash_and_original_id_recovery(payment_cli: CLI, kind: str) -> None:
    cli = payment_cli
    svc = services(cli)
    before = protected(cli)
    original = SQLiteDatabase.write

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
        if stored_kind == kind:
            raise RuntimeError("TEST write crash")

    with patch.object(SQLiteDatabase, "write", crash), pytest.raises(RuntimeError):
        svc.record.execute(request(cli))
    view = services(cli).get.execute(Reference("payment-report-1"))
    expected = (
        PaymentEvidenceStatus.MISSING
        if kind == "provisional_payment_report"
        else PaymentEvidenceStatus.CAPTURE_RETAINED
        if kind == "provisional_payment_observation"
        else PaymentEvidenceStatus.CAPTURE_PENDING
    )
    assert view.status == expected
    assert services(cli).record.execute(request(cli)).status == PaymentEvidenceStatus.UNVERIFIED
    assert protected(cli) == before


def test_stale_snapshot_after_capture_is_preserved_not_rebound(payment_cli: CLI) -> None:
    cli = payment_cli
    svc = services(cli)
    original = SQLitePaymentEvidenceRepository.attach

    def stale(self: SQLitePaymentEvidenceRepository, observation: PaymentObservation) -> None:
        repo = SQLiteOpportunityRepository(cli.world.database)
        old = repo.get(Reference("op"))
        assert old is not None
        repo.save(OpportunitySave(old.value, old.revision))
        original(self, observation)

    with patch.object(SQLitePaymentEvidenceRepository, "attach", stale), pytest.raises(PortError):
        svc.record.execute(request(cli))
    view = svc.get.execute(Reference("payment-report-1"))
    assert (
        view.status == PaymentEvidenceStatus.CONFLICT
        and view.capture_retained
        and view.observation is None
    )
    with pytest.raises(PortError):
        svc.record.execute(request(cli))
    assert cli.world.current().payment is None


def test_lost_attach_ack_and_concurrent_equal_writes(payment_cli: CLI) -> None:
    cli = payment_cli
    svc = services(cli)
    command = request(cli)
    original = SQLitePaymentEvidenceRepository.attach

    def lost(self: SQLitePaymentEvidenceRepository, observation: PaymentObservation) -> None:
        original(self, observation)
        raise RuntimeError("lost acknowledgement")

    with patch.object(SQLitePaymentEvidenceRepository, "attach", lost), pytest.raises(RuntimeError):
        svc.record.execute(command)
    before = dump(cli)
    with ThreadPoolExecutor(max_workers=2) as pool:
        views = list(pool.map(lambda _: services(cli).record.execute(command), range(2)))
    assert views[0] == views[1] and dump(cli) == before
    # Fresh concurrent IDs retain reports, never monetary ownership by a transaction hint.
    another = replace(
        command, reference=Reference("payment-report-2"), transaction_hint="SAME_TEST_ONLY_HASH"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        views = list(pool.map(lambda _: services(cli).record.execute(another), range(2)))
    assert views[0] == views[1]
    assert cli.world.current().verified_revenue.amount == 0


def test_legacy_verify_payment_cannot_consume_b5_report(payment_cli: CLI) -> None:
    cli = payment_cli
    services(cli).record.execute(replace(request(cli), transaction_hint="TEST_ONLY_HASH"))
    repository = SQLiteSubmissionRepository(cli.world.database)
    submission = cli.world.current().submission
    assert submission is not None
    assert repository.payment_history(submission.reference) == ()

    class Unavailable:
        def verify_payment(self, request: PaymentVerificationRequest) -> PaymentVerificationResult:
            return PaymentVerificationResult(
                request.submission.reference,
                PaymentStatus.UNVERIFIABLE,
                cli.world.clock.now(),
                None,
                "No independent settlement provider configured",
            )

    result = VerifyPayment(
        SQLiteOpportunityRepository(cli.world.database), Unavailable(), cli.world.clock, repository
    ).execute(Reference("op"))
    assert (
        result.state.name == "ACCEPTED"
        and result.payment is None
        and result.verified_revenue.amount == 0
    )


def test_existing_legacy_capture_is_not_adopted(payment_cli: CLI) -> None:
    cli = payment_cli
    svc = services(cli)
    command = request(cli)
    from agentmine.application.contracts.submission_context import (
        EvidenceState,
        EvidenceTrust,
        EvidenceType,
        ImportEvidence,
    )

    op = cli.world.current()
    assert op.submission is not None
    svc.record.evidence.import_report(
        ImportEvidence(
            command.reference,
            svc.record.handoffs.execute(Reference("handoff-1")).draft.envelope.reference,
            op.submission.reference,
            EvidenceType.PAYMENT_REPORT,
            EvidenceTrust.OPERATOR_REPORTED,
            EvidenceState.UNVERIFIED,
            None,
            None,
            command.event_at,
            command.observed_at,
            command.provenance,
            command.capture,
        )
    )
    with pytest.raises(PortError):
        svc.record.execute(command)


def test_cli_explicit_unknowns_and_unavailable_authority(payment_cli: CLI, tmp_path: Path) -> None:
    import io
    import json

    from agentmine.presentation.operator_cli import run_cli

    cli = payment_cli
    command = request(cli)
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "outcome_id": command.outcome_reference.value
                if command.outcome_reference
                else None,
                "observed_at": command.observed_at.isoformat(),
                "provenance": command.provenance.value,
                "text": command.capture.text,
            }
        )
    )
    composed = compose_operator(
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
                "payment",
                *args,
            ],
            composed,
            output,
        )
        return code, json.loads(output.getvalue())

    code, value = invoke(
        [
            "record",
            "--handoff-id",
            "handoff-1",
            "--evidence-id",
            "payment-report-1",
            "--inputs",
            str(path),
        ]
    )
    assert code == 0 and value["status"] == "UNVERIFIED"
    assert (
        value["independently_verified_payment"] is False
        and value["current_paid_authority"] == "UNAVAILABLE"
    )
    assert (
        value["actual_asset"]
        == value["actual_network"]
        == value["actual_recipient"]
        == value["actual_amount"]
        == "UNKNOWN"
    )
    assert invoke(["show", "--evidence-id", "payment-report-1"])[1] == value
    assert invoke(["status", "--evidence-id", "payment-report-1"])[1] == value
    assert invoke(["status", "--evidence-id", "absent"])[1]["status"] == "MISSING"
    with pytest.raises(SystemExit):
        invoke(["verify", "--evidence-id", "payment-report-1"])
    with pytest.raises(SystemExit):
        invoke(
            [
                "record",
                "--handoff-id",
                "handoff-1",
                "--evidence-id",
                "other",
                "--inputs",
                str(path),
                "--authoritative",
            ]
        )
    data = json.loads(path.read_text())
    data["verified"] = True
    path.write_text(json.dumps(data))
    assert (
        invoke(
            ["record", "--handoff-id", "handoff-1", "--evidence-id", "other", "--inputs", str(path)]
        )[0]
        != 0
    )


@pytest.mark.parametrize(
    "case", ["digest", "future", "before-submission", "secret", "unsafe-url", "numeric-amount"]
)
def test_invalid_report_rejected_before_persistence(payment_cli: CLI, case: str) -> None:
    cli = payment_cli
    command = request(cli)
    before = dump(cli)
    with pytest.raises((PortError, ValueError)):
        if case == "digest":
            command = replace(
                command,
                capture=ReferencedText(Reference("sha256:" + "0" * 64), command.capture.text),
            )
        elif case == "future":
            command = replace(command, observed_at=cli.world.clock.now() + timedelta(days=1))
        elif case == "before-submission":
            command = replace(command, event_at=cli.world.clock.now() - timedelta(days=1))
        elif case == "secret":
            command = replace(
                command,
                capture=ReferencedText(
                    content_reference("Bearer abcdefghijklmnopqrstuvwxyz123456"),
                    "Bearer abcdefghijklmnopqrstuvwxyz123456",
                ),
            )
        elif case == "unsafe-url":
            command = replace(command, url_hint="http://127.0.0.1/private")
        else:
            command = replace(command, amount_hint=12.3)  # type: ignore[arg-type]
        services(cli).record.execute(command)
    assert dump(cli) == before


def test_deleted_or_corrupt_capture_has_explicit_diagnostic(payment_cli: CLI) -> None:
    cli = payment_cli
    svc = services(cli)
    svc.record.execute(request(cli))
    with cli.world.database.transaction(write=True) as connection:
        connection.execute(
            "DELETE FROM snapshots WHERE kind='submission_capture' AND id='payment-report-1'"
        )
    view = svc.get.execute(Reference("payment-report-1"))
    assert view.status == PaymentEvidenceStatus.MISSING and not view.capture_retained
    assert cli.world.current().payment is None


def test_completed_historical_readback_and_retry_never_rewrite(payment_cli: CLI) -> None:
    cli = payment_cli
    svc = services(cli)
    command = request(cli)
    old = svc.record.execute(command)
    repo = SQLiteOpportunityRepository(cli.world.database)
    current = repo.get(Reference("op"))
    assert current is not None
    repo.save(OpportunitySave(current.value, current.revision))
    before = dump(cli)
    view = services(cli).record.execute(command)
    assert (
        view.status == PaymentEvidenceStatus.CONFLICT
        and view.report == old.report
        and view.observation == old.observation
    )
    assert dump(cli) == before


def test_reporting_has_no_domain_payment_or_legacy_dispatch(payment_cli: CLI) -> None:
    from agentmine.domain.opportunity import Opportunity

    cli = payment_cli
    before = protected(cli)
    with (
        patch.object(Opportunity, "verify_payment", side_effect=AssertionError("no PAID")),
        patch.object(VerifyPayment, "execute", side_effect=AssertionError("no legacy payment")),
    ):
        svc = services(cli)
        assert not hasattr(svc.record, "verifier")
        assert svc.record.execute(request(cli)).status == PaymentEvidenceStatus.UNVERIFIED
    assert protected(cli) == before


def test_submission_without_outcome_keeps_absent_identity(payment_cli: CLI) -> None:
    cli = payment_cli
    with (
        sqlite3.connect(cli.root.parent / "before-outcome.sqlite3") as source,
        sqlite3.connect(cli.world.database.path) as target,
    ):
        source.backup(target)
    assert cli.world.current().outcome is None
    text = "Unknown payment report before any accepted Outcome"
    command = PaymentReportRequest(
        Reference("payment-report-1"),
        Reference("handoff-1"),
        None,
        None,
        cli.world.clock.now(),
        Reference("operator:report"),
        ReferencedText(content_reference(text), text),
    )
    view = services(cli).record.execute(command)
    assert view.report is not None and view.report.source_snapshot.value.outcome is None
    assert view.status == PaymentEvidenceStatus.UNVERIFIED and cli.world.current().payment is None


def test_missing_outcome_record_reports_lineage_conflict(payment_cli: CLI) -> None:
    cli = payment_cli
    svc = services(cli)
    svc.record.execute(request(cli))
    with cli.world.database.transaction(write=True) as connection:
        connection.execute("DELETE FROM snapshots WHERE kind='outcome'")
    before = dump(cli)
    assert svc.get.execute(Reference("payment-report-1")).status == PaymentEvidenceStatus.CONFLICT
    assert dump(cli) == before and cli.world.current().payment is None


@pytest.mark.parametrize("failure", ["missing-input", "wrong-outcome"])
def test_cli_error_outputs_keep_payment_authority_unavailable(
    payment_cli: CLI, tmp_path: Path, failure: str
) -> None:
    import io
    import json

    from agentmine.presentation.operator_cli import run_cli

    cli = payment_cli
    path = tmp_path / "error-report.json"
    if failure == "wrong-outcome":
        path.write_text(
            json.dumps(
                {
                    "outcome_id": "unrelated",
                    "observed_at": cli.world.clock.now().isoformat(),
                    "provenance": "operator:report",
                    "text": "Unverified report",
                }
            )
        )
    composed = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    output = io.StringIO()
    code = run_cli(
        [
            "--db",
            str(cli.world.database.path),
            "--ledger",
            "ledger",
            "submission",
            "payment",
            "record",
            "--evidence-id",
            "payment-report-1",
            "--handoff-id",
            "handoff-1",
            "--inputs",
            str(path),
        ],
        composed,
        output,
    )
    value = json.loads(output.getvalue())
    assert code != 0
    assert value["independently_verified_payment"] is False
    assert value["current_paid_authority"] == "UNAVAILABLE"
    assert value["settlement_identity_status"] == "UNKNOWN"
    assert value["verification_status"] == "UNVERIFIED"
    assert value["missing_or_conflicting_evidence"] is True
