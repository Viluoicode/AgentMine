from decimal import Decimal, localcontext
from typing import cast

import pytest

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import Cost, CostCategory, ExpectedValue, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.values import Reference


@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_nonfinite_money_is_rejected(amount: str) -> None:
    with pytest.raises(DomainError) as error:
        Money(Decimal(amount), "USD")
    assert error.value.code == ErrorCode.INVALID_VALUE


def test_money_rejects_float() -> None:
    with pytest.raises(DomainError):
        Money(cast(Decimal, 0.1), "USD")


@pytest.mark.parametrize("currency", ["", "usd", "US", "USDD", "123", "ÜSD"])
def test_invalid_currency_format(currency: str) -> None:
    with pytest.raises(DomainError):
        Money(Decimal(0), currency)


def test_arithmetic_is_exact_even_with_low_ambient_precision() -> None:
    with localcontext() as context:
        context.prec = 2
        first = Money(Decimal("123456789.123456789"), "USD")
        second = Money(Decimal("0.000000001"), "USD")
        assert (first + second).amount == Decimal("123456789.123456790")
        assert (first - second).amount == Decimal("123456789.123456788")
        assert context.prec == 2


def test_signed_money_can_express_negative_net_value() -> None:
    assert (Money(Decimal(1), "USD") - Money(Decimal(2), "USD")).amount == -1


def test_currency_conversion_is_never_implicit() -> None:
    with pytest.raises(DomainError) as error:
        Money(Decimal(1), "USD") + Money(Decimal(1), "EUR")
    assert error.value.code == ErrorCode.CURRENCY_MISMATCH


@pytest.mark.parametrize("stage", list(RewardStage))
def test_negative_reward_is_rejected(stage: RewardStage) -> None:
    with pytest.raises(DomainError):
        Reward(Money(Decimal(-1), "USD"), stage, Reference("evidence"), Reference("submission"))


@pytest.mark.parametrize("category", list(CostCategory))
def test_negative_cost_is_rejected(category: CostCategory) -> None:
    with pytest.raises(DomainError):
        Cost(Reference("cost"), Money(Decimal(-1), "USD"), category)


def test_zero_reward_and_cost_are_valid() -> None:
    amount = Money(Decimal(0), "USD")
    assert Reward(amount).amount == amount
    assert Cost(Reference("cost"), amount, CostCategory.TOOL).amount == amount


@pytest.mark.parametrize("stage", [RewardStage.ACCEPTED, RewardStage.VERIFIED_PAYMENT])
def test_nonpotential_reward_requires_evidence_and_submission(stage: RewardStage) -> None:
    amount = Money(Decimal(1), "USD")
    with pytest.raises(DomainError):
        Reward(amount, stage)
    with pytest.raises(DomainError):
        Reward(amount, stage, Reference("evidence"))
    with pytest.raises(DomainError):
        Reward(amount, stage, None, Reference("submission"))


def test_potential_reward_cannot_claim_a_submission() -> None:
    with pytest.raises(DomainError):
        Reward(Money(Decimal(1), "USD"), submission_reference=Reference("submission"))


def test_expected_value_is_a_distinct_estimate() -> None:
    amount = Money(Decimal(1), "USD")
    with pytest.raises(DomainError):
        ExpectedValue(amount, " ")
    assert (
        ExpectedValue(Money(Decimal(-1), "USD"), "Negative expected net value").amount.amount == -1
    )


@pytest.mark.parametrize("value", ["", " ", "\n"])
def test_blank_references_are_rejected(value: str) -> None:
    with pytest.raises(DomainError):
        Reference(value)


def test_untyped_enum_values_are_rejected() -> None:
    amount = Money(Decimal(1), "USD")
    with pytest.raises(DomainError):
        Reward(amount, cast(RewardStage, "potential"))
    with pytest.raises(DomainError):
        Cost(Reference("cost"), amount, cast(CostCategory, "tool"))
