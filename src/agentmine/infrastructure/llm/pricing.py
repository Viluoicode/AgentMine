"""Explicit operator-supplied tariff; usage-derived cost is not a verified invoice."""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from agentmine.domain.money import Money
from agentmine.infrastructure.llm.operations import object_value


@dataclass(frozen=True, slots=True)
class TokenPricing:
    input_per_million: Money
    output_per_million: Money
    evidence: str

    def __post_init__(self) -> None:
        self.input_per_million.require_nonnegative("input_rate")
        self.output_per_million.require_nonnegative("output_rate")
        self.input_per_million.require_same_currency(self.output_per_million)
        if not self.evidence.strip():
            raise ValueError("Tariff source/version required")

    def cost(self, input_tokens: int, output_tokens: int) -> Money:
        if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
            raise ValueError("Nonnegative integer usage required")
        input_exp = self.input_per_million.amount.as_tuple().exponent
        output_exp = self.output_per_million.amount.as_tuple().exponent
        assert isinstance(input_exp, int) and isinstance(output_exp, int)
        with localcontext() as context:
            context.prec = (
                max(
                    len(self.input_per_million.amount.as_tuple().digits) + len(str(input_tokens)),
                    len(self.output_per_million.amount.as_tuple().digits) + len(str(output_tokens)),
                )
                + abs(input_exp)
                + abs(output_exp)
                + 10
            )
            return Money(
                (
                    self.input_per_million.amount * input_tokens
                    + self.output_per_million.amount * output_tokens
                )
                / Decimal(1_000_000),
                self.input_per_million.currency,
            )


@dataclass(frozen=True, slots=True)
class BedrockSettings:
    model_id: str
    region: str
    pricing: TokenPricing
    estimated_input_tokens: int
    max_output_tokens: int

    def __post_init__(self) -> None:
        if not self.model_id.strip() or not self.region.strip():
            raise ValueError("Explicit model and region required")
        if any(
            type(n) is not int or not 1 <= n <= 1_000_000
            for n in (self.estimated_input_tokens, self.max_output_tokens)
        ):
            raise ValueError("Positive bounded token settings required")
        if self.estimate().amount <= 0:
            raise ValueError("Bedrock requires a positive estimated tariff")

    def estimate(self) -> Money:
        return self.pricing.cost(self.estimated_input_tokens, self.max_output_tokens)


def measured_tokens(response: dict[str, object]) -> tuple[int, int] | None:
    raw = response.get("usage")
    if not isinstance(raw, dict):
        return None
    usage = object_value(raw)
    # Cache or unrecognized billing dimensions cannot be priced with two flat rates.
    if set(usage) - {
        "inputTokens",
        "outputTokens",
        "totalTokens",
        "cacheReadInputTokens",
        "cacheWriteInputTokens",
        "cacheDetails",
    }:
        return None
    if usage.get("cacheDetails") not in (None, []):
        return None
    for name in ("cacheReadInputTokens", "cacheWriteInputTokens"):
        if name in usage and (type(usage[name]) is not int or usage[name] != 0):
            return None
    values = [usage.get(name) for name in ("inputTokens", "outputTokens", "totalTokens")]
    if any(type(value) is not int or value < 0 for value in values if isinstance(value, int)):
        return None
    if not all(type(value) is int for value in values):
        return None
    incoming, outgoing, total = values
    assert isinstance(incoming, int) and isinstance(outgoing, int) and isinstance(total, int)
    if incoming + outgoing != total:
        return None
    return incoming, outgoing
