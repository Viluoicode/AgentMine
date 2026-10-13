"""Explicit configurable V1 heuristic, never execution or spending authorization."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from fractions import Fraction

from agentmine.domain.economics import EconomicAssessment, SignalEstimate
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.money import Money


class Recommendation(StrEnum):
    REJECT = "REJECT"
    WATCH = "WATCH"
    RECOMMEND = "RECOMMEND"
    ATTEMPT = "ATTEMPT"


class RecommendationReason(StrEnum):
    NONPOSITIVE_EXPECTED_NET_VALUE = "NONPOSITIVE_EXPECTED_NET_VALUE"
    UNKNOWN_SIGNALS = "UNKNOWN_SIGNALS"
    BELOW_RECOMMEND_THRESHOLD = "BELOW_RECOMMEND_THRESHOLD"
    RECOMMEND_THRESHOLD_MET = "RECOMMEND_THRESHOLD_MET"
    ATTEMPT_THRESHOLD_MET = "ATTEMPT_THRESHOLD_MET"


@dataclass(frozen=True, slots=True)
class ScoringSignals:
    risk: SignalEstimate  # Higher means riskier.
    competition: SignalEstimate  # Higher means more competition.
    deadline: SignalEstimate  # Higher means more favorable time remaining.
    ai_suitability: SignalEstimate
    historical_performance: SignalEstimate


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    economics: Decimal = Decimal(40)
    risk: Decimal = Decimal(15)
    competition: Decimal = Decimal(10)
    deadline: Decimal = Decimal(10)
    ai_suitability: Decimal = Decimal(15)
    historical_performance: Decimal = Decimal(10)

    def __post_init__(self) -> None:
        values = self.values
        if any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in values):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "weights", "Positive Decimal weights required"
            )
        if sum((Fraction(value) for value in values), Fraction(0)) != 100:
            raise DomainError(ErrorCode.INVALID_VALUE, "weights", "Weights must sum to 100")

    @property
    def values(self) -> tuple[Decimal, ...]:
        return (
            self.economics,
            self.risk,
            self.competition,
            self.deadline,
            self.ai_suitability,
            self.historical_performance,
        )


@dataclass(frozen=True, slots=True)
class ScoringPolicy:
    """Caller supplies a currency-specific target; no implicit exchange rate or pricing."""

    version: str
    net_value_target: Money
    rationale: str
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    recommend_threshold: Decimal = Decimal(60)
    attempt_threshold: Decimal = Decimal(80)

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.rationale.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "policy", "Version and rationale required")
        if self.net_value_target.amount <= 0:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "target", "Positive net value target required"
            )
        thresholds = (self.recommend_threshold, self.attempt_threshold)
        if any(not isinstance(v, Decimal) or not v.is_finite() for v in thresholds) or not (
            0 <= self.recommend_threshold < self.attempt_threshold <= 100
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "thresholds", "Ordered thresholds in [0, 100]"
            )


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    name: str
    estimate: SignalEstimate
    desirability: Decimal | None
    weight: Decimal
    points: Decimal


@dataclass(frozen=True, slots=True)
class ScoringAssessment:
    economics: EconomicAssessment
    signals: ScoringSignals
    policy: ScoringPolicy
    components: tuple[ScoreComponent, ...] = field(init=False)
    score: Decimal = field(init=False)
    recommendation: Recommendation = field(init=False)
    reasons: tuple[RecommendationReason, ...] = field(init=False)

    def __post_init__(self) -> None:
        net = self.economics.expected_net_value.amount
        net.require_same_currency(self.policy.net_value_target)
        # Score arithmetic has a documented independent 50-digit context; final score
        # rounds once to two decimals, half-even. Monetary forecasts are not rounded.
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            normalized = max(
                Decimal(0), min(Decimal(1), net.amount / self.policy.net_value_target.amount)
            )
            specifications = (
                (
                    "economics",
                    SignalEstimate(normalized, "clamp(expected net / policy target, 0, 1)"),
                    False,
                ),
                ("risk", self.signals.risk, True),
                ("competition", self.signals.competition, True),
                ("deadline", self.signals.deadline, False),
                ("ai_suitability", self.signals.ai_suitability, False),
                ("historical_performance", self.signals.historical_performance, False),
            )
            components: list[ScoreComponent] = []
            for (name, estimate, invert), weight in zip(
                specifications, self.policy.weights.values, strict=True
            ):
                desirability = estimate.value
                if desirability is not None and invert:
                    desirability = 1 - desirability
                points = Decimal(0) if desirability is None else desirability * weight
                components.append(ScoreComponent(name, estimate, desirability, weight, points))
            score = sum((c.points for c in components), Decimal(0)).quantize(Decimal("0.01"))
        if net.amount <= 0:
            recommendation = Recommendation.REJECT
            reason = RecommendationReason.NONPOSITIVE_EXPECTED_NET_VALUE
        elif any(c.desirability is None for c in components):
            recommendation = Recommendation.WATCH
            reason = RecommendationReason.UNKNOWN_SIGNALS
        elif score >= self.policy.attempt_threshold:
            recommendation = Recommendation.ATTEMPT
            reason = RecommendationReason.ATTEMPT_THRESHOLD_MET
        elif score >= self.policy.recommend_threshold:
            recommendation = Recommendation.RECOMMEND
            reason = RecommendationReason.RECOMMEND_THRESHOLD_MET
        else:
            recommendation = Recommendation.WATCH
            reason = RecommendationReason.BELOW_RECOMMEND_THRESHOLD
        object.__setattr__(self, "components", tuple(components))
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "recommendation", recommendation)
        object.__setattr__(self, "reasons", (reason,))
