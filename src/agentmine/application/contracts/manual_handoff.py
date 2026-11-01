"""Offline manual intent and provisional receipts, never permission to act externally."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.submission import (
    SubmissionAttemptStatus,
    SubmissionMode,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.contracts.submission_context import (
    EffectKnowledge,
    EvidenceState,
    EvidenceTrust,
    EvidenceType,
    SubmissionEnvelope,
    SubmissionEvidence,
    bounded,
    https_location,
    identity,
    require,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.domain.work import Submission


class PermissionStatus(StrEnum):
    UNVERIFIED = "unverified"
    OFFLINE_TEST_ONLY = "offline_test_only"


class HandoffReason(StrEnum):
    NONE = "none"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CHANNEL_UNVERIFIED = "channel_unverified"
    ACCOUNT_EFFECTS_UNSUPPORTED = "account_effects_unsupported"
    CONSENT_NOT_APPLIED = "consent_not_applied"
    CONTEXT_UNSUPPORTED = "context_unsupported"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_CHANGED = "source_changed"
    ELIGIBILITY_BLOCKED = "eligibility_blocked"
    EVIDENCE_INVALID = "evidence_invalid"
    STALE_STATE = "stale_state"
    LEDGER_CHANGED = "ledger_changed"
    UNKNOWN_POSSIBLE_ACTION = "unknown_possible_action"
    RECEIPT_RETAINED = "receipt_retained"
    NOT_FOUND = "not_found"


class HandoffError(PortError):
    def __init__(self, reason: HandoffReason) -> None:
        self.reason = reason
        super().__init__(PortErrorCode.CONFLICT, "manual_handoff", reason.value)


@dataclass(frozen=True, slots=True)
class ChannelPermission:
    scope: Reference
    observed_at: datetime
    status: PermissionStatus
    evidence: Reference

    def __post_init__(self) -> None:
        identity(self.scope)
        identity(self.evidence)
        require_aware_timestamp(self.observed_at)
        require(isinstance(self.status, PermissionStatus))


@dataclass(frozen=True, slots=True)
class HandoffReadiness:
    envelope: Reference
    reason: HandoffReason
    permission: ChannelPermission | None


@dataclass(frozen=True, slots=True)
class ManualHandoffDraft:
    reference: Reference
    submission_reference: Reference
    envelope: SubmissionEnvelope
    review_reference: Reference
    approved_snapshot: Versioned[Opportunity]
    ledger_revision: int
    prepared_at: datetime
    permission: ChannelPermission

    def __post_init__(self) -> None:
        for ref in (self.reference, self.submission_reference, self.review_reference):
            identity(ref)
        require_aware_timestamp(self.prepared_at)
        op = self.approved_snapshot.value
        old = self.envelope.opportunity_snapshot
        require(
            self.envelope.mode == SubmissionMode.MANUAL
            and self.envelope.request.channel.effects == EffectKnowledge.NONE_DECLARED
            and op.state == OpportunityState.APPROVED_FOR_SUBMISSION
            and op.approval is not None
            and op.approval.target == self.envelope.scope
            and op.approval.deliverable == self.envelope.deliverable
            and op.approval.actor == self.envelope.run.specification.actor
            and old.value.approve(op.approval) == op
            and self.approved_snapshot.revision == old.revision + 1
            and op.approval.approved_at <= self.prepared_at
            and type(self.ledger_revision) is int
            and self.ledger_revision >= 1
            and self.permission.scope == self.envelope.scope
            and self.permission.status == PermissionStatus.OFFLINE_TEST_ONLY
            and self.envelope.prepared_at <= self.permission.observed_at <= self.prepared_at
        )

    @property
    def request(self) -> SubmissionRequest:
        op = self.approved_snapshot.value
        assert op.qa is not None and op.approval is not None
        return SubmissionRequest(
            self.submission_reference,
            self.envelope.deliverable,
            op.qa,
            op.approval,
            self.envelope.scope,
            bundle_content(self.envelope.retained.result),
            SubmissionMode.MANUAL,
        )

    @property
    def in_flight(self) -> Versioned[Opportunity]:
        return Versioned(
            self.approved_snapshot.value.begin_submission(), self.approved_snapshot.revision + 1
        )


@dataclass(frozen=True, slots=True)
class ManualHandoffClaim:
    draft: ManualHandoffDraft
    confirmed_at: datetime
    permission: ChannelPermission

    def __post_init__(self) -> None:
        require_aware_timestamp(self.confirmed_at)
        require(
            self.draft.prepared_at <= self.permission.observed_at <= self.confirmed_at
            and self.permission.scope == self.draft.envelope.scope
            and self.permission.status == PermissionStatus.OFFLINE_TEST_ONLY
        )


@dataclass(frozen=True, slots=True)
class ReportManualReceipt:
    handoff: Reference
    evidence_reference: Reference
    reported_at: datetime
    observed_at: datetime
    provenance: Reference
    capture: ReferencedText
    external_id: str | None = None
    external_url: str | None = None


@dataclass(frozen=True, slots=True)
class ManualReceipt:
    claim: ManualHandoffClaim
    evidence: SubmissionEvidence
    capture: ReferencedText
    external_id: str | None
    external_url: str | None

    def __post_init__(self) -> None:
        draft = self.claim.draft
        evidence = self.evidence
        require(
            evidence.envelope == draft.envelope.reference
            and evidence.submission == draft.submission_reference
            and evidence.actor == draft.envelope.run.specification.actor
            and evidence.account == draft.envelope.account.reference
            and evidence.provider == draft.envelope.account.provider
            and evidence.kind == EvidenceType.RECEIPT_REPORT
            and evidence.trust == EvidenceTrust.OPERATOR_REPORTED
            and evidence.state == EvidenceState.UNVERIFIED
            and evidence.observing_source is None
            and evidence.event_at is not None
            and self.claim.confirmed_at <= evidence.event_at <= evidence.observed_at
            and evidence.content_digest == self.capture.reference
        )
        bounded(self.capture.text, 64000)
        if self.external_id is not None:
            bounded(self.external_id, 300)
        require(
            evidence.event == (None if self.external_id is None else Reference(self.external_id))
        )
        if self.external_url is not None:
            https_location(self.external_url)

    @property
    def submission(self) -> Submission:
        request = self.claim.draft.request
        assert self.evidence.event_at is not None
        return Submission(
            request.reference,
            request.deliverable,
            request.qa,
            request.approval,
            request.target,
            self.evidence.reference,
            self.evidence.event_at,
        )

    @property
    def result(self) -> SubmissionResult:
        return SubmissionResult(
            self.submission.reference,
            SubmissionAttemptStatus.CONFIRMED,
            self.evidence.captured_at,
            self.submission,
            (
                "OFFLINE_ONLY operator-reported UNVERIFIED receipt; "
                "no independent send/outcome/payment evidence"
            ),
            self.external_id,
            self.capture.text,
            self.external_url,
            recorded_by=self.evidence.actor,
        )


@dataclass(frozen=True, slots=True)
class ManualHandoffView:
    draft: ManualHandoffDraft
    claim: ManualHandoffClaim | None
    receipt: ManualReceipt | None
    applied: bool
    opportunity: Versioned[Opportunity] | None

    @property
    def reason(self) -> HandoffReason:
        if self.applied:
            return HandoffReason.NONE
        expected = self.draft.approved_snapshot if self.claim is None else self.draft.in_flight
        if self.opportunity != expected:
            return HandoffReason.STALE_STATE
        if self.receipt is not None:
            return HandoffReason.RECEIPT_RETAINED
        return HandoffReason.NONE if self.claim is None else HandoffReason.UNKNOWN_POSSIBLE_ACTION

    @property
    def status(self) -> str:
        if self.applied:
            return "SUBMITTED_HISTORY"
        if self.reason == HandoffReason.STALE_STATE:
            return "BLOCKED"
        if self.receipt is not None:
            return "RECEIPT_PENDING"
        return "PREPARED" if self.claim is None else "IN_FLIGHT_UNKNOWN"
