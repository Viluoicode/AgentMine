"""External capabilities expressed in AgentMine vocabulary, independent of vendors."""

from datetime import datetime
from typing import Protocol

from agentmine.application.contracts.ai import (
    AIResponse,
    DeliverableDraft,
    EvaluationAdvice,
    EvaluationRequest,
    QAAdvice,
    QARequest,
    WorkRequest,
)
from agentmine.application.contracts.opportunities import (
    DiscoveryRequest,
    OpportunityBatch,
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.contracts.submission import (
    OutcomeObservation,
    PaymentVerificationRequest,
    PaymentVerificationResult,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.domain.work import Submission


class OpportunitySource(Protocol):
    """Discover observations and refresh open/deadline facts; no eligibility policy."""

    def discover(self, request: DiscoveryRequest) -> OpportunityBatch: ...

    def refresh(self, request: RefreshOpportunityRequest) -> OpportunityStatus: ...


class LLMProvider(Protocol):
    """Budget-authorized V1 assistance; results are advice/drafts, never approvals."""

    def evaluate_opportunity(self, request: EvaluationRequest) -> AIResponse[EvaluationAdvice]: ...

    def perform_work(self, request: WorkRequest) -> AIResponse[DeliverableDraft]: ...

    def review_deliverable(self, request: QARequest) -> AIResponse[QAAdvice]: ...


class SubmissionGateway(Protocol):
    """Submit API requests using their stable reference as provider idempotency key.

    reconcile is observation-only: it MUST NOT send/create another submission.
    Confirm only with a correlated receipt; retain ID, sanitized response and URL
    when available. Unknown metadata stays None; confirmation is not acceptance.
    """

    def submit(self, request: SubmissionRequest) -> SubmissionResult: ...

    def reconcile(self, request: SubmissionRequest) -> SubmissionResult: ...

    def track_outcome(self, submission: Submission) -> OutcomeObservation: ...


class PaymentVerifier(Protocol):
    """Read independent ledger/provider settlement evidence for the authorized recipient.

    Verify submission correlation, amount/currency, settlement time and payment ID.
    A marketplace winner flag, operator claim or model output is not independent
    evidence: return PENDING/UNVERIFIABLE, with no payment, when proof is unavailable.
    Implementations supply stable verification-source IDs and auditable records.
    No payment transfer, wallet action or guessed provider contract is authorized.
    """

    def verify_payment(self, request: PaymentVerificationRequest) -> PaymentVerificationResult: ...


class Clock(Protocol):
    """Return a timezone-aware UTC instant; application supplies time to Domain."""

    def now(self) -> datetime: ...
