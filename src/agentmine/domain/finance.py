"""Distinct reward stages, estimates and recorded cost evidence."""

from dataclasses import dataclass
from enum import StrEnum

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.money import Money
from agentmine.domain.values import Reference, require_reference


class RewardStage(StrEnum):
    POTENTIAL = "potential"
    ACCEPTED = "accepted"
    VERIFIED_PAYMENT = "verified_payment"


@dataclass(frozen=True, slots=True)
class Reward:
    amount: Money
    stage: RewardStage = RewardStage.POTENTIAL
    evidence: Reference | None = None
    submission_reference: Reference | None = None

    def __post_init__(self) -> None:
        self.amount.require_nonnegative("reward")
        if not isinstance(self.stage, RewardStage):
            raise DomainError(ErrorCode.INVALID_VALUE, "reward_stage", "Unknown reward stage")
        if self.stage != RewardStage.POTENTIAL:
            if self.evidence is None or self.submission_reference is None:
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "evidence", "Evidence and submission required"
                )
            require_reference(self.evidence, "evidence")
            require_reference(self.submission_reference, "submission_reference")
        elif self.submission_reference is not None:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "submission_reference", "Potential reward is unsubmitted"
            )


@dataclass(frozen=True, slots=True)
class ExpectedValue:
    """An estimate, never accepted reward or verified revenue."""

    amount: Money
    rationale: str

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise DomainError(
                ErrorCode.INVALID_VALUE, "rationale", "Estimate rationale is required"
            )


class CostCategory(StrEnum):
    AI = "ai"
    TOOL = "tool"
    INFRASTRUCTURE = "infrastructure"
    TRANSACTION = "transaction"


@dataclass(frozen=True, slots=True)
class Cost:
    reference: Reference
    amount: Money
    category: CostCategory

    def __post_init__(self) -> None:
        require_reference(self.reference, "cost_reference")
        self.amount.require_nonnegative("cost")
        if not isinstance(self.category, CostCategory):
            raise DomainError(ErrorCode.INVALID_VALUE, "cost_category", "Unknown cost category")
