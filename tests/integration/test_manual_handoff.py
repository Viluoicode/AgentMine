"""Offline-only handoff tests: real CLI/SQLite/approval; explicit permission/source fixtures."""

import io
import json
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from test_runtime_operator_cli import CLI, cli
from test_submission_context import completed, services

from agentmine.application.contracts.manual_handoff import (
    ChannelPermission,
    ManualHandoffClaim,
    ManualHandoffView,
    ManualReceipt,
    PermissionStatus,
    ReportManualReceipt,
)
from agentmine.application.contracts.submission_context import EffectKnowledge, SubmissionEnvelope
from agentmine.bootstrap.operator import compose_operator
from agentmine.domain.approval import OperatorDecision
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase
from agentmine.presentation.manual_handoff_cli import ManualHandoffServices
from agentmine.presentation.operator_cli import run_cli

__all__ = ["cli"]


@dataclass
class OfflinePermissionFixture:
    cli: CLI
    status: PermissionStatus = PermissionStatus.OFFLINE_TEST_ONLY

    def inspect(self, envelope: SubmissionEnvelope) -> ChannelPermission:
        return ChannelPermission(
            envelope.scope, self.cli.world.clock.now(), self.status, Reference("fixture:permission")
        )


def approved(cli: CLI) -> SubmissionEnvelope:
    request = completed(cli)
    request = replace(
        request, channel=replace(request.channel, effects=EffectKnowledge.NONE_DECLARED)
    )
    envelope = services(cli).prepare.execute(request)
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
    )
    ops.prepare.for_submission(
        Reference("manual-review"), Reference("op"), Reference("ledger"), envelope.scope
    )
    ops.decide.execute(Reference("manual-review"), OperatorDecision.APPROVE)
    return envelope


def command(
    cli: CLI, *args: str, permission: OfflinePermissionFixture | None = None
) -> tuple[int, dict[str, object]]:
    ops = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
        manual_permission=permission,
    )
    output = io.StringIO()
    code = run_cli(
        [
            "--db",
            str(cli.world.database.path),
            "--ledger",
            "ledger",
            "submission",
            "handoff",
            *args,
        ],
        ops,
        output,
    )
    return code, json.loads(output.getvalue())


def test_offline_handoff_requires_explicit_permission_and_confirm(cli: CLI) -> None:
    envelope = approved(cli)
    args = (
        "prepare",
        "--handoff-id",
        "handoff-1",
        "--submission-id",
        "submission-1",
        "--context-id",
        envelope.reference.value,
        "--review-id",
        "manual-review",
    )
    assert command(cli, *args)[0] != 0
    fixture = OfflinePermissionFixture(cli)
    assert command(cli, *args, permission=fixture)[0] == 0
    assert cli.world.current().state.name == "APPROVED_FOR_SUBMISSION"
    assert command(cli, "confirm", "--handoff-id", "handoff-1", permission=fixture)[0] != 0
    code, result = command(
        cli, "confirm", "--handoff-id", "handoff-1", "--confirm", permission=fixture
    )
    assert code == 0 and result["status"] == "IN_FLIGHT_UNKNOWN"
    assert result["external_action_authorized"] is False
    assert cli.world.current().state.name == "SUBMISSION_IN_FLIGHT"
    assert (
        cli.world.current().submission is None and cli.world.current().verified_revenue.amount == 0
    )


def handoff_services(cli: CLI) -> ManualHandoffServices:
    result = compose_operator(
        cli.world.database.path,
        Reference("ledger"),
        Reference("operator"),
        cli.world.clock,
        cli.world.source,
        manual_permission=OfflinePermissionFixture(cli),
    ).submission_context
    assert result is not None and result.handoff is not None
    return result.handoff


def prepare(cli: CLI) -> tuple[ManualHandoffServices, ManualHandoffView]:
    envelope = approved(cli)
    svc = handoff_services(cli)
    view = svc.prepare.execute(
        Reference("handoff-1"),
        Reference("submission-1"),
        envelope.reference,
        Reference("manual-review"),
    )
    return svc, view


