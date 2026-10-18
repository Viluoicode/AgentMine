"""Independent payment evidence; claims of acceptance are not settlement evidence."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import Reward, RewardStage
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference


class PaymentVerificationMethod(StrEnum):
    INDEPENDENT_LEDGER = "independent_ledger"
    PAYMENT_PROVIDER_SETTLEMENT = "payment_provider_settlement"


@dataclass(frozen=True, slots=True)
class PaymentEvidence:
    reward: Reward
    payment_reference: Reference
    payment_timestamp: datetime
    verification_source: Reference
    verification_record: Reference
    method: PaymentVerificationMethod

    def __post_init__(self) -> None:
        for value in (self.payment_reference, self.verification_source, self.verification_record):
            require_reference(value, "payment_evidence")
        require_aware_timestamp(self.payment_timestamp)
        if (
            not isinstance(self.method, PaymentVerificationMethod)
            or not isinstance(self.reward, Reward)
            or self.reward.stage != RewardStage.VERIFIED_PAYMENT
            or self.reward.evidence != self.verification_record
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "payment",
                "Matching independently verified settlement evidence required",
            )
