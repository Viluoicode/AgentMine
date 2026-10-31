"""Immutable local submission scope and provisional evidence; never dispatch authority."""

import json
import re
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, StrEnum
from hashlib import sha256
from zoneinfo import ZoneInfo

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.contracts.qa import QAInspection, bundle_content, lifecycle_qa_result
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.runtime import WorkerResult, WorkerRun
from agentmine.application.contracts.submission import SubmissionMode
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.qa import QAOutcome, QAReport
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.domain.work import Deliverable


def require(condition: bool) -> None:
    if not condition:
        raise PortError(PortErrorCode.CONFLICT, "submission_context", "Context evidence mismatch")


def bounded(value: str, maximum: int = 500) -> None:
    require(
        isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= maximum
    )
    # Reject recognizable credentials; this is not a general secret-content classifier.
    require(not re.search(r"-----BEGIN .*PRIVATE KEY|\bsk_[A-Za-z0-9_-]+|Bearer\s+\S+", value))
    require(not any(ord(c) < 32 and c not in "\n\t\r" for c in value))


def identity(reference: Reference) -> None:
    require(isinstance(reference, Reference))
    bounded(reference.value, 300)


def https_location(value: str) -> None:
    bounded(value, 2000)
    # Conservative metadata grammar, not a network parser or permission grant.
    require(
        bool(
            re.fullmatch(
                r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::443)?"
                r"(?:/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?",
                value,
            )
        )
    )


def canonical(value: object) -> object:
    """Deterministic version-1 context representation, independent of storage codecs."""
    if isinstance(value, Enum):
        return {"enum": type(value).__qualname__, "value": value.value}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "type": type(value).__qualname__,
            "fields": [[f.name, canonical(getattr(value, f.name))] for f in fields(value)],
        }
    if isinstance(value, datetime):
        return {"instant": value.astimezone(UTC).isoformat()}
    if isinstance(value, timedelta):
        return {"duration": [value.days, value.seconds, value.microseconds]}
    if isinstance(value, ZoneInfo):
        return {"zone": value.key}
    if isinstance(value, timezone):
        return {"offset": canonical(value.utcoffset(None)), "name": value.tzname(None)}
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, tuple):
        return [canonical(item) for item in value]
    if isinstance(value, frozenset):
        return {
            "set": sorted(
                (canonical(item) for item in value),
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        }
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise PortError(
        PortErrorCode.INVALID_RESPONSE,
        "submission_context",
        "Unsupported scope value type: " + type(value).__name__,
    )


def digest(value: object) -> Reference:
    raw = json.dumps(canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return Reference("sha256:" + sha256(raw.encode("utf-8")).hexdigest())


class ChannelKind(StrEnum):
    MANUAL_FORM = "manual_form"
    MANUAL_MESSAGE = "manual_message"
    API_INTENDED = "api_intended"


class EffectKnowledge(StrEnum):
    UNKNOWN = "unknown"
    NONE_DECLARED = "none_declared"
    KNOWN = "known"


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    reference: Reference
    provider: Reference
    effective_account: str

    def __post_init__(self) -> None:
        identity(self.reference)
        identity(self.provider)
        bounded(self.effective_account)


@dataclass(frozen=True, slots=True)
class SubmissionChannel:
    reference: Reference
    provider: Reference
    listing: Reference
    kind: ChannelKind
    destination: str
    permission_note: Reference
    disclosed_data: tuple[str, ...]
    effects: EffectKnowledge
    account_effects: tuple[str, ...]

    def __post_init__(self) -> None:
        for item in (self.reference, self.provider, self.listing, self.permission_note):
            identity(item)
        require(isinstance(self.kind, ChannelKind) and isinstance(self.effects, EffectKnowledge))
        https_location(self.destination)
        require(isinstance(self.disclosed_data, tuple) and 1 <= len(self.disclosed_data) <= 50)
        require(isinstance(self.account_effects, tuple) and len(self.account_effects) <= 20)
        for text in (*self.disclosed_data, *self.account_effects):
            bounded(text, 1000)
        require((self.effects == EffectKnowledge.KNOWN) == bool(self.account_effects))


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
    name: str
    location: str
    content_digest: Reference

    def __post_init__(self) -> None:
        bounded(self.name)
        https_location(self.location)  # A local path cannot masquerade as a public artifact.
        require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_digest.value)))


@dataclass(frozen=True, slots=True)
class OutboundMaterial:
    text: str
    artifact_names: tuple[str, ...]
    published_artifacts: tuple[PublishedArtifact, ...]

    def __post_init__(self) -> None:
        bounded(self.text, 16000)
        require(isinstance(self.artifact_names, tuple) and len(self.artifact_names) <= 10)
        require(len(set(self.artifact_names)) == len(self.artifact_names))
        require(isinstance(self.published_artifacts, tuple) and len(self.published_artifacts) <= 10)
        for name in self.artifact_names:
            bounded(name)
        require(all(isinstance(item, PublishedArtifact) for item in self.published_artifacts))


@dataclass(frozen=True, slots=True)
class PrepareEnvelope:
    reference: Reference
    execution: Reference
    mode: SubmissionMode
    account: AccountIdentity
    channel: SubmissionChannel
    outbound: OutboundMaterial

    def __post_init__(self) -> None:
        identity(self.reference)
        identity(self.execution)
        require(
            isinstance(self.account, AccountIdentity)
            and isinstance(self.channel, SubmissionChannel)
        )
        require(isinstance(self.outbound, OutboundMaterial))
        require(
            isinstance(self.mode, SubmissionMode)
            and self.mode in (SubmissionMode.MANUAL, SubmissionMode.API)
        )
        require(
            (self.mode == SubmissionMode.API) == (self.channel.kind == ChannelKind.API_INTENDED)
        )
        require(self.account.provider == self.channel.provider)


