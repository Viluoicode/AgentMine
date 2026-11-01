"""Explicit offline intent and receipt commands; never instruct a real external action."""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.manual_handoff import (
    HandoffError,
    HandoffReason,
    ManualHandoffView,
    ReportManualReceipt,
)
from agentmine.application.use_cases.context import content_reference
from agentmine.application.use_cases.manual_handoff import (
    ConfirmManualHandoff,
    GetManualHandoff,
    InspectManualReadiness,
    PrepareManualHandoff,
    RecordManualHandoffReceipt,
)
from agentmine.domain.values import Reference
from agentmine.presentation.runtime_inputs import fields, read_json, text
from agentmine.presentation.runtime_views import encode


@dataclass(frozen=True, slots=True)
class ManualHandoffServices:
    readiness: InspectManualReadiness
    prepare: PrepareManualHandoff
    confirm: ConfirmManualHandoff
    get: GetManualHandoff
    record: RecordManualHandoffReceipt


def add_handoff_parsers(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = actions.add_parser(
        "handoff", help="OFFLINE ONLY: durable intent, never external authorization"
    )
    commands = command.add_subparsers(dest="handoff_action", required=True)
    for name in ("readiness", "prepare", "confirm", "show", "receipt-record", "receipt-show"):
        item = commands.add_parser(name)
        if name in ("readiness", "prepare"):
            item.add_argument("--context-id", required=True)
            item.add_argument("--review-id", required=True)
        if name != "readiness":
            item.add_argument("--handoff-id", required=True)
        if name == "prepare":
            item.add_argument("--submission-id", required=True)
        if name == "confirm":
            item.add_argument("--confirm", action="store_true")
        if name == "receipt-record":
            item.add_argument("--evidence-id", required=True)
            item.add_argument("--inputs", required=True)


def handoff_view(view: ManualHandoffView) -> dict[str, object]:
    draft = view.draft
    return {
        "handoff_id": draft.reference.value,
        "submission_id": draft.submission_reference.value,
        "status": view.status,
        "recovery_reason": view.reason.name,
        "context_id": draft.envelope.reference.value,
        "scope_reference": draft.envelope.scope.value,
        "deliverable": encode(draft.envelope.deliverable),
        "account": encode(draft.envelope.account),
        "channel": encode(draft.envelope.request.channel),
        "outbound": encode(draft.envelope.request.outbound),
        "representation_digest": draft.envelope.representation_digest.value,
        "actor": draft.envelope.run.specification.actor.value,
        "ledger": draft.envelope.run.specification.ledger_reference.value,
        "prepared_at": draft.prepared_at.isoformat(),
        "confirmed_at": None if view.claim is None else view.claim.confirmed_at.isoformat(),
        "receipt": None if view.receipt is None else encode(view.receipt.evidence),
        "receipt_recorded": view.applied,
        "opportunity_state": None
        if view.opportunity is None
        else view.opportunity.value.state.name,
        "offline_only": True,
        "external_action_authorized": False,
        "external_send_verified": False,
        "payment_verified": False,
        "instruction": (
            "OFFLINE ONLY. Do not send externally. Unknown effects stay locked; "
            "inspect original IDs, never resend."
        ),
    }


def run_handoff(args: argparse.Namespace, services: ManualHandoffServices, output: TextIO) -> int:
    try:
        action = args.handoff_action
        if action == "readiness":
            result = services.readiness.execute(
                Reference(args.context_id), Reference(args.review_id)
            )
            print(
                json.dumps(
                    {
                        "context_id": result.envelope.value,
                        "reason": result.reason.name,
                        "offline_fixture_ready": result.reason == HandoffReason.NONE,
                        "external_action_authorized": False,
                        "offline_only": True,
                    }
                ),
                file=output,
            )
            return 0 if result.reason == HandoffReason.NONE else 1
        reference = Reference(args.handoff_id)
        if action == "prepare":
            view = services.prepare.execute(
                reference,
                Reference(args.submission_id),
                Reference(args.context_id),
                Reference(args.review_id),
            )
        elif action == "confirm":
            view = services.confirm.execute(reference, confirm=args.confirm)
        elif action == "receipt-record":
            required = {"reported_at", "observed_at", "provenance", "text"}
            data = fields(
                read_json(Path(args.inputs)), required | {"external_id", "external_url"}, required
            )
            capture = text(data["text"])
            view = services.record.execute(
                ReportManualReceipt(
                    reference,
                    Reference(args.evidence_id),
                    datetime.fromisoformat(text(data["reported_at"])),
                    datetime.fromisoformat(text(data["observed_at"])),
                    Reference(text(data["provenance"])),
                    ReferencedText(content_reference(capture), capture),
                    None if data.get("external_id") is None else text(data["external_id"]),
                    None if data.get("external_url") is None else text(data["external_url"]),
                )
            )
        else:
            view = services.get.execute(reference)
        print(json.dumps(handoff_view(view), ensure_ascii=True), file=output)
        return 0
    except HandoffError as error:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": error.reason.name,
                    "external_action_authorized": False,
                }
            ),
            file=output,
        )
        return 1
    except (ValueError, OSError, OverflowError):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "manual_handoff_input",
                    "message": "Invalid bounded offline input",
                }
            ),
            file=output,
        )
        return 2
