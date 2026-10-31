"""Offline submission-context foundation: real SQLite, worker, QA and reviews."""

from pathlib import Path

import pytest
from test_operational_deliverable_qa import execute_data, qa
from test_runtime_operator_cli import CLI, cli

from agentmine.application.contracts.submission import SubmissionMode
from agentmine.application.contracts.submission_context import (
    AccountIdentity,
    ChannelKind,
    EffectKnowledge,
    OutboundMaterial,
    PrepareEnvelope,
    SubmissionChannel,
    SubmissionEnvelope,
    SubmissionEvidence,
)
from agentmine.bootstrap.operator import compose_operator
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.presentation.submission_context_cli import SubmissionContextServices

__all__ = ["cli"]


def services(
    cli: CLI, actor: str = "operator", ledger: str = "ledger"
) -> SubmissionContextServices:
    result = compose_operator(
        cli.world.database.path,
        Reference(ledger),
        Reference(actor),
        cli.world.clock,
        cli.world.source,
    ).submission_context
    assert result is not None
    return result


def command(reference: str = "context-1", execution: str = "cli-exec") -> PrepareEnvelope:
    return PrepareEnvelope(
        Reference(reference),
        Reference(execution),
        SubmissionMode.MANUAL,
        AccountIdentity(Reference("account-1"), Reference("provider-1"), "explicit-user"),
        SubmissionChannel(
            Reference("channel-1"),
            Reference("provider-1"),
            Reference("source:item"),
            ChannelKind.MANUAL_FORM,
            "https://example.test/submit",
            Reference("operator:permission-note"),
            ("name", "approved data"),
            EffectKnowledge.UNKNOWN,
            (),
        ),
        OutboundMaterial("Exact operator-approved message", ("data.csv",), ()),
    )


def test_prepare_is_immutable_offline_and_reopens(cli: CLI, tmp_path: Path) -> None:
    from dataclasses import replace

    from agentmine.application.errors import PortError

    execute_data(cli)
    assert qa(cli)[1]["qa_outcome"] == "PASS"
    # Bind to retained source identity, never an arbitrary destination listing.
    request = command()
    observation = SQLiteOpportunityRepository(cli.world.database).get_observation(Reference("op"))
    assert observation is not None
    request = replace(
        request, channel=replace(request.channel, listing=observation.source_reference)
    )
    with cli.world.database.transaction() as connection:
        before = tuple(connection.iterdump())
    envelope = services(cli).prepare.execute(request)
    assert envelope.deliverable.version == 1
    assert envelope.account == request.account and envelope.mode == SubmissionMode.MANUAL
    assert services(cli).get.execute(envelope.reference) == envelope
    assert services(cli).prepare.execute(request) == envelope
    with pytest.raises(PortError):
        services(cli).prepare.execute(
            replace(request, outbound=replace(request.outbound, text="edit"))
        )
    assert cli.world.current().approval is None and cli.world.current().submission is None
    assert cli.world.current().verified_revenue.amount == 0
    with cli.world.database.transaction() as connection:
        after = tuple(connection.iterdump())
    assert before != after  # Only the immutable context is added, never a send or payment.


def current_request(
    cli: CLI, reference: str = "context-1", execution: str = "cli-exec"
) -> PrepareEnvelope:
    from dataclasses import replace

    observation = SQLiteOpportunityRepository(cli.world.database).get_observation(Reference("op"))
    assert observation is not None
    request = command(reference, execution)
    return replace(request, channel=replace(request.channel, listing=observation.source_reference))


def completed(cli: CLI) -> PrepareEnvelope:
    execute_data(cli)
    assert qa(cli)[1]["qa_outcome"] == "PASS"
    return current_request(cli)


