"""Immutable provisional events and independent verification decisions; no payment."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.manual_handoff import ManualReceipt
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.submission_context import (
    EvidenceState,
    EvidenceTrust,
    EvidenceType,
    SubmissionEvidence,
    bounded,
    identity,
    require,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.domain.work import Outcome, OutcomeStatus


class OutcomeEventType(StrEnum):
    SUBMISSION_REPORTED = "submission_reported"
    SUBMISSION_RECEIVED = "submission_received"
    APPLICATION_SELECTED = "application_selected"
    UNDER_REVIEW = "under_review"
    DELIVERABLE_ACCEPTED = "deliverable_accepted"
    DELIVERABLE_REJECTED = "deliverable_rejected"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    UNKNOWN = "unknown"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"
    CONFLICT = "conflict"
    VERIFIED = "verified"


class OutcomeEvidenceError(PortError):
    def __init__(self, diagnostic: VerificationStatus) -> None:
        self.diagnostic = diagnostic
        super().__init__(PortErrorCode.CONFLICT, "outcome_evidence", diagnostic.value)


@dataclass(frozen=True, slots=True)
class ReportOutcomeEvent:
    handoff: Reference
    reference: Reference
    provider_event: Reference
    event_type: OutcomeEventType
    event_at: datetime
    observed_at: datetime
    provenance: Reference
    capture: ReferencedText


@dataclass(frozen=True, slots=True)
class OutcomeEvent:
    receipt: ManualReceipt
    metadata: SubmissionEvidence
    event_type: OutcomeEventType
    parser_version: str = "reported-outcome-v1"

    def __post_init__(self) -> None:
        draft = self.receipt.claim.draft
        meta = self.metadata
        require(isinstance(self.event_type, OutcomeEventType))
        require(self.parser_version == "reported-outcome-v1")
        require(
            meta.kind == EvidenceType.OUTCOME_REPORT
            and meta.trust == EvidenceTrust.OPERATOR_REPORTED
            and meta.state == EvidenceState.UNVERIFIED
            and meta.observing_source is None
            and meta.envelope == draft.envelope.reference
            and meta.submission == draft.submission_reference
            and meta.account == draft.envelope.account.reference
            and meta.provider == draft.envelope.account.provider
            and meta.actor == draft.envelope.run.specification.actor
            and meta.event is not None
            and meta.event_at is not None
            and meta.event_at >= self.receipt.submission.submitted_at
        )

    @property
    def reference(self) -> Reference:
        return self.metadata.reference


@dataclass(frozen=True, slots=True)
class OutcomeVerificationRequest:
    reference: Reference
    event: OutcomeEvent
    snapshot: Versioned[Opportunity]

    def __post_init__(self) -> None:
        identity(self.reference)
        require(
            self.snapshot.value.state == OpportunityState.SUBMITTED
            and self.snapshot.value.submission == self.event.receipt.submission
            and self.snapshot.value.deliverable == self.event.receipt.submission.deliverable
            and self.snapshot.value.outcome is None
            and self.snapshot.value.payment is None
        )


@dataclass(frozen=True, slots=True)
class OutcomeVerification:
    request: OutcomeVerificationRequest
    status: VerificationStatus
    authority: Reference | None
    rationale: str
    verified_at: datetime
    contract_version: str = "outcome-verification-v1"

    def __post_init__(self) -> None:
        require(isinstance(self.status, VerificationStatus))
        require_aware_timestamp(self.verified_at)
        bounded(self.rationale, 4000)
        require(self.verified_at >= self.request.event.metadata.captured_at)
        require(self.contract_version == "outcome-verification-v1")
        require((self.status == VerificationStatus.VERIFIED) == (self.authority is not None))
        if self.authority is not None:
            identity(self.authority)

    @property
    def outcome(self) -> Outcome | None:
        if self.status != VerificationStatus.VERIFIED:
            return None
        kind = self.request.event.event_type
        if kind not in (
            OutcomeEventType.DELIVERABLE_ACCEPTED,
            OutcomeEventType.DELIVERABLE_REJECTED,
        ):
            return None
        return Outcome(
            self.request.event.receipt.submission.reference,
            OutcomeStatus.ACCEPTED
            if kind == OutcomeEventType.DELIVERABLE_ACCEPTED
            else OutcomeStatus.REJECTED,
            self.request.reference,
            rejection_reason=self.rationale
            if kind == OutcomeEventType.DELIVERABLE_REJECTED
            else None,
        )


@dataclass(frozen=True, slots=True)
class OutcomeVerificationView:
    request: OutcomeVerificationRequest
    decision: OutcomeVerification | None
    applied: bool
    current: Versioned[Opportunity] | None

    @property
    def diagnostic(self) -> str:
        if self.applied:
            return "APPLIED"
        if self.current != self.request.snapshot:
            return "CONFLICT"
        if self.decision is None:
            return "UNKNOWN"
        if self.decision.outcome is not None:
            return "FINALIZATION_PENDING"
        return self.decision.status.name
