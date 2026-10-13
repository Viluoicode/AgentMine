"""References and audit timestamps supplied explicitly by callers."""

from dataclasses import dataclass
from datetime import datetime

from agentmine.domain.errors import DomainError, ErrorCode


@dataclass(frozen=True, slots=True)
class Reference:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "reference", "Reference must be nonblank")


def require_reference(value: Reference, field: str) -> None:
    if not isinstance(value, Reference):
        raise DomainError(ErrorCode.INVALID_VALUE, field, "A nonblank Reference is required")


def require_aware_timestamp(value: datetime) -> None:
    """Audit timestamps must identify an instant, rather than local wall time."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainError(ErrorCode.INVALID_VALUE, "timestamp", "Timezone is required")
