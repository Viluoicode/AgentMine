"""Offline outcome reporting/inspection. No CLI authority or payment declaration."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import TextIO

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.outcome_evidence import (
    OutcomeEvent,
    OutcomeEventType,
    OutcomeEvidenceError,
    ReportOutcomeEvent,
)
from agentmine.application.use_cases.context import content_reference
from agentmine.application.use_cases.outcome_evidence import OutcomeEvidenceWorkflow
from agentmine.domain.values import Reference
from agentmine.presentation.runtime_inputs import fields, read_json, text
from agentmine.presentation.runtime_views import encode


def add_outcome_parsers(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = actions.add_parser(
        "outcome", help="Provisional reports; independent authority disabled"
    )
    commands = command.add_subparsers(dest="outcome_action", required=True)
    for name in ("record", "show", "verify", "status"):
        item = commands.add_parser(name)
        if name in ("record", "show", "verify"):
            item.add_argument("--evidence-id", required=True)
        if name == "record":
            item.add_argument("--handoff-id", required=True)
            item.add_argument("--inputs", required=True)
        if name in ("verify", "status"):
            item.add_argument("--verification-id", required=True)


def event_view(event: OutcomeEvent) -> dict[str, object]:
    draft = event.receipt.claim.draft
    return {
        "evidence_id": event.reference.value,
        "handoff_id": draft.reference.value,
        "submission_id": draft.submission_reference.value,
        "envelope_id": draft.envelope.reference.value,
        "account": encode(draft.envelope.account),
        "listing": draft.envelope.request.channel.listing.value,
        "channel": draft.envelope.request.channel.reference.value,
        "deliverable": encode(event.receipt.submission.deliverable),
        "event_type": event.event_type.name,
        "metadata": encode(event.metadata),
        "parser_version": event.parser_version,
        "trust": "OPERATOR_REPORTED",
        "verification_status": "UNVERIFIED",
        "payment_verified": False,
    }


def run_outcome(args: argparse.Namespace, workflow: OutcomeEvidenceWorkflow, output: TextIO) -> int:
    try:
        if args.outcome_action == "record":
            required = {
                "provider_event",
                "event_type",
                "event_at",
                "observed_at",
                "provenance",
                "text",
            }
            data = fields(read_json(Path(args.inputs)), required, required)
            capture = text(data["text"])
            event = workflow.record(
                ReportOutcomeEvent(
                    Reference(args.handoff_id),
                    Reference(args.evidence_id),
                    Reference(text(data["provider_event"])),
                    OutcomeEventType(text(data["event_type"])),
                    datetime.fromisoformat(text(data["event_at"])),
                    datetime.fromisoformat(text(data["observed_at"])),
                    Reference(text(data["provenance"])),
                    ReferencedText(content_reference(capture), capture),
                )
            )
            result = event_view(event)
        elif args.outcome_action == "show":
            result = event_view(workflow.get(Reference(args.evidence_id)))
        else:
            view = (
                workflow.verify(Reference(args.verification_id), Reference(args.evidence_id))
                if args.outcome_action == "verify"
                else workflow.status(Reference(args.verification_id))
            )
            result = event_view(view.request.event)
            result.update(
                {
                    "verification_id": view.request.reference.value,
                    "diagnostic": view.diagnostic,
                    "decision": None
                    if view.decision is None
                    else {
                        "status": view.decision.status.name,
                        "authority": encode(view.decision.authority),
                        "rationale": view.decision.rationale,
                        "verified_at": view.decision.verified_at.isoformat(),
                        "contract_version": view.decision.contract_version,
                    },
                    "outcome_applied": view.applied,
                    "current_state": None
                    if view.current is None
                    else view.current.value.state.name,
                }
            )
            print(json.dumps(result), file=output)
            return (
                0
                if view.applied
                or (
                    view.decision is not None
                    and view.decision.status.name == "VERIFIED"
                    and view.diagnostic != "CONFLICT"
                )
                else 1
            )
        print(json.dumps(result), file=output)
        return 0
    except OutcomeEvidenceError as error:
        print(json.dumps({"status": error.diagnostic.name, "payment_verified": False}), file=output)
        return 1
    except (ValueError, OSError, OverflowError):
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "code": "outcome_input",
                    "message": "Invalid bounded outcome input",
                }
            ),
            file=output,
        )
        return 2
