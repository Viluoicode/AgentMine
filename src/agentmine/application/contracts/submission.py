"""Evidence-bearing submission/payment results, including unresolved side effects."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.records import Versioned
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import Reward, RewardStage
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.payment import PaymentEvidence
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import (
    Deliverable,
    HumanApproval,
    Outcome,
    OutcomeStatus,
    QAResult,
    QAStatus,
    Submission,
)


class SubmissionMode(StrEnum):
    API = "API"
    MANUAL = "MANUAL"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class ManualSubmissionPackage:
    reference: Reference
    target: Reference
    deliverable: Deliverable
    content: ReferencedText
    instructions: tuple[str, ...]

    def __post_init__(self) -> None:
        require_reference(self.reference, "submission")
        require_reference(self.target, "target")
        if self.content.reference != self.deliverable.content_reference or not self.instructions:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "package", "Content and instructions required"
            )


@dataclass(frozen=True, slots=True)
class SubmissionRequest:
    """Stable reference is the submission identity and idempotency key."""

    reference: Reference
    deliverable: Deliverable
    qa: QAResult
    approval: HumanApproval
    target: Reference
    content: ReferencedText
    mode: SubmissionMode = SubmissionMode.API

    def __post_init__(self) -> None:
        require_reference(self.reference, "submission")
        if not isinstance(self.mode, SubmissionMode):
            raise DomainError(ErrorCode.INVALID_VALUE, "mode", "Known submission mode required")
        if (
            self.qa.status != QAStatus.PASSED
            or self.qa.deliverable != self.deliverable
            or self.approval.deliverable != self.deliverable
            or self.approval.target != self.target
            or self.content.reference != self.deliverable.content_reference
        ):
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "submission", "QA/approval mismatch")


@dataclass(frozen=True, slots=True)
class SubmissionDispatch:
    """Atomically bind an API intent to the approved authoritative revision."""

    request: SubmissionRequest
    opportunity_snapshot: Versioned[Opportunity]

    def __post_init__(self) -> None:
        op = self.opportunity_snapshot.value
        if (
            self.request.mode != SubmissionMode.API
            or self.request.deliverable != op.deliverable
            or self.request.qa != op.qa
            or self.request.approval != op.approval
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "dispatch", "Current API approval required"
            )
        op.begin_submission()  # State precondition belongs to Domain.

    @property
    def in_flight(self) -> Opportunity:
        return self.opportunity_snapshot.value.begin_submission()


class SubmissionAttemptStatus(StrEnum):
    CONFIRMED = "confirmed"
    HUMAN_ACTION_REQUIRED = "human_action_required"
    UNKNOWN = "unknown"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    reference: Reference
    status: SubmissionAttemptStatus
    observed_at: datetime
    submission: Submission | None
    explanation: str
    external_submission_id: str | None = None
    marketplace_response: str | None = None
    external_url: str | None = None
    manual_package: ManualSubmissionPackage | None = None
    recorded_by: Reference | None = None

    @property
    def submission_timestamp(self) -> datetime | None:
        return None if self.submission is None else self.submission.submitted_at

    def __post_init__(self) -> None:
        require_aware_timestamp(self.observed_at)
        if not isinstance(self.status, SubmissionAttemptStatus):
            raise DomainError(ErrorCode.INVALID_VALUE, "status", "Unknown submission status")
        if (self.status == SubmissionAttemptStatus.CONFIRMED) != (self.submission is not None):
            raise DomainError(ErrorCode.INVALID_VALUE, "submission", "Confirmation needs receipt")
        require_reference(self.reference, "submission")
        if self.recorded_by is not None:
            require_reference(self.recorded_by, "operator")
        for value in (self.external_submission_id, self.marketplace_response, self.external_url):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "metadata", "Nonblank text or unknown required"
                )
        if self.external_url is not None and (
            not self.external_url.startswith(("https://", "http://"))
            or any(ord(char) < 32 for char in self.external_url)
        ):
            raise DomainError(ErrorCode.INVALID_VALUE, "url", "HTTP(S) reference required")
        if self.manual_package is not None and (
            self.manual_package.reference != self.reference
            or self.status != SubmissionAttemptStatus.HUMAN_ACTION_REQUIRED
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "package", "Pending manual package mismatch"
            )
        if self.submission is not None and (
            self.submission.reference != self.reference
            or self.submission.submitted_at > self.observed_at
        ):
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "submission", "Receipt mismatch")


@dataclass(frozen=True, slots=True)
class OutcomeObservation:
    submission_reference: Reference
    observed_at: datetime
    outcome: Outcome | None

    def __post_init__(self) -> None:
        require_aware_timestamp(self.observed_at)
        if (
            self.outcome is not None
            and self.outcome.submission_reference != self.submission_reference
        ):
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "outcome", "Submission mismatch")


@dataclass(frozen=True, slots=True)
class PaymentVerificationRequest:
    submission: Submission
    outcome: Outcome

    def __post_init__(self) -> None:
        if (
            self.outcome.status != OutcomeStatus.ACCEPTED
            or self.outcome.submission_reference != self.submission.reference
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "payment", "Accepted submission required"
            )


class PaymentStatus(StrEnum):
    VERIFIED = "verified"
    PENDING = "pending"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class PaymentVerificationResult:
    submission_reference: Reference
    status: PaymentStatus
    observed_at: datetime
    payment: Reward | None
    explanation: str
    verification: PaymentEvidence | None = None

    def __post_init__(self) -> None:
        require_aware_timestamp(self.observed_at)
        require_reference(self.submission_reference, "submission")
        if not self.explanation.strip():
            raise DomainError(
                ErrorCode.INVALID_VALUE, "explanation", "Verification explanation required"
            )
        if (self.status == PaymentStatus.VERIFIED) != (self.verification is not None):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "verification",
                "Independent verification required for VERIFIED",
            )
        if self.verification is not None and (
            self.verification.reward != self.payment
            or self.verification.payment_timestamp > self.observed_at
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "verification",
                "Payment evidence or timestamp mismatch",
            )
        if not isinstance(self.status, PaymentStatus):
            raise DomainError(ErrorCode.INVALID_VALUE, "status", "Unknown payment status")
        if (self.status == PaymentStatus.VERIFIED) != (self.payment is not None):
            raise DomainError(ErrorCode.INVALID_VALUE, "payment", "Verified status needs payment")
        if self.payment is not None and (
            self.payment.stage != RewardStage.VERIFIED_PAYMENT
            or self.payment.submission_reference != self.submission_reference
        ):
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "payment", "Payment evidence mismatch")
