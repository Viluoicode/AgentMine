"""Structured failures for domain invariants; no external dependencies."""

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_VALUE = "invalid_value"
    CURRENCY_MISMATCH = "currency_mismatch"
    INVALID_TRANSITION = "invalid_transition"
    BUDGET_EXCEEDED = "budget_exceeded"
    DUPLICATE_REFERENCE = "duplicate_reference"
    EXECUTION_FORBIDDEN = "execution_forbidden"
    EVIDENCE_MISMATCH = "evidence_mismatch"
    REVALIDATION_REQUIRED = "revalidation_required"


class DomainError(ValueError):
    """A predictable failure with a machine-readable code and field."""

    def __init__(self, code: ErrorCode, field: str, message: str) -> None:
        self.code = code
        self.field = field
        super().__init__(message)