@dataclass(frozen=True, slots=True)
class SubmissionEnvelope:
    request: PrepareEnvelope
    opportunity_snapshot: Versioned[Opportunity]
    run: WorkerRun
    retained: WorkerResult
    deliverable: Deliverable
    inspection: QAInspection
    report: QAReport
    observation: OpportunityObservation
    prepared_at: datetime
    contract_version: str = "submission-context-v1"

    def __post_init__(self) -> None:
        require_aware_timestamp(self.prepared_at)
        require(self.contract_version == "submission-context-v1")
        op = self.opportunity_snapshot.value
        spec = self.run.specification
        require(
            self.retained.run == self.run
            and op.state == OpportunityState.READY_FOR_HUMAN_REVIEW
            and op.task == spec.task
            and op.execution == self.run.plan.execution
            and op.deliverable == self.deliverable
            and op.approval is None
            and self.request.execution == self.run.binding.execution_reference
            and self.deliverable.execution_reference == self.request.execution
            and self.deliverable.reference == self.run.binding.deliverable_reference
            and self.deliverable.content_reference == bundle_content(self.retained.result).reference
            and self.inspection.plan == self.run.plan
            and self.inspection.result == self.retained.result
            and self.inspection.deliverable == self.deliverable
            and self.report.deliverable == self.deliverable
            and self.report.outcome == QAOutcome.PASS
            and self.inspection.reference == self.report.reference
            and lifecycle_qa_result(self.report) == op.qa
            and self.report.checked_at <= self.prepared_at
            and spec.execution_evidence is not None
            and spec.acceptance is not None
            and self.inspection.formats == spec.acceptance.formats
            and self.inspection.requirements == spec.acceptance.requirements
            and self.observation.opportunity.reference == op.reference
            and self.observation.source_reference == spec.source_context.source_reference
            and self.request.channel.listing == self.observation.source_reference
        )
        artifacts = {
            a.name: Reference("sha256:" + a.digest) for a in self.retained.result.artifacts
        }
        # Only retained operator-approved local inputs are copied into the scope.
        # Refuse recognizable credentials even when they originated in those inputs.
        for source in self.run.specification.sources:
            bounded(source.content, 1_000_000)
        for artifact in self.retained.result.artifacts:
            bounded(artifact.content, 2_000_000)
        require(all(name in artifacts for name in self.request.outbound.artifact_names))
        require(
            all(
                a.name in self.request.outbound.artifact_names
                and artifacts.get(a.name) == a.content_digest
                for a in self.request.outbound.published_artifacts
            )
        )

    @property
    def reference(self) -> Reference:
        return self.request.reference

    @property
    def account(self) -> AccountIdentity:
        return self.request.account

    @property
    def mode(self) -> SubmissionMode:
        return self.request.mode

    @property
    def representation_digest(self) -> Reference:
        return digest((self.request, self.deliverable, self.retained.result.artifacts))

    @property
    def scope(self) -> Reference:
        return Reference("submission-context:" + digest(self).value[7:])


class EvidenceType(StrEnum):
    RECEIPT_REPORT = "receipt_report"
    OUTCOME_REPORT = "outcome_report"
    PAYMENT_REPORT = "payment_report"
    ACCOUNT_NOTE = "account_note"


class EvidenceTrust(StrEnum):
    OPERATOR_REPORTED = "operator_reported"
    UNVERIFIED_SOURCE = "unverified_source"
    TEST_FIXTURE = "test_fixture"


class EvidenceState(StrEnum):
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class SubmissionEvidence:
    reference: Reference
    envelope: Reference
    submission: Reference | None
    kind: EvidenceType
    trust: EvidenceTrust
    state: EvidenceState
    actor: Reference
    observing_source: Reference | None
    provider: Reference
    account: Reference
    event: Reference | None
    event_at: datetime | None
    observed_at: datetime
    captured_at: datetime
    content_digest: Reference
    provenance: Reference
    parser_version: str = "operator-import-v1"
    contract_version: str = "submission-evidence-v1"

    def __post_init__(self) -> None:
        for item in (
            self.reference,
            self.envelope,
            self.actor,
            self.provider,
            self.account,
            self.provenance,
        ):
            identity(item)
        for optional in (self.submission, self.observing_source, self.event):
            if optional is not None:
                identity(optional)
        require(isinstance(self.kind, EvidenceType) and isinstance(self.trust, EvidenceTrust))
        require(isinstance(self.state, EvidenceState))
        require_aware_timestamp(self.observed_at)
        require_aware_timestamp(self.captured_at)
        require(self.observed_at <= self.captured_at)
        if self.event_at is not None:
            require_aware_timestamp(self.event_at)
            require(self.event_at <= self.observed_at)
        require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", self.content_digest.value)))
        require(
            self.parser_version == "operator-import-v1"
            and self.contract_version == "submission-evidence-v1"
        )
        require(self.trust != EvidenceTrust.UNVERIFIED_SOURCE or self.observing_source is not None)


@dataclass(frozen=True, slots=True)
class SubmissionConsent:
    envelope: SubmissionEnvelope
    review: Reference
    applied: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class ImportEvidence:
    reference: Reference
    envelope: Reference
    submission: Reference | None
    kind: EvidenceType
    trust: EvidenceTrust
    state: EvidenceState
    observing_source: Reference | None
    event: Reference | None
    event_at: datetime | None
    observed_at: datetime
    provenance: Reference
    capture: ReferencedText
