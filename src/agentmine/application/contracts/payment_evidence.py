"""Reported payment hints and immutable local context; never settlement authority."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.submission_context import (
    AccountIdentity,
    EvidenceState,
    EvidenceTrust,
    EvidenceType,
    SubmissionEvidence,
    bounded,
    https_location,
    identity,
    require,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference, require_aware_timestamp


class PaymentEvidenceStatus(StrEnum):
    UNKNOWN = "unknown"
    MISSING = "missing"
    CAPTURE_PENDING = "capture_pending"
    CAPTURE_RETAINED = "capture_retained"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"


class PaymentReportError(PortError):
    def __init__(self, status: PaymentEvidenceStatus) -> None:
        self.status = status
        super().__init__(PortErrorCode.CONFLICT, "payment_report", status.value)


@dataclass(frozen=True, slots=True)
class PaymentReportRequest:
    reference: Reference
    handoff: Reference
    outcome_reference: Reference | None
    event_at: datetime | None
    observed_at: datetime
    provenance: Reference
    capture: ReferencedText
    transaction_hint: str | None = None
    url_hint: str | None = None
    asset_hint: str | None = None
    network_hint: str | None = None
    recipient_hint: str | None = None
    amount_hint: str | None = None

    def __post_init__(self) -> None:
        for ref in (self.reference, self.handoff, self.provenance):
            identity(ref)
        if self.outcome_reference is not None:
            identity(self.outcome_reference)
        require_aware_timestamp(self.observed_at)
        if self.event_at is not None:
            require_aware_timestamp(self.event_at)
            require(self.event_at <= self.observed_at)
        bounded(self.capture.text, 64000)
        identity(self.capture.reference)
        for hint in (
            self.transaction_hint,
            self.asset_hint,
            self.network_hint,
            self.recipient_hint,
            self.amount_hint,
        ):
            if hint is not None:
                bounded(hint, 500)
        if self.url_hint is not None:
            https_location(self.url_hint)


@dataclass(frozen=True, slots=True)
class PaymentReport:
    request: PaymentReportRequest
    envelope: Reference
    scope: Reference
    account: AccountIdentity
    channel: Reference
    listing: Reference
    actor: Reference
    ledger: Reference
    source_snapshot: Versioned[Opportunity]
    prepared_at: datetime
    contract_version: str = "provisional-payment-report-v1"

    def __post_init__(self) -> None:
        for ref in (self.envelope, self.scope, self.channel, self.listing, self.actor, self.ledger):
            identity(ref)
        require_aware_timestamp(self.prepared_at)
        op = self.source_snapshot.value
        require(
            self.contract_version == "provisional-payment-report-v1"
            and op.submission is not None
            and op.deliverable == op.submission.deliverable
            and self.request.observed_at <= self.prepared_at
            and self.request.outcome_reference
            == (None if op.outcome is None else op.outcome.evidence)
        )
        if self.request.event_at is not None:
            assert op.submission is not None
            require(self.request.event_at >= op.submission.submitted_at)

    @property
    def reference(self) -> Reference:
        return self.request.reference


@dataclass(frozen=True, slots=True)
class PaymentObservation:
    report_reference: Reference
    metadata: SubmissionEvidence
    contract_version: str = "provisional-payment-observation-v1"

    def __post_init__(self) -> None:
        identity(self.report_reference)
        require(
            self.metadata.reference == self.report_reference
            and self.metadata.kind == EvidenceType.PAYMENT_REPORT
            and self.metadata.trust == EvidenceTrust.OPERATOR_REPORTED
            and self.metadata.state == EvidenceState.UNVERIFIED
            and self.metadata.observing_source is None
            and self.metadata.event is None
            and self.contract_version == "provisional-payment-observation-v1"
        )


@dataclass(frozen=True, slots=True)
class PaymentEvidenceView:
    reference: Reference
    status: PaymentEvidenceStatus
    report: PaymentReport | None = None
    observation: PaymentObservation | None = None
    metadata: SubmissionEvidence | None = None
    capture_retained: bool = False
