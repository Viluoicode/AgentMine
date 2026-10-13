from dataclasses import replace
from decimal import Decimal, Inexact, localcontext

import pytest

from agentmine.domain.economics import (
    EconomicAssessment,
    EconomicInputs,
    EstimatedCosts,
    SignalEstimate,
)
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.scoring import (
    Recommendation,
    RecommendationReason,
    ScoringAssessment,
    ScoringPolicy,
    ScoringSignals,
    ScoringWeights,
)
from agentmine.domain.values import Reference


def money(value: str, currency: str = "USD") -> Money:
    return Money(Decimal(value), currency)


def signal(value: str | None) -> SignalEstimate:
    return SignalEstimate(None if value is None else Decimal(value), "Documented subjective input")


def economics(reward: str = "100", probability: str = "0.8") -> EconomicAssessment:
    return EconomicAssessment(
        Reward(money(reward)),
        EconomicInputs(
            signal(probability),
            EstimatedCosts(money("10"), money("5"), money("3"), money("2")),
            "Explicit four-category estimate",
            (Reference("cost-basis"),),
        ),
    )


def signals() -> ScoringSignals:
    return ScoringSignals(signal("0"), signal("0"), signal("1"), signal("1"), signal("1"))


def policy() -> ScoringPolicy:
    return ScoringPolicy("v1", money("100"), "Illustrative USD target, not empirical calibration")


@pytest.mark.parametrize(
    ("reward", "probability", "gross", "net"),
    [
        ("100", "0.8", "80", "60"),
        ("100", "0", "0", "-20"),
        ("100", "1", "100", "80"),
        ("0", "1", "0", "-20"),
        ("100", "0.2", "20", "0"),
        ("12.345", "0.1234", "1.523373", "-18.476627"),
    ],
)
def test_exact_expected_net_value(reward: str, probability: str, gross: str, net: str) -> None:
    result = economics(reward, probability)
    assert result.expected_gross_value == money(gross)
    assert result.inputs.estimated_cost.total == money("20")
    assert result.expected_net_value.amount == money(net)
    assert result.inputs.predicted_success_probability.rationale


@pytest.mark.parametrize("value", ["-0.01", "1.01", "NaN", "Infinity", "-Infinity"])
def test_invalid_signal(value: str) -> None:
    with pytest.raises(DomainError):
        signal(value)


def test_probability_must_be_known_and_explained() -> None:
    with pytest.raises(DomainError):
        replace(economics().inputs, predicted_success_probability=signal(None))
    with pytest.raises(DomainError):
        SignalEstimate(Decimal("0.5"), " ")
    with pytest.raises(DomainError):
        replace(economics().inputs, cost_rationale=" ")


@pytest.mark.parametrize("category", ["ai", "tool", "infrastructure", "transaction"])
def test_each_cost_must_be_nonnegative_and_same_currency(category: str) -> None:
    costs = economics().inputs.estimated_cost
    with pytest.raises(DomainError):
        replace(costs, **{category: money("-1")})
    with pytest.raises(DomainError):
        replace(costs, **{category: money("1", "EUR")})


def test_reward_currency_and_stage_checked() -> None:
    with pytest.raises(DomainError):
        EconomicAssessment(Reward(money("100", "EUR")), economics().inputs)
    accepted = Reward(money("100"), RewardStage.ACCEPTED, Reference("evidence"), Reference("sub"))
    with pytest.raises(DomainError):
        EconomicAssessment(accepted, economics().inputs)


def test_components_are_stored_and_explain_score() -> None:
    result = ScoringAssessment(economics(), signals(), policy())
    assert result.score == Decimal("84.00")
    assert [c.points for c in result.components] == list(map(Decimal, [24, 15, 10, 10, 15, 10]))
    assert sum(c.points for c in result.components) == result.score
    assert result.recommendation == Recommendation.ATTEMPT
    assert result.reasons == (RecommendationReason.ATTEMPT_THRESHOLD_MET,)
    assert result.policy == policy()


@pytest.mark.parametrize(
    ("reward", "expected_score", "recommendation"),
    [
        ("25", "60.00", Recommendation.REJECT),
        ("100", "84.00", Recommendation.ATTEMPT),
        ("150", "100.00", Recommendation.ATTEMPT),
    ],
)
def test_nonpositive_net_gate_and_economic_clamp(
    reward: str, expected_score: str, recommendation: Recommendation
) -> None:
    result = ScoringAssessment(economics(reward), signals(), policy())
    assert result.score == Decimal(expected_score)
    assert result.recommendation == recommendation


@pytest.mark.parametrize(
    "name", ["risk", "competition", "deadline", "ai_suitability", "historical_performance"]
)
def test_unknown_signals_remain_unknown_and_cap_recommendation(name: str) -> None:
    result = ScoringAssessment(
        economics("1000"), replace(signals(), **{name: signal(None)}), policy()
    )
    component = next(c for c in result.components if c.name == name)
    assert component.estimate.value is None and component.desirability is None
    assert component.points == 0
    assert result.recommendation == Recommendation.WATCH
    assert result.reasons == (RecommendationReason.UNKNOWN_SIGNALS,)