@pytest.mark.parametrize("changed", ["account", "channel", "mode", "outbound"])
def test_changed_scope_requires_new_review(cli: CLI, changed: str) -> None:
    from dataclasses import replace

    from agentmine.application.errors import PortError

    req = completed(cli)
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    first = services(cli).prepare.execute(req)
    ops.prepare.for_submission(
        Reference("review-1"), Reference("op"), Reference("ledger"), first.scope
    )
    new = replace(req, reference=Reference("context-2"))
    if changed == "account":
        new = replace(
            new,
            account=replace(
                new.account, reference=Reference("account-2"), effective_account="another-user"
            ),
        )
    elif changed == "channel":
        new = replace(
            new,
            channel=replace(
                new.channel,
                reference=Reference("channel-2"),
                destination="https://example.test/other",
            ),
        )
    elif changed == "mode":
        new = replace(
            new,
            mode=SubmissionMode.API,
            channel=replace(
                new.channel, reference=Reference("channel-api"), kind=ChannelKind.API_INTENDED
            ),
        )
    else:
        new = replace(new, outbound=replace(new.outbound, text="Different exact outbound bytes"))
    second = services(cli).prepare.execute(new)
    assert second.scope != first.scope
    with pytest.raises(PortError):
        ops.prepare.for_submission(
            Reference("review-1"), Reference("op"), Reference("ledger"), second.scope
        )
    review = ops.prepare.for_submission(
        Reference("review-2"), Reference("op"), Reference("ledger"), second.scope
    )
    assert ops.get_review.execute(review.reference).submission_envelope == second
    assert cli.world.current().approval is None and cli.world.current().submission is None


def test_applied_approval_is_separate_from_partial_decision(cli: CLI) -> None:
    from unittest.mock import patch

    from agentmine.application.errors import PortError, PortErrorCode
    from agentmine.domain.approval import OperatorDecision

    envelope = services(cli).prepare.execute(completed(cli))
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    review = ops.prepare.for_submission(
        Reference("context-review"), Reference("op"), Reference("ledger"), envelope.scope
    )
    with patch.object(
        SQLiteOpportunityRepository,
        "save",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "save", "injected"),
    ):
        with pytest.raises(PortError):
            ops.decide.execute(review.reference, OperatorDecision.APPROVE)
    assert not services(cli).consent.execute(review.reference).applied
    assert cli.world.current().approval is None
    # No source refresh or any external provider is needed for offline scope consent.
    with patch.object(
        type(cli.world.source), "refresh", side_effect=AssertionError("B1 is offline")
    ):
        ops.decide.execute(review.reference, OperatorDecision.APPROVE)
    consent = services(cli).consent.execute(review.reference)
    assert consent.applied and consent.envelope == envelope
    assert cli.world.current().submission is None and cli.world.current().payment is None
    assert cli.world.current().verified_revenue.amount == 0


@pytest.mark.parametrize("actor,ledger", [("wrong", "ledger"), ("operator", "wrong")])
def test_actor_and_ledger_bind_all_reads_and_consent(cli: CLI, actor: str, ledger: str) -> None:
    from agentmine.application.errors import PortError

    req = completed(cli)
    envelope = services(cli).prepare.execute(req)
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    ops.prepare.for_submission(
        Reference("review"), Reference("op"), Reference("ledger"), envelope.scope
    )
    wrong = services(cli, actor, ledger)
    for action in (
        lambda: wrong.get.execute(envelope.reference),
        lambda: wrong.prepare.execute(req),
        lambda: wrong.consent.execute(Reference("review")),
    ):
        with pytest.raises(PortError):
            action()
    wrong_ops = compose_operator(
        cli.world.database.path,
        Reference(ledger),
        Reference(actor),
        cli.world.clock,
        cli.world.source,
    )
    with pytest.raises(PortError):
        wrong_ops.get_review.execute(Reference("review"))


