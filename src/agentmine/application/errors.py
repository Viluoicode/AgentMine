"""Provider-neutral failures translated by adapters at the application boundary."""

from enum import StrEnum


class PortErrorCode(StrEnum):
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    INVALID_RESPONSE = "invalid_response"
    CONFLICT = "conflict"
    OUTCOME_UNKNOWN = "outcome_unknown"


class PortError(Exception):
    """Safe business-facing failure; never expose credentials or raw provider payloads."""

    def __init__(self, code: PortErrorCode, operation: str, message: str) -> None:
        self.code = code
        self.operation = operation
        super().__init__(message)


class ApplicationErrorCode(StrEnum):
    NOT_FOUND = "not_found"
    EXPIRED = "expired"
    CLOSED = "closed"
    UNSUPPORTED_TASK = "unsupported_task"
    INVALID_STATE = "invalid_state"
    UNRESOLVED = "unresolved"


class ApplicationError(Exception):
    """Use-case precondition failure, separate from adapter and domain failures."""

    def __init__(self, code: ApplicationErrorCode, operation: str, message: str) -> None:
        self.code = code
        self.operation = operation
        super().__init__(message)
