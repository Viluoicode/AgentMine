import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.bootstrap.superteam_smoke import main
from agentmine.infrastructure.marketplaces.superteam_http import ReadFailure, SuperteamReadError


class OfflineHTTP:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty
        self.routes: list[str] = []

    def get(self, route: str) -> bytes:
        self.routes.append(route)
        fixtures = Path(__file__).parents[1] / "contract/fixtures/superteam"
        if "live?" in route:
            return b"[]" if self.empty else (fixtures / "live.json").read_bytes()
        return (fixtures / "detail.json").read_bytes()


def test_live_flag_is_mandatory_even_with_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENTMINE_SUPERTEAM_API_KEY", "sk_never_sent")
    archive = tmp_path / "raw.db"
    with patch("agentmine.bootstrap.superteam_smoke.SuperteamHTTP") as factory:
        with pytest.raises(SystemExit) as error:
            main(["--archive", str(archive)])
        assert error.value.code == 2
        factory.assert_not_called()
    assert not archive.exists()
    assert "sk_never_sent" not in capsys.readouterr().err


def test_missing_key_does_not_create_archive_or_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AGENTMINE_SUPERTEAM_API_KEY", raising=False)
    archive = tmp_path / "raw.db"
    with patch("agentmine.bootstrap.superteam_smoke.SuperteamHTTP") as factory:
        assert main(["--live", "--archive", str(archive)]) == 2
        factory.assert_not_called()
    assert not archive.exists()
    assert json.loads(capsys.readouterr().out)["reason"] == "missing_api_key"


def test_invalid_key_is_safe_and_never_opens_a_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENTMINE_SUPERTEAM_API_KEY", "private-invalid-key")
    archive = tmp_path / "raw.db"
    with patch("http.client.HTTPSConnection") as factory:
        assert main(["--live", "--archive", str(archive)]) == 2
        factory.assert_not_called()
    assert "private-invalid-key" not in capsys.readouterr().out
    assert not archive.exists()


@pytest.mark.parametrize("limit", ["0", "51", "-1"])
def test_invalid_window_fails_before_network(tmp_path: Path, limit: str) -> None:
    with patch("agentmine.bootstrap.superteam_smoke.SuperteamHTTP") as factory:
        with pytest.raises(SystemExit) as error:
            main(["--live", "--limit", limit, "--archive", str(tmp_path / "raw.db")])
        assert error.value.code == 2
        factory.assert_not_called()


@pytest.mark.parametrize("empty", [True, False])
def test_smoke_uses_offline_fixture_in_tests_and_outputs_only_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    empty: bool,
) -> None:
    monkeypatch.setenv("AGENTMINE_SUPERTEAM_API_KEY", "sk_test_only")
    transport = OfflineHTTP(empty=empty)
    archive = tmp_path / "evidence" / "raw.db"
    with patch("agentmine.bootstrap.superteam_smoke.SuperteamHTTP", return_value=transport):
        assert main(["--live", "--archive", str(archive)]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "read_succeeded"
    assert report["normalized"] == (0 if empty else 1)
    assert report["pagination_unverified"] is (not empty)
    assert "sk_test_only" not in output and "Synthetic research brief" not in output
    assert archive.exists()
    assert len(transport.routes) == (1 if empty else 2)


@pytest.mark.parametrize(
    "failure,expected",
    [
        (SuperteamReadError(ReadFailure.AUTHENTICATION, 401), "authentication"),
        (SuperteamReadError(ReadFailure.RATE_LIMITED, 429), "rate_limited"),
        (
            PortError(PortErrorCode.INVALID_RESPONSE, "discovery", "private raw data"),
            "invalid_response",
        ),
    ],
)
def test_smoke_failure_has_nonzero_exit_and_safe_machine_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: PortError,
    expected: str,
) -> None:
    monkeypatch.setenv("AGENTMINE_SUPERTEAM_API_KEY", "sk_test_only")
    with patch("agentmine.bootstrap.superteam_smoke.SuperteamHTTP") as factory:
        factory.return_value.get.side_effect = failure
        assert main(["--live", "--archive", str(tmp_path / "raw.db")]) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["reason"] == expected
    assert "private" not in output and "sk_test_only" not in output