@pytest.mark.parametrize("same", [False, True])
def test_concurrent_preparation_and_lost_ack_readback(cli: CLI, same: bool) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from unittest.mock import patch

    from agentmine.application.errors import PortError, PortErrorCode
    from agentmine.infrastructure.sqlite.submission_context import SQLiteSubmissionContextRepository

    req = completed(cli)
    requests = [req, req if same else replace(req, reference=Reference("second"))]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda request: services(cli).prepare.execute(request), requests))
    assert (results[0] == results[1]) is same
    original = SQLiteSubmissionContextRepository.prepare

    def lost_ack(
        repository: SQLiteSubmissionContextRepository, envelope: SubmissionEnvelope
    ) -> SubmissionEnvelope:
        original(repository, envelope)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "prepare", "lost acknowledgement")

    another = replace(req, reference=Reference("lost-ack"))
    with patch.object(SQLiteSubmissionContextRepository, "prepare", lost_ack):
        with pytest.raises(PortError):
            services(cli).prepare.execute(another)
    assert services(cli).prepare.execute(another) == services(cli).get.execute(another.reference)


@pytest.mark.parametrize(
    "kind", ["submission_account", "submission_channel", "submission_envelope", "submission_scope"]
)
def test_prepare_rolls_back_every_write(cli: CLI, kind: str) -> None:
    import sqlite3
    from unittest.mock import patch

    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase

    req = completed(cli)
    with cli.world.database.transaction() as connection:
        before = tuple(connection.iterdump())
    original = SQLiteDatabase.write

    def failure(
        database: SQLiteDatabase,
        connection: sqlite3.Connection,
        written_kind: str,
        key: str,
        value: object,
        revision: int,
        indexes: IndexValues,
    ) -> None:
        original(database, connection, written_kind, key, value, revision, indexes)
        if written_kind == kind:
            raise sqlite3.OperationalError("injected after write")

    with patch.object(SQLiteDatabase, "write", failure):
        with pytest.raises(PortError):
            services(cli).prepare.execute(req)
    with cli.world.database.transaction() as connection:
        assert tuple(connection.iterdump()) == before
    assert services(cli).prepare.execute(req).request == req


def test_identical_v2_bytes_do_not_transfer_scope_approval(cli: CLI) -> None:
    from test_revision_operator_qa import approve, execute, prepare

    from agentmine.application.errors import PortError
    from agentmine.domain.approval import OperatorDecision

    first = services(cli).prepare.execute(completed(cli))
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    for identity in ("old-undecided", "request-rework"):
        ops.prepare.for_submission(
            Reference(identity), Reference("op"), Reference("ledger"), first.scope
        )
    ops.decide.execute(Reference("request-rework"), OperatorDecision.REQUEST_REVISION)
    assert prepare(cli, trigger="operator", trigger_id="request-rework")[0] == 0
    assert approve(cli)[0] == 0 and execute(cli)[0] == 0
    assert (
        cli.command(
            "work",
            "qa",
            "--execution-id",
            "revision-2-exec",
            "--inspection-id",
            "qa-v2",
            "--confirm",
        )[1]["qa_outcome"]
        == "PASS"
    )
    second = services(cli).prepare.execute(current_request(cli, "context-v2", "revision-2-exec"))
    assert first.deliverable.content_reference == second.deliverable.content_reference
    assert second.deliverable.version == 2 and first.scope != second.scope
    with pytest.raises(PortError):
        ops.decide.execute(Reference("old-undecided"), OperatorDecision.APPROVE)
    review = ops.prepare.for_submission(
        Reference("new-v2"), Reference("op"), Reference("ledger"), second.scope
    )
    ops.decide.execute(review.reference, OperatorDecision.APPROVE)
    assert services(cli).consent.execute(review.reference).applied
    assert not services(cli).consent.execute(Reference("old-undecided")).applied
    assert services(cli).get.execute(first.reference) == first
    assert (
        cli.world.current().submission is None and cli.world.current().verified_revenue.amount == 0
    )


