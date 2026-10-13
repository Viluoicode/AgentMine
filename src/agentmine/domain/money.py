"""Exact monetary values with explicit currencies and no implicit conversion."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from agentmine.domain.errors import DomainError, ErrorCode


@dataclass(frozen=True, slots=True)
class Money:
    """Signed money; individual financial concepts impose nonnegative amounts."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise DomainError(ErrorCode.INVALID_VALUE, "amount", "Amount must be a finite Decimal")
        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isalpha()
            or self.currency != self.currency.upper()
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE,
                "currency",
                "Currency must be three uppercase ASCII letters",
            )

    def require_nonnegative(self, field: str) -> None:
        if self.amount < 0:
            raise DomainError(ErrorCode.INVALID_VALUE, field, "Amount cannot be negative")

    def require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise DomainError(ErrorCode.CURRENCY_MISMATCH, "currency", "Currencies must match")

    def __add__(self, other: Money) -> Money:
        self.require_same_currency(other)
        # Enough precision to align both finite coefficients without rounding.
        with localcontext() as context:
            context.prec = max(
                len(value.as_tuple().digits)
                + abs(int(value.as_tuple().exponent))
                + abs(value.adjusted())
                + 2
                for value in (self.amount, other.amount)
            )
            return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        return self + Money(other.amount.copy_negate(), other.currency)