def receipt_command(cli: CLI) -> ReportManualReceipt:
    from agentmine.application.contracts.ai import ReferencedText
    from agentmine.application.contracts.manual_handoff import ReportManualReceipt
    from agentmine.application.use_cases.context import content_reference

    capture = "Explicitly synthetic offline receipt; no marketplace send"
    return ReportManualReceipt(
        Reference("handoff-1"),
        Reference("receipt-1"),
        cli.world.clock.now(),
        cli.world.clock.now(),
        Reference("fixture:operator-note"),
        ReferencedText(content_reference(capture), capture),
        "offline-receipt",
    )


def test_receipt_reopen_idempotency_conflicts_and_zero_revenue(cli: CLI) -> None:
    from agentmine.application.errors import PortError

    svc, _ = prepare(cli)
    claim = svc.confirm.execute(Reference("handoff-1"), confirm=True)
    command_value = receipt_command(cli)
    completed_view = svc.record.execute(command_value)
    assert completed_view.applied and completed_view.receipt is not None
    assert completed_view.receipt.evidence.trust.name == "OPERATOR_REPORTED"
    assert completed_view.receipt.evidence.state.name == "UNVERIFIED"
    assert cli.world.current().state.name == "SUBMITTED"
    assert cli.world.current().verified_revenue.amount == 0
    assert handoff_services(cli).record.execute(command_value) == completed_view
    assert (
        handoff_services(cli).confirm.execute(Reference("handoff-1"), confirm=True)
        == completed_view
    )
    with pytest.raises(PortError):
        svc.record.execute(replace(command_value, evidence_reference=Reference("receipt-other")))
    assert svc.get.execute(Reference("handoff-1")) == completed_view
    assert claim.claim == completed_view.claim


@pytest.mark.parametrize("change", ["closed", "unknown", "expired", "terms", "requirements"])
def test_source_changes_block_prepare(cli: CLI, change: str) -> None:
    from datetime import timedelta

    from agentmine.application.errors import PortError

    envelope = approved(cli)
    source = cli.world.source
    if change == "closed":
        source.is_open = False
    if change == "unknown":
        source.is_open = None
    if change == "expired":
        cli.world.clock.instant += timedelta(days=3)
    if change == "terms":
        source.terms_reference = Reference("changed-terms")
    if change == "requirements":
        source.requirements = "Changed instructions"
    with pytest.raises(PortError):
        handoff_services(cli).prepare.execute(
            Reference("handoff-1"),
            Reference("submission-1"),
            envelope.reference,
            Reference("manual-review"),
        )
    assert cli.world.current().state.name == "APPROVED_FOR_SUBMISSION"


def test_cancellation_before_confirm_and_claim_blocks_cancellation(cli: CLI) -> None:
    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    svc, _ = prepare(cli)
    repo = SQLiteOpportunityRepository(cli.world.database)
    old = repo.get(Reference("op"))
    assert old is not None
    repo.save(OpportunitySave(old.value.skip("operator cancelled"), old.revision))
    with pytest.raises(PortError):
        svc.confirm.execute(Reference("handoff-1"), confirm=True)
    assert svc.get.execute(Reference("handoff-1")).claim is None


def test_confirmed_claim_never_releases_or_renews(cli: CLI) -> None:
    from datetime import timedelta

    from agentmine.domain.errors import DomainError

    svc, _ = prepare(cli)
    original = svc.confirm.execute(Reference("handoff-1"), confirm=True)
    with pytest.raises(DomainError):
        cli.world.current().skip("too late")
    cli.world.clock.instant += timedelta(days=30)
    cli.world.source.is_open = False
    assert handoff_services(cli).confirm.execute(Reference("handoff-1"), confirm=True) == original
    completed_view = handoff_services(cli).record.execute(receipt_command(cli))
    assert completed_view.applied and cli.world.current().verified_revenue.amount == 0