@pytest.mark.parametrize("state", ["unknown", "unverified", "conflict"])
@pytest.mark.parametrize("kind", ["receipt_report", "outcome_report", "payment_report"])
def test_provisional_evidence_never_creates_final_authority(
    cli: CLI, state: str, kind: str
) -> None:
    from datetime import timedelta

    from agentmine.application.contracts.ai import ReferencedText
    from agentmine.application.contracts.submission_context import (
        EvidenceState,
        EvidenceTrust,
        EvidenceType,
        ImportEvidence,
    )
    from agentmine.application.use_cases.context import content_reference

    envelope = services(cli).prepare.execute(completed(cli))
    raw = "Operator says accepted and paid; this is not independent proof"
    report = ImportEvidence(
        Reference("evidence-1"),
        envelope.reference,
        Reference("reported-submission-hint"),
        EvidenceType(kind),
        EvidenceTrust.OPERATOR_REPORTED,
        EvidenceState(state),
        None,
        Reference("reported-event"),
        None,
        cli.world.clock.now(),
        Reference("operator:note"),
        ReferencedText(content_reference(raw), raw),
    )
    before = cli.world.current()
    ledger = cli.world.budget().ledger.get(Reference("ledger"))
    value = services(cli).record.import_report(report)
    cli.world.clock.instant += timedelta(seconds=1)
    assert services(cli).record.import_report(report) == value
    assert services(cli).evidence.execute(value.reference) == value
    assert (
        cli.world.current() == before
        and cli.world.budget().ledger.get(Reference("ledger")) == ledger
    )
    assert cli.world.current().outcome is None and cli.world.current().payment is None
    assert cli.world.current().verified_revenue.amount == 0


@pytest.mark.parametrize("field", ["actor", "account", "provider", "content_digest", "provenance"])
def test_evidence_conflicting_identity_and_binding_rejected(cli: CLI, field: str) -> None:
    from dataclasses import replace

    from agentmine.application.contracts.ai import ReferencedText
    from agentmine.application.contracts.submission_context import (
        EvidenceState,
        EvidenceTrust,
        EvidenceType,
        ImportEvidence,
    )
    from agentmine.application.errors import PortError
    from agentmine.application.use_cases.context import content_reference

    envelope = services(cli).prepare.execute(completed(cli))
    capture = ReferencedText(content_reference("provisional note"), "provisional note")
    request = ImportEvidence(
        Reference("evidence"),
        envelope.reference,
        None,
        EvidenceType.PAYMENT_REPORT,
        EvidenceTrust.UNVERIFIED_SOURCE,
        EvidenceState.UNVERIFIED,
        Reference("reported-source"),
        None,
        None,
        cli.world.clock.now(),
        Reference("operator:provenance"),
        capture,
    )
    evidence = services(cli).record.import_report(request)
    replacement = (
        Reference("sha256:" + "0" * 64) if field == "content_digest" else Reference("wrong")
    )
    changed = {
        "actor": replace(evidence, actor=replacement),
        "account": replace(evidence, account=replacement),
        "provider": replace(evidence, provider=replacement),
        "content_digest": replace(evidence, content_digest=Reference("sha256:" + "0" * 64)),
        "provenance": replace(evidence, provenance=replacement),
    }[field]
    with pytest.raises(PortError):
        services(cli).record.execute(changed, capture)
    assert services(cli).evidence.execute(evidence.reference) == evidence


