"""Only the documented Superteam GET routes, fixed HTTPS origin and no redirects."""

import http.client
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from agentmine.application.errors import PortError, PortErrorCode


class ReadFailure(StrEnum):
    AUTHENTICATION = "authentication"
    ACCESS_DENIED = "access_denied"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    REDIRECT = "redirect"
    HTTP = "http"
    NETWORK = "network"


class SuperteamReadError(PortError):
    """Safe infrastructure diagnostics; no response body, credentials or headers."""

    def __init__(self, reason: ReadFailure, http_status: int | None = None) -> None:
        self.reason = reason
        self.http_status = http_status
        super().__init__(
            PortErrorCode.UNAVAILABLE,
            "discovery",
            f"Source read failed: {reason.value} (HTTP {http_status})",
        )


def _http_failure(status: int) -> SuperteamReadError:
    reason = {
        401: ReadFailure.AUTHENTICATION,
        403: ReadFailure.ACCESS_DENIED,
        404: ReadFailure.NOT_FOUND,
        429: ReadFailure.RATE_LIMITED,
    }.get(status, ReadFailure.REDIRECT if 300 <= status < 400 else ReadFailure.HTTP)
    return SuperteamReadError(reason, status)


class SuperteamTransport(Protocol):
    """Infrastructure-only seam for offline contract tests, not a business port."""

    def get(self, route: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SuperteamHTTP:
    api_key: str = field(repr=False)
    timeout_seconds: float = 15
    max_response_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if not re.fullmatch(r"sk_[A-Za-z0-9_-]+", self.api_key):
            raise ValueError("A Superteam agent key is required")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("A positive finite timeout is required")
        if type(self.max_response_bytes) is not int or self.max_response_bytes < 1:
            raise ValueError("A positive response byte limit is required")

    def get(self, route: str) -> bytes:
        if not re.fullmatch(
            r"/api/agents/listings/(?:live\?take=(?:[1-9]|[1-4][0-9]|50)|"
            r"details/[A-Za-z0-9_-]+)",
            route,
        ):
            raise PortError(PortErrorCode.UNSUPPORTED, "discovery", "Unsupported read route")
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = http.client.HTTPSConnection("superteam.fun", timeout=self.timeout_seconds)
            connection.request(
                "GET",
                route,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise _http_failure(response.status)
            body = response.read(self.max_response_bytes + 1)
            if len(body) > self.max_response_bytes:
                raise PortError(
                    PortErrorCode.INVALID_RESPONSE, "discovery", "Source response too large"
                )
            return body
        except (OSError, http.client.HTTPException):
            raise SuperteamReadError(ReadFailure.NETWORK) from None
        finally:
            if connection is not None:
                connection.close()