@pytest.mark.parametrize("stage", ["claim", "receipt"])
@pytest.mark.parametrize("write_number", [1, 2, 3, 4])
def test_transaction_write_crashes_roll_back_and_recover(
    cli: CLI, stage: str, write_number: int
) -> None:
    from unittest.mock import patch

    svc, _ = prepare(cli)
    if stage == "receipt":
        svc.confirm.execute(Reference("handoff-1"), confirm=True)
    original = SQLiteDatabase.write
    count = 0

    def failing(
        self: SQLiteDatabase,
        connection: sqlite3.Connection,
        kind: str,
        key: str,
        value: object,
        revision: int,
        indexes: IndexValues,
    ) -> None:
        nonlocal count
        original(self, connection, kind, key, value, revision, indexes)
        if (
            stage == "claim"
            and kind
            in (
                "submission_request",
                "submission_delivery",
                "manual_handoff_external_owner",
                "manual_handoff_claim",
                "opportunity",
            )
        ) or (
            stage == "receipt"
            and kind
            in ("submission_attempt", "submission", "opportunity", "manual_handoff_applied")
        ):
            count += 1
            if count == write_number:
                raise RuntimeError("injected write crash")

    with patch.object(SQLiteDatabase, "write", failing), pytest.raises(RuntimeError):
        if stage == "claim":
            svc.confirm.execute(Reference("handoff-1"), confirm=True)
        else:
            svc.record.execute(receipt_command(cli))
    view = handoff_services(cli).get.execute(Reference("handoff-1"))
    if stage == "claim":
        assert view.claim is None and cli.world.current().state.name == "APPROVED_FOR_SUBMISSION"
        assert (
            handoff_services(cli).confirm.execute(Reference("handoff-1"), confirm=True).claim
            is not None
        )
    else:
        assert view.receipt is not None and not view.applied
        assert cli.world.current().state.name == "SUBMISSION_IN_FLIGHT"
        assert handoff_services(cli).record.execute(receipt_command(cli)).applied


def test_concurrent_claims_and_receipts_have_one_owner(cli: CLI) -> None:
    from concurrent.futures import ThreadPoolExecutor

    svc, _ = prepare(cli)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: svc.confirm.execute(Reference("handoff-1"), confirm=True), range(2))
        )
    assert results[0].claim == results[1].claim
    cmd = receipt_command(cli)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: svc.record.execute(cmd), range(2)))
    assert all(result.applied for result in results)
    assert results[0].receipt == results[1].receipt


def test_lost_ack_after_claim_and_after_completion(cli: CLI) -> None:
    from unittest.mock import patch

    from agentmine.infrastructure.sqlite.manual_handoff import SQLiteManualHandoffRepository

    svc, _ = prepare(cli)
    original_claim = SQLiteManualHandoffRepository.claim

    def lost_claim(
        self: SQLiteManualHandoffRepository, claim: ManualHandoffClaim
    ) -> ManualHandoffClaim:
        original_claim(self, claim)
        raise RuntimeError("lost acknowledgement")

    with (
        patch.object(SQLiteManualHandoffRepository, "claim", lost_claim),
        pytest.raises(RuntimeError),
    ):
        svc.confirm.execute(Reference("handoff-1"), confirm=True)
    assert (
        handoff_services(cli).confirm.execute(Reference("handoff-1"), confirm=True).claim
        is not None
    )
    original_finish = SQLiteManualHandoffRepository.complete_receipt

    def lost_finish(self: SQLiteManualHandoffRepository, receipt: ManualReceipt) -> None:
        original_finish(self, receipt)
        raise RuntimeError("lost completion acknowledgement")

    cmd = receipt_command(cli)
    with (
        patch.object(SQLiteManualHandoffRepository, "complete_receipt", lost_finish),
        pytest.raises(RuntimeError),
    ):
        svc.record.execute(cmd)
    assert handoff_services(cli).record.execute(cmd).applied
    assert cli.world.current().verified_revenue.amount == 0


