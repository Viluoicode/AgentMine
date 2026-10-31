"""Bounded offline context/evidence commands; no handoff or external capability."""

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.submission import SubmissionMode
from agentmine.application.contracts.submission_context import (
    AccountIdentity,
    ChannelKind,
    EffectKnowledge,
    EvidenceState,
    EvidenceTrust,
    EvidenceType,
    ImportEvidence,
    OutboundMaterial,
    PrepareEnvelope,
    PublishedArtifact,
    SubmissionChannel,
    SubmissionEnvelope,
    digest,
)
from agentmine.application.use_cases.context import content_reference
from agentmine.application.use_cases.submission_context import (
    GetSubmissionConsent,
    GetSubmissionEnvelope,
    GetSubmissionEvidence,
    PrepareSubmissionEnvelope,
    RecordSubmissionEvidence,
)
from agentmine.domain.values import Reference
from agentmine.presentation.runtime_inputs import fields, items, read_json, text
from agentmine.presentation.runtime_views import encode


@dataclass(frozen=True, slots=True)
class SubmissionContextServices:
    prepare: PrepareSubmissionEnvelope
    get: GetSubmissionEnvelope
    record: RecordSubmissionEvidence
    evidence: GetSubmissionEvidence
    consent: GetSubmissionConsent


def add_submission_context_parsers(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    command = commands.add_parser("submission", help="Offline context/evidence only; no send")
    actions = command.add_subparsers(dest="submission_action", required=True)
    for name in ("prepare", "show", "evidence-record", "evidence-show", "consent"):
        action = actions.add_parser(name)
        if name in ("prepare", "show", "evidence-record"):
            action.add_argument("--context-id", required=True)
        if name == "prepare":
            action.add_argument("--execution-id", required=True)
        if name in ("prepare", "evidence-record"):
            action.add_argument("--inputs", required=True)
        if name in ("evidence-record", "evidence-show"):
            action.add_argument("--evidence-id", required=True)
        if name == "consent":
            action.add_argument("--review-id", required=True)


def read_envelope(path: Path, reference: Reference, execution: Reference) -> PrepareEnvelope:
    data = fields(
        read_json(path),
        {"mode", "account", "channel", "outbound"},
        {"mode", "account", "channel", "outbound"},
    )
    account = fields(
        data["account"],
        {"id", "provider", "effective_account"},
        {"id", "provider", "effective_account"},
    )
    channel_fields = {
        "id",
        "provider",
        "listing",
        "kind",
        "destination",
        "permission_note",
        "disclosed_data",
        "effects",
        "account_effects",
    }
    channel = fields(data["channel"], channel_fields, channel_fields)
    outbound = fields(
        data["outbound"],
        {"text", "artifact_names", "published_artifacts"},
        {"text", "artifact_names", "published_artifacts"},
    )
    published = []
    for value in items(outbound["published_artifacts"], 10):
        item = fields(value, {"name", "location", "sha256"}, {"name", "location", "sha256"})
        published.append(
            PublishedArtifact(
                text(item["name"]), text(item["location"]), Reference(text(item["sha256"]))
            )
        )
    return PrepareEnvelope(
        reference,
        execution,
        SubmissionMode(text(data["mode"])),
        AccountIdentity(
            Reference(text(account["id"])),
            Reference(text(account["provider"])),
            text(account["effective_account"]),
        ),
        SubmissionChannel(
            Reference(text(channel["id"])),
            Reference(text(channel["provider"])),
            Reference(text(channel["listing"])),
            ChannelKind(text(channel["kind"])),
            text(channel["destination"]),
            Reference(text(channel["permission_note"])),
            tuple(text(x) for x in items(channel["disclosed_data"], 50)),
            EffectKnowledge(text(channel["effects"])),
            tuple(text(x) for x in items(channel["account_effects"], 20)),
        ),
        OutboundMaterial(
            text(outbound["text"]),
            tuple(text(x) for x in items(outbound["artifact_names"], 10)),
            tuple(published),
        ),
    )


def envelope_view(envelope: SubmissionEnvelope) -> dict[str, object]:
    spec = envelope.run.specification
    return {
        "context_id": envelope.reference.value,
        "scope_reference": envelope.scope.value,
        "scope_digest": digest(envelope).value,
        "representation_digest": envelope.representation_digest.value,
        "deliverable": encode(envelope.deliverable),
        "task": encode(spec.task),
        "mode": envelope.mode.value,
        "account": encode(envelope.account),
        "channel": encode(envelope.request.channel),
        "outbound": encode(envelope.request.outbound),
        "artifacts": [
            {"name": a.name, "sha256": a.digest, "media_type": a.media_type}
            for a in envelope.retained.result.artifacts
        ],
        "qa": encode(envelope.report),
        "source_context": encode(spec.source_context),
        "eligibility_evidence": encode(spec.execution_evidence),
        "actor": spec.actor.value,
        "ledger": spec.ledger_reference.value,
        "prepared_at": envelope.prepared_at.isoformat(),
        "contract_version": envelope.contract_version,
        "dispatch_capability": "UNAVAILABLE_B1",
        "external_action_authorized": False,
        "account_permission": "UNVERIFIED",
        "public_artifacts_verified": False,
        "source_freshness": "RETAINED_ONLY_REVALIDATION_REQUIRED_BEFORE_HANDOFF",
    }


def run_submission_context(
    args: argparse.Namespace, services: SubmissionContextServices, output: TextIO
) -> int:
    try:
        action = args.submission_action
        if action in ("prepare", "show"):
            value = (
                services.prepare.execute(
                    read_envelope(
                        Path(args.inputs), Reference(args.context_id), Reference(args.execution_id)
                    )
                )
                if action == "prepare"
                else services.get.execute(Reference(args.context_id))
            )
            result = envelope_view(value)
        elif action == "consent":
            consent = services.consent.execute(Reference(args.review_id))
            result = {
                "applied": consent.applied,
                "explanation": consent.explanation,
                "envelope": envelope_view(consent.envelope),
                "external_action_authorized": False,
            }
        else:
            if action == "evidence-record":
                required = {"kind", "trust", "state", "observed_at", "provenance", "text"}
                data = fields(
                    read_json(Path(args.inputs)),
                    required | {"submission", "observing_source", "event", "event_at"},
                    required,
                )

                def optional_ref(key: str) -> Reference | None:
                    return None if data.get(key) is None else Reference(text(data[key]))

                capture = text(data["text"])
                evidence = services.record.import_report(
                    ImportEvidence(
                        Reference(args.evidence_id),
                        Reference(args.context_id),
                        optional_ref("submission"),
                        EvidenceType(text(data["kind"])),
                        EvidenceTrust(text(data["trust"])),
                        EvidenceState(text(data["state"])),
                        optional_ref("observing_source"),
                        optional_ref("event"),
                        None
                        if data.get("event_at") is None
                        else datetime.fromisoformat(text(data["event_at"])),
                        datetime.fromisoformat(text(data["observed_at"])),
                        Reference(text(data["provenance"])),
                        ReferencedText(content_reference(capture), capture),
                    )
                )
            else:
                evidence = services.evidence.execute(Reference(args.evidence_id))
            result = {
                "evidence": encode(evidence),
                "authoritative_outcome": False,
                "verified_payment": False,
            }
        print(json.dumps(result, ensure_ascii=True), file=output)
        return 0
    except (ValueError, OSError, OverflowError):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": "submission_context_input",
                    "message": "Invalid bounded local context input",
                }
            ),
            file=output,
        )
        return 2