@pytest.mark.parametrize("kind", ["submission_capture", "submission_evidence"])
def test_evidence_transaction_rollback_and_lost_ack(cli: CLI, kind: str) -> None:
    import sqlite3
    from unittest.mock import patch

    from agentmine.application.contracts.ai import ReferencedText
    from agentmine.application.contracts.submission_context import (
        EvidenceState,
        EvidenceTrust,
        EvidenceType,
        ImportEvidence,
    )
    from agentmine.application.errors import PortError, PortErrorCode
    from agentmine.application.use_cases.context import content_reference
    from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase
    from agentmine.infrastructure.sqlite.submission_context import SQLiteSubmissionContextRepository

    envelope = services(cli).prepare.execute(completed(cli))
    report = ImportEvidence(
        Reference("capture-1"),
        envelope.reference,
        None,
        EvidenceType.RECEIPT_REPORT,
        EvidenceTrust.OPERATOR_REPORTED,
        EvidenceState.UNKNOWN,
        None,
        None,
        None,
        cli.world.clock.now(),
        Reference("operator:capture"),
        ReferencedText(content_reference("note"), "note"),
    )
    original = SQLiteDatabase.write

    def fault(
        database: SQLiteDatabase,
        connection: sqlite3.Connection,
        written_kind: str,
        key: str,
        value: object,
        revision: int,
        indexes: IndexValues,
    ) -> None:
        original(database, connection, written_kind, key, value, revision, indexes)
        if written_kind == kind:
            raise sqlite3.OperationalError("injected")

    with cli.world.database.transaction() as connection:
        before = tuple(connection.iterdump())
    with patch.object(SQLiteDatabase, "write", fault), pytest.raises(PortError):
        services(cli).record.import_report(report)
    with cli.world.database.transaction() as connection:
        assert tuple(connection.iterdump()) == before
    record = SQLiteSubmissionContextRepository.record_evidence

    def unknown(
        repository: SQLiteSubmissionContextRepository,
        evidence: SubmissionEvidence,
        capture: ReferencedText,
    ) -> None:
        record(repository, evidence, capture)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "evidence", "lost acknowledgement")

    with (
        patch.object(SQLiteSubmissionContextRepository, "record_evidence", unknown),
        pytest.raises(PortError),
    ):
        services(cli).record.import_report(report)
    retained = services(cli).evidence.execute(report.reference)
    assert services(cli).record.import_report(report) == retained


@pytest.mark.parametrize("corruption", ["source", "qa", "content"])
def test_authoritative_source_qa_content_mismatch_blocks_preparation(
    cli: CLI, corruption: str
) -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.qa import SQLiteQAJournal

    req = completed(cli)
    if corruption == "content":
        with cli.world.database.transaction(write=True) as connection:
            connection.execute("DELETE FROM snapshots WHERE kind='content'")
        with pytest.raises(PortError):
            services(cli).prepare.execute(req)
    elif corruption == "qa":
        report = SQLiteQAJournal(cli.world.database).get_report(Reference("qa-001"))
        assert report is not None
        with (
            patch.object(
                SQLiteQAJournal,
                "get_report",
                return_value=replace(report, reference=Reference("wrong")),
            ),
            pytest.raises(PortError),
        ):
            services(cli).prepare.execute(req)
    else:
        observation = SQLiteOpportunityRepository(cli.world.database).get_observation(
            Reference("op")
        )
        assert observation is not None
        with (
            patch.object(
                SQLiteOpportunityRepository,
                "get_observation",
                return_value=replace(observation, source_reference=Reference("wrong")),
            ),
            pytest.raises(PortError),
        ):
            services(cli).prepare.execute(req)


def manifest(cli: CLI) -> Path:
    import json

    req = current_request(cli)
    value = {
        "mode": "MANUAL",
        "account": {
            "id": "account-1",
            "provider": "provider-1",
            "effective_account": "explicit-user",
        },
        "channel": {
            "id": "channel-1",
            "provider": "provider-1",
            "listing": req.channel.listing.value,
            "kind": "manual_form",
            "destination": "https://example.test/submit",
            "permission_note": "operator:permission-note",
            "disclosed_data": ["name", "approved data"],
            "effects": "unknown",
            "account_effects": [],
        },
        "outbound": {
            "text": "Exact operator-approved message",
            "artifact_names": ["data.csv"],
            "published_artifacts": [],
        },
    }
    path = cli.root.parent / "submission-context.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "bad",
    [
        "unknown-field",
        "duplicate",
        "oversize",
        "constant",
        "local-url",
        "secret",
        "channel",
        "mode",
    ],
)
def test_cli_strict_bounded_context_inputs(cli: CLI, bad: str) -> None:
    import json

    completed(cli)
    path = manifest(cli)
    value = json.loads(path.read_text())
    if bad == "unknown-field":
        value["authorization"] = True
    elif bad == "local-url":
        value["channel"]["destination"] = "file:///C:/data.csv"
    elif bad == "secret":
        value["outbound"]["text"] = "Bearer should-never-be-retained"
    elif bad == "channel":
        value["channel"]["kind"] = "automatic_browser"
    elif bad == "mode":
        value["mode"] = "UNSUPPORTED"
    raw = json.dumps(value)
    if bad == "duplicate":
        raw = raw.replace('"mode":', '"mode":"MANUAL","mode":', 1)
    if bad == "oversize":
        raw = " " * 64001 + raw
    if bad == "constant":
        raw = raw.replace('"mode": "MANUAL"', '"mode": NaN')
    path.write_text(raw, encoding="utf-8")
    code, _ = cli.command(
        "submission",
        "prepare",
        "--context-id",
        "context-1",
        "--execution-id",
        "cli-exec",
        "--inputs",
        str(path),
    )
    assert code != 0