def test_distinct_ids_cannot_evade_claim_or_adopt_legacy_intent(cli: CLI) -> None:
    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository

    svc, first = prepare(cli)
    second = svc.prepare.execute(
        Reference("handoff-2"),
        Reference("submission-2"),
        first.draft.envelope.reference,
        first.draft.review_reference,
    )
    svc.confirm.execute(first.draft.reference, confirm=True)
    with pytest.raises(PortError):
        svc.confirm.execute(second.draft.reference, confirm=True)
    assert svc.get.execute(second.draft.reference).claim is None
    assert (
        SQLiteSubmissionRepository(cli.world.database).get_request(Reference("submission-2"))
        is None
    )


def test_legacy_intent_is_not_adopted(cli: CLI) -> None:
    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository

    svc, view = prepare(cli)
    SQLiteSubmissionRepository(cli.world.database).claim_request(view.draft.request)
    with pytest.raises(PortError):
        svc.confirm.execute(view.draft.reference, confirm=True)
    assert svc.get.execute(view.draft.reference).claim is None


def test_stale_revision_retains_receipt_without_lifecycle_overwrite(cli: CLI) -> None:
    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    svc, _ = prepare(cli)
    svc.confirm.execute(Reference("handoff-1"), confirm=True)
    repo = SQLiteOpportunityRepository(cli.world.database)
    current = repo.get(Reference("op"))
    assert current is not None
    repo.save(OpportunitySave(current.value, current.revision))
    with pytest.raises(PortError):
        svc.record.execute(receipt_command(cli))
    view = svc.get.execute(Reference("handoff-1"))
    assert view.receipt is not None and not view.applied and view.status == "BLOCKED"
    assert cli.world.current().state.name == "SUBMISSION_IN_FLIGHT"


def test_receipt_cli_strict_input_and_readback(cli: CLI, tmp_path: Path) -> None:
    svc, _ = prepare(cli)
    svc.confirm.execute(Reference("handoff-1"), confirm=True)
    path = tmp_path / "receipt.json"
    path.write_text(
        json.dumps(
            {
                "reported_at": cli.world.clock.now().isoformat(),
                "observed_at": cli.world.clock.now().isoformat(),
                "provenance": "fixture:operator-note",
                "text": "Synthetic offline receipt",
            }
        )
    )
    assert (
        command(
            cli,
            "receipt-record",
            "--handoff-id",
            "handoff-1",
            "--evidence-id",
            "receipt-cli",
            "--inputs",
            str(path),
        )[0]
        == 0
    )
    code, result = command(cli, "receipt-show", "--handoff-id", "handoff-1")
    assert code == 0 and result["receipt_recorded"] is True
    assert result["external_send_verified"] is False and result["payment_verified"] is False


@pytest.mark.parametrize("change", ["actor", "ledger", "account", "channel", "mode", "effects"])
def test_exact_owner_context_and_effects_fail_closed(cli: CLI, change: str) -> None:
    from agentmine.application.contracts.submission import SubmissionMode
    from agentmine.application.errors import PortError
    from agentmine.application.use_cases.submission_context import GetSubmissionEnvelope
    from agentmine.infrastructure.sqlite.submission_context import SQLiteSubmissionContextRepository

    envelope = approved(cli)
    if change in ("actor", "ledger"):
        get = GetSubmissionEnvelope(
            SQLiteSubmissionContextRepository(cli.world.database),
            Reference("wrong" if change == "actor" else "operator"),
            Reference("wrong" if change == "ledger" else "ledger"),
        )
        with pytest.raises(PortError):
            get.execute(envelope.reference)
    else:
        svc = handoff_services(cli)
        view = svc.prepare.execute(
            Reference("handoff-1"),
            Reference("submission-1"),
            envelope.reference,
            Reference("manual-review"),
        )
        request = envelope.request
        with pytest.raises(PortError):
            if change == "effects":
                changed = replace(
                    request, channel=replace(request.channel, effects=EffectKnowledge.UNKNOWN)
                )
            elif change == "mode":
                changed = replace(request, mode=SubmissionMode.API)
            elif change == "channel":
                changed = replace(
                    request, channel=replace(request.channel, reference=Reference("wrong-channel"))
                )
            else:
                changed = replace(
                    request, account=replace(request.account, reference=Reference("wrong-account"))
                )
            replace(view.draft, envelope=replace(envelope, request=changed))


