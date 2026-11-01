"""Outcome evidence ownership and independently authenticated read-only verification."""

from typing import Protocol

from agentmine.application.contracts.outcome_evidence import (
    OutcomeEvent,
    OutcomeVerification,
    OutcomeVerificationRequest,
    OutcomeVerificationView,
)
from agentmine.domain.values import Reference


class OutcomeEvidenceVerifier(Protocol):
    def accepts(self, decision: OutcomeVerification) -> bool:
        """Authenticate retained decision authority under the configured verifier contract."""
        ...

    def verify(self, request: OutcomeVerificationRequest) -> OutcomeVerification:
        """Independently authenticate exact provider/account/listing/event/content/stage.

        Reports, screenshots, URLs, source labels and hashes are not authentication.
        Read-only: never submit, mutate accounts or settle payment. No paid calls.
        Return BLOCKED/UNVERIFIED/UNKNOWN when authority cannot be established.
        VERIFIED is an assertion by a trusted adapter, never supplied by CLI inputs.
        """
        ...


class OutcomeEvidenceRepository(Protocol):
    def record(self, event: OutcomeEvent) -> OutcomeEvent: ...
    def get(self, reference: Reference) -> OutcomeEvent | None: ...
    def prepare(self, request: OutcomeVerificationRequest) -> OutcomeVerificationRequest: ...
    def inspect(self, reference: Reference) -> OutcomeVerificationView | None: ...
    def retain(self, decision: OutcomeVerification) -> OutcomeVerification: ...
    def apply(self, decision: OutcomeVerification) -> None:
        """CAS final Outcome plus receipt atomically; preserve terminal history and all money."""
        ...