def test_offline_cli_review_show_decide_and_evidence_without_providers(cli: CLI) -> None:
    import io
    import json
    from unittest.mock import patch

    from agentmine.application.use_cases.settlement import SubmitTask, VerifyPayment
    from agentmine.application.workers.data import DataWorker
    from agentmine.presentation.operator_cli import run_cli

    completed(cli)
    path = manifest(cli)
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )

    def textual(*args: str) -> str:
        output = io.StringIO()
        assert (
            run_cli(
                ["--db", str(cli.world.database.path), "--ledger", "ledger", *args], ops, output
            )
            == 0
        )
        return output.getvalue()

    with (
        patch.object(SubmitTask, "execute", side_effect=AssertionError("no send")),
        patch.object(VerifyPayment, "execute", side_effect=AssertionError("no verifier")),
        patch.object(DataWorker, "execute", side_effect=AssertionError("no work")),
        patch.object(type(cli.world.source), "refresh", side_effect=AssertionError("offline only")),
    ):
        result = cli.command(
            "submission",
            "prepare",
            "--context-id",
            "context-1",
            "--execution-id",
            "cli-exec",
            "--inputs",
            str(path),
        )
        assert result[0] == 0 and result[1]["external_action_authorized"] is False
        scope = result[1]["scope_reference"]
        assert isinstance(scope, str)
        assert "SUBMISSION ENVELOPE" in textual(
            "review", "--opportunity", "op", "--review-id", "review-cli", "--destination", scope
        )
        assert "explicit-user" in textual("show-review", "--review-id", "review-cli")
        textual("decide", "--review-id", "review-cli", "--decision", "APPROVE")
        assert (
            cli.command("submission", "consent", "--review-id", "review-cli")[1]["applied"] is True
        )
        evidence = cli.root.parent / "note.json"
        evidence.write_text(
            json.dumps(
                {
                    "kind": "payment_report",
                    "trust": "operator_reported",
                    "state": "unverified",
                    "observed_at": cli.world.clock.now().isoformat(),
                    "provenance": "operator:note",
                    "text": "Payment reported, not verified",
                }
            ),
            encoding="utf-8",
        )
        assert (
            cli.command(
                "submission",
                "evidence-record",
                "--context-id",
                "context-1",
                "--evidence-id",
                "note",
                "--inputs",
                str(evidence),
            )[1]["verified_payment"]
            is False
        )
        assert cli.command("submission", "evidence-show", "--evidence-id", "note")[0] == 0
    assert cli.world.current().submission is None and cli.world.current().outcome is None
    assert cli.world.current().verified_revenue.amount == 0
    with pytest.raises(SystemExit):
        cli.command("submission", "handoff", "--context-id", "context-1")