def test_source_unavailable_default_permission_and_no_dispatch(cli: CLI) -> None:
    from unittest.mock import patch

    from fakes import FakeSource

    from agentmine.application.errors import PortError, PortErrorCode

    envelope = approved(cli)
    with patch.object(
        FakeSource, "refresh", side_effect=AssertionError("must not refresh without channel")
    ):
        assert (
            command(
                cli,
                "readiness",
                "--context-id",
                envelope.reference.value,
                "--review-id",
                "manual-review",
            )[0]
            == 1
        )
    with patch.object(
        FakeSource,
        "refresh",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "refresh", "offline unavailable"),
    ):
        code, result = command(
            cli,
            "readiness",
            "--context-id",
            envelope.reference.value,
            "--review-id",
            "manual-review",
            permission=OfflinePermissionFixture(cli),
        )
    assert code == 1 and result["reason"] == "SOURCE_UNAVAILABLE"
    assert cli.world.current().submission is None


def test_cancellation_during_freshness_check_wins_atomically(cli: CLI) -> None:
    from unittest.mock import patch

    from fakes import FakeSource

    from agentmine.application.contracts.opportunities import (
        OpportunityStatus,
        RefreshOpportunityRequest,
    )
    from agentmine.application.contracts.records import OpportunitySave
    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository

    svc, view = prepare(cli)
    original = FakeSource.refresh

    def cancel(source: FakeSource, request: RefreshOpportunityRequest) -> OpportunityStatus:
        result = original(source, request)
        repository = SQLiteOpportunityRepository(cli.world.database)
        current = repository.get(Reference("op"))
        assert current is not None
        repository.save(
            OpportunitySave(current.value.skip("cancelled during source refresh"), current.revision)
        )
        return result

    with patch.object(FakeSource, "refresh", cancel), pytest.raises(PortError):
        svc.confirm.execute(view.draft.reference, confirm=True)
    assert svc.get.execute(view.draft.reference).claim is None
    assert cli.world.current().state.name == "SKIPPED"


def test_ledger_revision_change_blocks_claim_without_touching_costs(cli: CLI) -> None:
    from agentmine.application.errors import PortError
    from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository

    svc, view = prepare(cli)
    database = cli.world.database
    with database.transaction(write=True) as connection:
        connection.execute("UPDATE snapshots SET revision=revision+1 WHERE kind='budget'")
    ledger = SQLiteCostLedgerRepository(database).get(Reference("ledger"))
    with pytest.raises(PortError):
        svc.confirm.execute(view.draft.reference, confirm=True)
    assert SQLiteCostLedgerRepository(database).get(Reference("ledger")) == ledger
    assert svc.get.execute(view.draft.reference).claim is None


def test_backup_copy_readback_preserves_unknown_claim_and_provisional_evidence(
    cli: CLI, tmp_path: Path
) -> None:
    import sqlite3

    from agentmine.infrastructure.sqlite.database import SQLiteDatabase
    from agentmine.infrastructure.sqlite.manual_handoff import SQLiteManualHandoffRepository

    svc, view = prepare(cli)
    view = svc.confirm.execute(view.draft.reference, confirm=True)
    destination = tmp_path / "isolated-backup.sqlite3"
    with sqlite3.connect(cli.world.database.path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    restored = SQLiteManualHandoffRepository(SQLiteDatabase(destination)).inspect(
        view.draft.reference
    )
    assert restored == view and restored.status == "IN_FLIGHT_UNKNOWN"
    assert restored.claim == view.claim
    assert (
        restored.opportunity is not None and restored.opportunity.value.verified_revenue.amount == 0
    )
