"""Narrow human resolution of a known manual channel, never a policy override."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Eligibility, EligibilityReason, EligibilityStatus


class EligibilityChoice(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class ManualEligibilityEvidence:
    destination: Reference
    instructions: Reference
    account_access: Reference
    requirements: Reference
    requirements_satisfied: bool

    def __post_init__(self) -> None:
        for ref in (self.destination, self.instructions, self.account_access, self.requirements):
            require_reference(ref, "manual_evidence")
        if self.requirements_satisfied is not True:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "manual_evidence",
                "Manual requirements must be explicitly satisfied",
            )


@dataclass(frozen=True, slots=True)
class EligibilityResolution:
    review_reference: Reference
    actor: Reference
    decided_at: datetime
    choice: EligibilityChoice
    rationale: str
    evidence: ManualEligibilityEvidence | None = None

    @property
    def status(self) -> EligibilityStatus:
        """The recorded decision's result, never a fresh grant or submission consent."""
        return (
            EligibilityStatus.ELIGIBLE
            if self.choice == EligibilityChoice.APPROVE
            else EligibilityStatus.INELIGIBLE
        )

    def __post_init__(self) -> None:
        require_reference(self.review_reference, "eligibility_review")
        require_reference(self.actor, "operator")
        require_aware_timestamp(self.decided_at)
        if (
            not isinstance(self.choice, EligibilityChoice)
            or not isinstance(self.rationale, str)
            or not self.rationale.strip()
            or len(self.rationale) > 4000
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE,
                "eligibility_resolution",
                "Decision and bounded rationale required",
            )
        if self.choice == EligibilityChoice.APPROVE and not isinstance(
            self.evidence, ManualEligibilityEvidence
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "manual_evidence",
                "Documented manual readiness required",
            )
        if self.choice == EligibilityChoice.REJECT and self.evidence is not None:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "manual_evidence", "Rejection has no consent"
            )

    def resolve(self, recomputed: Eligibility) -> Eligibility:
        if self.choice == EligibilityChoice.REJECT:
            return Eligibility(
                EligibilityStatus.INELIGIBLE,
                self.rationale,
                (*recomputed.reasons, EligibilityReason.HUMAN_ELIGIBILITY_REJECTED),
            )
        if recomputed.status != EligibilityStatus.REQUIRES_HUMAN_REVIEW or recomputed.reasons != (
            EligibilityReason.MANUAL_SUBMISSION_REQUIRED,
        ):
            raise DomainError(
                ErrorCode.EXECUTION_FORBIDDEN,
                "eligibility_resolution",
                "Only an otherwise eligible manual channel may be resolved",
            )
        return Eligibility(
            EligibilityStatus.ELIGIBLE,
            self.rationale,
            (*recomputed.reasons, EligibilityReason.HUMAN_ELIGIBILITY_APPROVED),
        )