@pytest.mark.parametrize(
    ("score", "recommendation", "reason"),
    [
        ("59.99", Recommendation.WATCH, RecommendationReason.BELOW_RECOMMEND_THRESHOLD),
        ("60", Recommendation.RECOMMEND, RecommendationReason.RECOMMEND_THRESHOLD_MET),
        ("79.99", Recommendation.RECOMMEND, RecommendationReason.RECOMMEND_THRESHOLD_MET),
        ("80", Recommendation.ATTEMPT, RecommendationReason.ATTEMPT_THRESHOLD_MET),
    ],
)
def test_recommendation_thresholds(
    score: str, recommendation: Recommendation, reason: RecommendationReason
) -> None:
    # Economics gets all 40 points; other five desirabilities contribute equal shares.
    desirability = (Decimal(score) - 40) / 60
    good = SignalEstimate(desirability, "Known test desirability")
    bad = SignalEstimate(1 - desirability, "Known inverse desirability")
    result = ScoringAssessment(
        economics("150"), ScoringSignals(bad, bad, good, good, good), policy()
    )
    assert result.score == Decimal(score)
    assert result.recommendation == recommendation
    assert result.reasons == (reason,)


def test_all_unfavorable_signals_and_minimum_score() -> None:
    bad = ScoringSignals(signal("1"), signal("1"), signal("0"), signal("0"), signal("0"))
    assert ScoringAssessment(economics("0"), bad, policy()).score == 0
    assert ScoringAssessment(economics(), bad, policy()).recommendation == Recommendation.WATCH


def test_configurable_weights_target_thresholds_and_currency() -> None:
    configured = replace(
        policy(), weights=ScoringWeights(*(Decimal(v) for v in (50, 10, 10, 10, 10, 10)))
    )
    result = ScoringAssessment(economics(), signals(), configured)
    assert result.score == 80
    assert (
        ScoringAssessment(
            economics(), signals(), replace(policy(), net_value_target=money("200"))
        ).score
        == 72
    )
    assert (
        ScoringAssessment(
            economics(), signals(), replace(policy(), attempt_threshold=Decimal(90))
        ).recommendation
        == Recommendation.RECOMMEND
    )
    with pytest.raises(DomainError):
        ScoringAssessment(
            economics(), signals(), replace(policy(), net_value_target=money("100", "EUR"))
        )


@pytest.mark.parametrize("target", ["0", "-1"])
def test_positive_target(target: str) -> None:
    with pytest.raises(DomainError):
        replace(policy(), net_value_target=money(target))


@pytest.mark.parametrize("weight", ["0", "-1", "NaN", "Infinity", "41"])
def test_invalid_weights(weight: str) -> None:
    with pytest.raises(DomainError):
        ScoringWeights(economics=Decimal(weight))


@pytest.mark.parametrize(
    ("recommend", "attempt"),
    [("80", "60"), ("60", "60"), ("-1", "80"), ("60", "101"), ("NaN", "80")],
)
def test_invalid_thresholds(recommend: str, attempt: str) -> None:
    with pytest.raises(DomainError):
        replace(
            policy(), recommend_threshold=Decimal(recommend), attempt_threshold=Decimal(attempt)
        )


def test_calculation_independent_of_global_decimal_precision_and_traps() -> None:
    baseline = ScoringAssessment(economics("12.345", "0.1234"), signals(), policy())
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert ScoringAssessment(economics("12.345", "0.1234"), signals(), policy()) == baseline


def test_score_half_even_rounding_once() -> None:
    inputs = replace(economics().inputs, predicted_success_probability=signal("1"))
    for net, score in [("60.0125", "84.00"), ("60.0375", "84.02")]:
        assessment = EconomicAssessment(Reward(money(str(Decimal(net) + 20))), inputs)
        assert ScoringAssessment(assessment, signals(), policy()).score == Decimal(score)


def test_aggregate_binds_assessments_and_never_creates_revenue(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    eligible = lifecycle[OpportunityState.ELIGIBLE]
    evaluated = eligible.evaluate(economics())
    result = ScoringAssessment(economics(), signals(), policy())
    scored = evaluated.assign_score(result)
    assert scored.economic_assessment == economics()
    assert scored.scoring_assessment == result
    assert scored.verified_revenue == money("0")
    assert lifecycle[OpportunityState.ACCEPTED].verified_revenue == money("0")
    with pytest.raises(DomainError):
        eligible.evaluate(economics("101"))
    with pytest.raises(DomainError):
        evaluated.assign_score(ScoringAssessment(economics("101"), signals(), policy()))
    for invalid in [Decimal("100.01"), Decimal("-1")]:
        with pytest.raises(DomainError):
            evaluated.assign_score(invalid)
