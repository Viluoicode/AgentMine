import http.client
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive, RawCapture
from agentmine.infrastructure.marketplaces.superteam_http import SuperteamHTTP


def test_transport_fixed_host_get_and_secret_not_in_repr() -> None:
    transport = SuperteamHTTP("sk_test_only")
    assert "sk_test_only" not in repr(transport)
    with patch("http.client.HTTPSConnection", autospec=True) as factory:
        connection = factory.return_value
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b"[]"
        assert transport.get("/api/agents/listings/live?take=20") == b"[]"
        factory.assert_called_once_with("superteam.fun", timeout=15)
        connection.request.assert_called_once_with(
            "GET",
            "/api/agents/listings/live?take=20",
            headers={"Authorization": "Bearer sk_test_only", "Accept": "application/json"},
        )
        response.read.assert_called_once_with(2_000_001)
        connection.close.assert_called_once()


@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 403, 404, 429, 500, 503])
def test_http_failures_no_retry_redirect_or_body_leak(status: int) -> None:
    transport = SuperteamHTTP("sk_test_only")
    with patch("http.client.HTTPSConnection", autospec=True) as factory:
        connection = factory.return_value
        response = connection.getresponse.return_value
        response.status = status
        with pytest.raises(PortError) as error:
            transport.get("/api/agents/listings/details/slug")
        assert error.value.code == PortErrorCode.UNAVAILABLE
        assert "sk_test_only" not in str(error.value)
        assert str(status) in str(error.value)
        response.read.assert_not_called()
        connection.request.assert_called_once()
        connection.close.assert_called_once()


@pytest.mark.parametrize(
    "failure", [TimeoutError("private"), http.client.IncompleteRead(b"private")]
)
def test_network_errors_are_safe_and_connections_close(failure: Exception) -> None:
    with patch("http.client.HTTPSConnection", autospec=True) as factory:
        connection = factory.return_value
        connection.getresponse.side_effect = failure
        with pytest.raises(PortError) as error:
            SuperteamHTTP("sk_test_only").get("/api/agents/listings/live?take=1")
        assert "private" not in str(error.value)
        assert error.value.__suppress_context__
        connection.close.assert_called_once()


def test_oversized_response_is_not_parsed() -> None:
    with patch("http.client.HTTPSConnection", autospec=True) as factory:
        response = factory.return_value.getresponse.return_value
        response.status = 200
        response.read.return_value = b"1234"
        with pytest.raises(PortError) as error:
            SuperteamHTTP("sk_test_only", max_response_bytes=3).get(
                "/api/agents/listings/live?take=1"
            )
        assert error.value.code == PortErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "route",
    [
        "https://evil.example",
        "//evil.example",
        "/api/agents",
        "/api/agents/submissions/create",
        "/api/agents/listings/details/../status",
        "/api/agents/listings/details/%2e%2e",
        "/api/agents/listings/live?take=51",
        "/api/agents/listings/live?take=0",
        "/api/agents/listings/live?take=1&url=https://evil.example",
    ],
)
def test_no_unsupported_network_routes(route: str) -> None:
    with patch("http.client.HTTPSConnection", autospec=True) as factory:
        with pytest.raises(PortError):
            SuperteamHTTP("sk_test_only").get(route)
        factory.assert_not_called()


@pytest.mark.parametrize("secret", ["", "wrong", "sk_key\r\nOther: value"])
def test_invalid_key_is_not_reflected(secret: str) -> None:
    with pytest.raises(ValueError, match="agent key"):
        SuperteamHTTP(secret)


def test_archive_reopens_preserves_unknown_bytes_and_deduplicates(tmp_path: Path) -> None:
    path = tmp_path / "archive.db"
    capture = RawCapture(
        "/api/agents/listings/live?take=1",
        datetime(2026, 10, 14, tzinfo=UTC),
        b'{"future":{"arbitrary":[1,null,true]},"amount":1.123456789}',
    )
    archive = RawArchive(path)
    assert archive.save(capture) == archive.save(capture)
    assert RawArchive(path).get(capture.reference) == capture
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM marketplace_captures").fetchone()[0] == 1
        connection.execute("UPDATE marketplace_captures SET body = ?", (b"tampered",))
    with pytest.raises(PortError) as error:
        archive.get(capture.reference)
    assert error.value.code == PortErrorCode.INVALID_RESPONSE


def test_archive_error_is_structured(tmp_path: Path) -> None:
    archive = RawArchive(tmp_path / "missing" / "raw.db")
    capture = RawCapture(
        "/api/agents/listings/live?take=1", datetime(2026, 10, 14, tzinfo=UTC), b"[]"
    )
    with pytest.raises(PortError) as error:
        archive.save(capture)
    assert error.value.code == PortErrorCode.UNAVAILABLE
