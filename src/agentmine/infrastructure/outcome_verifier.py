"""No independently authenticated marketplace outcome contract is configured."""

from dataclasses import dataclass

from agentmine.application.contracts.outcome_evidence import (
    OutcomeVerification,
    OutcomeVerificationRequest,
    VerificationStatus,
)
from agentmine.application.ports.services import Clock


@dataclass(frozen=True, slots=True)
class UnavailableOutcomeVerifier:
    clock: Clock

    def accepts(self, decision: OutcomeVerification) -> bool:
        return False

    def verify(self, request: OutcomeVerificationRequest) -> OutcomeVerification:
        return OutcomeVerification(
            request,
            VerificationStatus.BLOCKED,
            None,
            (
                "No independently authenticated provider outcome contract configured; "
                "report remains provisional"
            ),
            self.clock.now(),
        )
