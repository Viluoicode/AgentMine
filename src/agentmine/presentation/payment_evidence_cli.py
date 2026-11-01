"""Bounded offline payment report inspection; no verifier, settlement or financial action."""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.payment_evidence import (
    PaymentEvidenceStatus,
    PaymentEvidenceView,
    PaymentReportError,
    PaymentReportRequest,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.context import content_reference
from agentmine.application.use_cases.payment_evidence import (
    GetPaymentEvidence,
    RecordPaymentEvidence,
)
from agentmine.domain.values import Reference
from agentmine.presentation.runtime_inputs import fields, read_json, text
from agentmine.presentation.runtime_views import encode


@dataclass(frozen=True, slots=True)
class PaymentEvidenceServices:
    record: RecordPaymentEvidence
    get: GetPaymentEvidence


def add_payment_parsers(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = actions.add_parser(
        "payment", help="UNVERIFIED reports only; PAID authority unavailable"
    )
    commands = command.add_subparsers(dest="payment_action", required=True)
    for name in ("record", "show", "status"):
        item = commands.add_parser(name)
        item.add_argument("--evidence-id", required=True)
        if name == "record":
            item.add_argument("--handoff-id", required=True)
            item.add_argument("--inputs", required=True)


def payment_view(view: PaymentEvidenceView) -> dict[str, object]:
    result: dict[str, object] = {
        "evidence_id": view.reference.value,
        "status": view.status.name,
        "reported_payment": view.report is not None,
        "trust": "OPERATOR_REPORTED",
        "verification_status": "UNVERIFIED",
        "independently_verified_payment": False,
        "settlement_identity_status": "UNKNOWN",
        "actual_asset": "UNKNOWN",
        "actual_network": "UNKNOWN",
        "actual_recipient": "UNKNOWN",
        "actual_amount": "UNKNOWN",
        "payout_obligation": "UNKNOWN",
        "current_paid_authority": "UNAVAILABLE",
        "verified_revenue_created": False,
        "capture_retained": view.capture_retained,
        "observation_attached": view.observation is not None,
        "missing_or_conflicting_evidence": view.status
        in (PaymentEvidenceStatus.MISSING, PaymentEvidenceStatus.CONFLICT),
        "instruction": (
            "Reported hints are not verified settlement. "
            "No payment or external action is authorized."
        ),
    }
    report = view.report
    if report is not None:
        request = report.request
        op = report.source_snapshot.value
        result.update(
            {
                "handoff_id": request.handoff.value,
                "envelope_id": report.envelope.value,
                "scope": report.scope.value,
                "account": encode(report.account),
                "channel": report.channel.value,
                "listing": report.listing.value,
                "submission": encode(op.submission),
                "outcome": encode(op.outcome),
                "actor": report.actor.value,
                "ledger": report.ledger.value,
                "source_revision": report.source_snapshot.revision,
                "prepared_at": report.prepared_at.isoformat(),
                "contract_version": report.contract_version,
                "metadata": encode(view.metadata),
                "reported_hints": {
                    name: getattr(request, name)
                    for name in (
                        "transaction_hint",
                        "url_hint",
                        "asset_hint",
                        "network_hint",
                        "recipient_hint",
                        "amount_hint",
                    )
                },
                "reported_event_at": None
                if request.event_at is None
                else request.event_at.isoformat(),
                "observed_at": request.observed_at.isoformat(),
                "provenance": request.provenance.value,
                "capture_digest": request.capture.reference.value,
                "reported_capture": request.capture.text,
            }
        )
    return result


def run_payment(args: argparse.Namespace, services: PaymentEvidenceServices, output: TextIO) -> int:
    try:
        reference = Reference(args.evidence_id)
        if args.payment_action == "record":
            required = {"observed_at", "provenance", "text"}
            hints = {
                "transaction_hint",
                "url_hint",
                "asset_hint",
                "network_hint",
                "recipient_hint",
                "amount_hint",
            }
            data = fields(
                read_json(Path(args.inputs)),
                required | hints | {"outcome_id", "event_at"},
                required,
            )
            capture = text(data["text"])

            def optional(name: str) -> str | None:
                return None if data.get(name) is None else text(data[name])

            outcome = optional("outcome_id")
            event = optional("event_at")
            request = PaymentReportRequest(
                reference,
                Reference(args.handoff_id),
                None if outcome is None else Reference(outcome),
                None if event is None else datetime.fromisoformat(event),
                datetime.fromisoformat(text(data["observed_at"])),
                Reference(text(data["provenance"])),
                ReferencedText(content_reference(capture), capture),
                optional("transaction_hint"),
                optional("url_hint"),
                optional("asset_hint"),
                optional("network_hint"),
                optional("recipient_hint"),
                optional("amount_hint"),
            )
            view = services.record.execute(request)
        else:
            view = services.get.execute(reference)
        print(json.dumps(payment_view(view)), file=output)
        return (
            1
            if view.status in (PaymentEvidenceStatus.MISSING, PaymentEvidenceStatus.CONFLICT)
            else 0
        )
    except PaymentReportError as error:
        print(json.dumps(payment_error(error.status, error.code.value)), file=output)
        return 1
    except PortError as error:
        status = (
            PaymentEvidenceStatus.UNKNOWN
            if error.code in (PortErrorCode.UNAVAILABLE, PortErrorCode.OUTCOME_UNKNOWN)
            else PaymentEvidenceStatus.CONFLICT
        )
        print(json.dumps(payment_error(status, error.code.value)), file=output)
        return 1
    except (ValueError, OSError, OverflowError):
        print(
            json.dumps(payment_error(PaymentEvidenceStatus.CONFLICT, "payment_report_input")),
            file=output,
        )
        return 2


def payment_error(status: PaymentEvidenceStatus, code: str) -> dict[str, object]:
    return {
        "status": status.name,
        "code": code,
        "reported_payment": "UNKNOWN",
        "trust": "OPERATOR_REPORTED",
        "verification_status": "UNVERIFIED",
        "independently_verified_payment": False,
        "settlement_identity_status": "UNKNOWN",
        "actual_asset": "UNKNOWN",
        "actual_network": "UNKNOWN",
        "actual_recipient": "UNKNOWN",
        "actual_amount": "UNKNOWN",
        "payout_obligation": "UNKNOWN",
        "current_paid_authority": "UNAVAILABLE",
        "verified_revenue_created": False,
        "missing_or_conflicting_evidence": True,
        "message": "Inspect the original evidence ID; no payment authority is available.",
    }