@pytest.mark.parametrize("mode", [SubmissionMode.API, SubmissionMode.MANUAL])
def test_context_consent_cannot_enter_legacy_submission(cli: CLI, mode: SubmissionMode) -> None:
    from unittest.mock import Mock

    from agentmine.application.errors import PortError, PortErrorCode
    from agentmine.application.ports.services import SubmissionGateway
    from agentmine.application.use_cases.settlement import SubmitTask
    from agentmine.domain.approval import OperatorDecision
    from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
    from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository

    envelope = services(cli).prepare.execute(completed(cli))
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    ops.prepare.for_submission(
        Reference("review"), Reference("op"), Reference("ledger"), envelope.scope
    )
    ops.decide.execute(Reference("review"), OperatorDecision.APPROVE)
    gateway = Mock(spec=SubmissionGateway)
    repository = SQLiteSubmissionRepository(cli.world.database)
    use_case = SubmitTask(
        SQLiteOpportunityRepository(cli.world.database),
        SQLiteExecutionRepository(cli.world.database),
        repository,
        gateway,
        cli.world.source,
        cli.world.clock,
    )
    with pytest.raises(PortError) as error:
        use_case.execute(Reference("op"), Reference("forbidden-send"), mode)
    assert error.value.code == PortErrorCode.UNSUPPORTED
    assert gateway.mock_calls == []
    assert repository.get_request(Reference("forbidden-send")) is None


@pytest.mark.parametrize("identity", ["account", "channel"])
def test_account_channel_identity_cannot_be_redefined(cli: CLI, identity: str) -> None:
    from dataclasses import replace

    from agentmine.application.errors import PortError

    req = completed(cli)
    services(cli).prepare.execute(req)
    changed = replace(req, reference=Reference("different-context"))
    if identity == "account":
        changed = replace(changed, account=replace(req.account, effective_account="different-user"))
    else:
        changed = replace(
            changed, channel=replace(req.channel, destination="https://example.test/different")
        )
    with pytest.raises(PortError):
        services(cli).prepare.execute(changed)


def test_stale_opportunity_between_read_and_prepare_fails_atomically(cli: CLI) -> None:
    from unittest.mock import patch

    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.submission_context import SQLiteSubmissionContextRepository

    req = completed(cli)
    original = SQLiteSubmissionContextRepository.prepare

    def race(
        repository: SQLiteSubmissionContextRepository, envelope: SubmissionEnvelope
    ) -> SubmissionEnvelope:
        opportunities = SQLiteOpportunityRepository(cli.world.database)
        current = opportunities.get(Reference("op"))
        assert current is not None
        opportunities.save(OpportunitySave(current.value, current.revision))
        return original(repository, envelope)

    with patch.object(SQLiteSubmissionContextRepository, "prepare", race), pytest.raises(PortError):
        services(cli).prepare.execute(req)
    assert SQLiteSubmissionContextRepository(cli.world.database).get(req.reference) is None


@pytest.mark.parametrize("bad", ["verified", "independent", "future", "actor"])
def test_cli_evidence_cannot_import_verification_authority(cli: CLI, bad: str) -> None:
    import json
    from datetime import timedelta

    services(cli).prepare.execute(completed(cli))
    value = {
        "kind": "payment_report",
        "trust": "operator_reported",
        "state": "unverified",
        "observed_at": cli.world.clock.now().isoformat(),
        "provenance": "operator:note",
        "text": "Claim only",
    }
    if bad == "verified":
        value["state"] = "VERIFIED"
    if bad == "independent":
        value["trust"] = "independent_ledger"
    if bad == "future":
        value["observed_at"] = (cli.world.clock.now() + timedelta(days=1)).isoformat()
    if bad == "actor":
        value["actor"] = "somebody-else"
    path = cli.root.parent / "bad-evidence.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert (
        cli.command(
            "submission",
            "evidence-record",
            "--context-id",
            "context-1",
            "--evidence-id",
            "bad",
            "--inputs",
            str(path),
        )[0]
        != 0
    )
    assert cli.world.current().payment is None and cli.world.current().verified_revenue.amount == 0


