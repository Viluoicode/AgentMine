"""Auditable forecasts, separate from actual costs and verified revenue."""

from dataclasses import dataclass, field
from decimal import Context, Decimal, localcontext

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import ExpectedValue, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.values import Reference, require_reference


@dataclass(frozen=True, slots=True)
class SignalEstimate:
    """A subjective unit-interval estimate; None explicitly means unknown."""

    value: Decimal | None
    rationale: str
    evidence: tuple[Reference, ...] = ()

    def __post_init__(self) -> None:
        if self.value is not None and (
            not isinstance(self.value, Decimal)
            or not self.value.is_finite()
            or not 0 <= self.value <= 1
        ):
            raise DomainError(ErrorCode.INVALID_VALUE, "signal", "Decimal in [0, 1] required")
        if not self.rationale.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "rationale", "Estimate rationale required")
        if not isinstance(self.evidence, tuple):
            raise DomainError(ErrorCode.INVALID_VALUE, "evidence", "Immutable evidence required")
        for reference in self.evidence:
            require_reference(reference, "evidence")


@dataclass(frozen=True, slots=True)
class EstimatedCosts:
    ai: Money
    tool: Money
    infrastructure: Money
    transaction: Money

    def __post_init__(self) -> None:
        for cost in (self.ai, self.tool, self.infrastructure, self.transaction):
            cost.require_nonnegative("estimated_cost")
            self.ai.require_same_currency(cost)

    @property
    def total(self) -> Money:
        return self.ai + self.tool + self.infrastructure + self.transaction


@dataclass(frozen=True, slots=True)
class EconomicInputs:
    predicted_success_probability: SignalEstimate
    estimated_cost: EstimatedCosts
    cost_rationale: str
    cost_evidence: tuple[Reference, ...] = ()

    def __post_init__(self) -> None:
        if self.predicted_success_probability.value is None:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "probability", "A documented prediction is required"
            )
        if not self.cost_rationale.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "cost_rationale", "Cost rationale required")
        if not isinstance(self.cost_evidence, tuple):
            raise DomainError(ErrorCode.INVALID_VALUE, "evidence", "Immutable evidence required")
        for reference in self.cost_evidence:
            require_reference(reference, "cost_evidence")


@dataclass(frozen=True, slots=True)
class EconomicAssessment:
    potential_reward: Reward
    inputs: EconomicInputs
    expected_gross_value: Money = field(init=False)
    expected_net_value: ExpectedValue = field(init=False)

    def __post_init__(self) -> None:
        if self.potential_reward.stage != RewardStage.POTENTIAL:
            raise DomainError(ErrorCode.INVALID_VALUE, "reward", "Potential reward required")
        reward = self.potential_reward.amount
        reward.require_same_currency(self.inputs.estimated_cost.total)
        probability = self.inputs.predicted_success_probability.value
        assert probability is not None  # EconomicInputs validates this invariant.
        # Finite Decimal multiplication needs at most the sum of coefficient lengths.
        # Own context makes calculations independent of process-wide decimal settings.
        precision = len(reward.amount.as_tuple().digits) + len(probability.as_tuple().digits) + 2
        with localcontext(Context(prec=precision)):
            gross = Money(reward.amount * probability, reward.currency)
        net = gross - self.inputs.estimated_cost.total
        object.__setattr__(self, "expected_gross_value", gross)
        object.__setattr__(
            self,
            "expected_net_value",
            ExpectedValue(
                net, "Potential reward * predicted success probability - estimated costs"
            ),
        )