def test_missing_capture_is_not_silently_read_as_complete_evidence(cli: CLI) -> None:
    from agentmine.application.contracts.ai import ReferencedText
    from agentmine.application.contracts.submission_context import (
        EvidenceState,
        EvidenceTrust,
        EvidenceType,
        ImportEvidence,
    )
    from agentmine.application.errors import PortError
    from agentmine.application.use_cases.context import content_reference

    envelope = services(cli).prepare.execute(completed(cli))
    report = ImportEvidence(
        Reference("broken"),
        envelope.reference,
        None,
        EvidenceType.ACCOUNT_NOTE,
        EvidenceTrust.TEST_FIXTURE,
        EvidenceState.UNKNOWN,
        None,
        None,
        None,
        cli.world.clock.now(),
        Reference("fixture:note"),
        ReferencedText(content_reference("note"), "note"),
    )
    services(cli).record.import_report(report)
    with cli.world.database.transaction(write=True) as connection:
        connection.execute("DELETE FROM snapshots WHERE kind='submission_capture'")
    with pytest.raises(PortError):
        services(cli).evidence.execute(report.reference)


def test_legacy_manual_receipt_cannot_upgrade_context_authority(cli: CLI) -> None:
    from agentmine.application.contracts.qa import bundle_content
    from agentmine.application.contracts.submission import SubmissionRequest
    from agentmine.application.errors import PortError, PortErrorCode
    from agentmine.application.use_cases.context import content_reference
    from agentmine.application.use_cases.manual_submission import RecordManualSubmission
    from agentmine.domain.approval import OperatorDecision
    from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository

    envelope = services(cli).prepare.execute(completed(cli))
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    ops.prepare.for_submission(
        Reference("review"), Reference("op"), Reference("ledger"), envelope.scope
    )
    ops.decide.execute(Reference("review"), OperatorDecision.APPROVE)
    op = cli.world.current()
    assert op.qa is not None and op.approval is not None
    repository = SQLiteSubmissionRepository(cli.world.database)
    # A trusted test-only internal writer supplies an old-style intent; it still cannot send.
    repository.claim_request(
        SubmissionRequest(
            Reference("legacy"),
            envelope.deliverable,
            op.qa,
            op.approval,
            envelope.scope,
            bundle_content(envelope.retained.result),
            SubmissionMode.MANUAL,
        )
    )
    use_case = RecordManualSubmission(
        SQLiteOpportunityRepository(cli.world.database),
        repository,
        cli.world.clock,
        Reference("operator"),
    )
    with pytest.raises(PortError) as error:
        use_case.execute(
            Reference("op"),
            Reference("legacy"),
            cli.world.clock.now(),
            content_reference("unverified receipt"),
            None,
            "unverified receipt",
        )
    assert error.value.code == PortErrorCode.UNSUPPORTED and cli.world.current().submission is None


def test_concurrent_evidence_returns_original_server_capture_timestamp(cli: CLI) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from datetime import timedelta

    from agentmine.application.contracts.ai import ReferencedText
    from agentmine.application.contracts.submission_context import (
        EvidenceState,
        EvidenceTrust,
        EvidenceType,
    )
    from agentmine.application.use_cases.context import content_reference

    envelope = services(cli).prepare.execute(completed(cli))
    now = cli.world.clock.now()
    capture = ReferencedText(
        content_reference("same reported observation"), "same reported observation"
    )
    first = SubmissionEvidence(
        Reference("racing-capture"),
        envelope.reference,
        None,
        EvidenceType.RECEIPT_REPORT,
        EvidenceTrust.OPERATOR_REPORTED,
        EvidenceState.UNVERIFIED,
        Reference("operator"),
        None,
        envelope.account.provider,
        envelope.account.reference,
        None,
        None,
        now,
        now,
        capture.reference,
        Reference("operator:provenance"),
    )
    second = replace(first, captured_at=now + timedelta(seconds=1))
    cli.world.clock.instant = second.captured_at
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda item: services(cli).record.execute(item, capture), [first, second])
        )
    retained = services(cli).evidence.execute(first.reference)
    assert results == [retained, retained]
    assert retained in (first, second)
