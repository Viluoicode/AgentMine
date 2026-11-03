"""Synthetic selected captures, never live marketplace evidence."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentmine.application.contracts.discovery_diagnostics import (
    DiagnosticClassification as C,
)
from agentmine.application.contracts.discovery_diagnostics import (
    DiagnosticError,
    DiagnosticReason,
    DiscoveryDiagnosticReport,
    DiscoveryDiagnosticRequest,
)
from agentmine.application.use_cases.discovery_diagnostics import InspectDiscoveryDiagnostics
from agentmine.domain.values import Reference
from agentmine.infrastructure.marketplaces.discovery_diagnostics import ArchiveDiscoveryDiagnostics
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive, RawCapture

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)


def detail(identity: str = "one", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": identity,
        "slug": identity,
        "title": "Synthetic approved input",
        "description": "Synthetic data task",
        "type": "project",
        "compensationType": "fixed",
        "token": "SOL",
        "rewardAmount": 1,
        "status": "OPEN",
        "agentAccess": "AGENT_ALLOWED",
        "deadline": "2026-12-01T00:00:00Z",
    }
    return value | changes


def capture(value: object, slug: str = "one", at: datetime = NOW) -> RawCapture:
    return RawCapture("/api/agents/listings/details/" + slug, at, json.dumps(value).encode())


def inspect(
    tmp_path: Path, rows: object, *details: RawCapture
) -> tuple[DiscoveryDiagnosticReport, RawArchive, RawCapture]:
    store = RawArchive(tmp_path / "raw.sqlite3")
    listing = RawCapture("/api/agents/listings/live?take=20", NOW, json.dumps(rows).encode())
    store.save(listing)
    for item in details:
        store.save(item)
    request = DiscoveryDiagnosticRequest(
        listing.reference, tuple(item.reference for item in details)
    )
    report = InspectDiscoveryDiagnostics(ArchiveDiscoveryDiagnostics(store)).execute(request)
    return report, store, listing


def test_empty_is_observed_window_only(tmp_path: Path) -> None:
    report, _, _ = inspect(tmp_path, [])
    assert set(report.classifications) == {C.EMPTY_FEED, C.UNKNOWN_COVERAGE}
    assert report.raw_row_count == report.unique_listing_count == 0
    assert report.normalized_count == report.quarantined_count == report.unresolved_count == 0


@pytest.mark.parametrize(
    "changes,issues",
    [
        ({}, ()),
        ({"type": "bounty"}, ("REWARD_MODEL_UNSUPPORTED",)),
        ({"token": "USDC"}, ("REWARD_ASSET_UNSUPPORTED",)),
        (
            {"type": "bounty", "token": "USDC"},
            ("REWARD_MODEL_UNSUPPORTED", "REWARD_ASSET_UNSUPPORTED"),
        ),
    ],
)
def test_current_normalizer_is_reused(
    tmp_path: Path, changes: dict[str, object], issues: tuple[str, ...]
) -> None:
    source = capture(detail() | changes)
    report, _, listing = inspect(tmp_path, [{"id": "one", "slug": "one"}], source)
    item = report.items[0]
    assert item.listing_id == item.slug == "one"
    assert item.classification == (C.QUARANTINED if issues else C.NORMALIZED)
    assert item.issue_codes == issues
    assert item.detail_captures[0].reference == source.reference
    assert report.list_capture.reference == listing.reference
    assert report.recomputed_with_current_normalizer is True
    assert C.UNKNOWN_COVERAGE in report.classifications


def test_mixed_and_duplicate_counts(tmp_path: Path) -> None:
    rows = [{"id": "one", "slug": "one"}] * 2 + [{"id": "two", "slug": "two"}]
    report, _, _ = inspect(
        tmp_path, rows, capture(detail()), capture(detail("two", token="USDC"), "two")
    )
    assert (report.raw_row_count, report.unique_listing_count, report.duplicate_row_count) == (
        3,
        2,
        1,
    )
    assert (report.normalized_count, report.quarantined_count, report.unresolved_count) == (1, 1, 0)


@pytest.mark.parametrize(
    "other",
    [
        {"id": "one", "slug": "two"},
        {"id": "two", "slug": "one"},
    ],
)
def test_conflicting_list_identity_has_no_guessed_counts(
    tmp_path: Path, other: dict[str, object]
) -> None:
    with pytest.raises(DiagnosticError) as caught:
        inspect(tmp_path, [{"id": "one", "slug": "one"}, other])
    assert caught.value.classification == C.IDENTITY_CONFLICT


def test_missing_detail_is_not_network_failure(tmp_path: Path) -> None:
    report, _, _ = inspect(tmp_path, [{"id": "one", "slug": "one"}])
    assert report.items[0].classification == C.INCOMPLETE_EVIDENCE
    assert report.items[0].reasons == (DiagnosticReason.DETAIL_NOT_PROVIDED,)
    assert C.PARTIAL_FAILURE not in report.classifications


def test_malformed_detail_retains_good_results(tmp_path: Path) -> None:
    bad = RawCapture("/api/agents/listings/details/two", NOW, b"{bad")
    report, _, _ = inspect(
        tmp_path,
        [{"id": "one", "slug": "one"}, {"id": "two", "slug": "two"}],
        capture(detail()),
        bad,
    )
    assert report.normalized_count == 1 and report.unresolved_count == 1
    assert {C.PARTIAL_FAILURE, C.INVALID_CAPTURE, C.UNKNOWN_COVERAGE} <= set(report.classifications)
    assert report.items[1].detail_captures[0].reference == bad.reference


@pytest.mark.parametrize("source", [capture(detail("wrong")), capture(detail(), "wrong")])
def test_unrelated_detail_cannot_normalize(tmp_path: Path, source: RawCapture) -> None:
    report, _, _ = inspect(tmp_path, [{"id": "one", "slug": "one"}], source)
    assert report.normalized_count == 0
    assert C.IDENTITY_CONFLICT in report.classifications


def test_distinct_times_and_repeated_inspection(tmp_path: Path) -> None:
    source = capture(detail(), at=NOW - timedelta(days=3))
    report, store, listing = inspect(tmp_path, [{"id": "one", "slug": "one"}], source)
    assert report.list_capture.observed_at == NOW
    assert report.items[0].detail_captures[0].observed_at == source.observed_at
    request = DiscoveryDiagnosticRequest(listing.reference, (source.reference,))
    assert (
        InspectDiscoveryDiagnostics(ArchiveDiscoveryDiagnostics(store)).execute(request) == report
    )


def test_two_selected_details_never_choose_latest(tmp_path: Path) -> None:
    report, _, _ = inspect(
        tmp_path,
        [{"id": "one", "slug": "one"}],
        capture(detail()),
        capture(detail(), at=NOW + timedelta(seconds=1)),
    )
    assert report.items[0].classification == C.IDENTITY_CONFLICT
    assert len(report.items[0].detail_captures) == 2


def test_corrupt_detail_digest_and_missing_capture(tmp_path: Path) -> None:
    report, store, listing = inspect(tmp_path, [{"id": "one", "slug": "one"}], capture(detail()))
    reference = report.items[0].detail_captures[0].reference
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE marketplace_captures SET body=? WHERE id=?", (b"{}", reference.value)
        )
    reader = InspectDiscoveryDiagnostics(ArchiveDiscoveryDiagnostics(store))
    damaged = reader.execute(DiscoveryDiagnosticRequest(listing.reference, (reference,)))
    assert C.INVALID_CAPTURE in damaged.classifications and damaged.normalized_count == 0
    missing = reader.execute(
        DiscoveryDiagnosticRequest(listing.reference, (Reference("raw:sha256:" + "0" * 64),))
    )
    assert C.INCOMPLETE_EVIDENCE in missing.classifications
    assert C.PARTIAL_FAILURE not in missing.classifications


@pytest.mark.parametrize("rows", [{"message": "not an array"}, [{"id": "one"}], [True]])
def test_invalid_list_cannot_be_empty(tmp_path: Path, rows: object) -> None:
    with pytest.raises(DiagnosticError) as caught:
        inspect(tmp_path, rows)
    assert caught.value.classification == C.INVALID_CAPTURE


@pytest.mark.parametrize("damage", ["body", "route", "time"])
def test_list_digest_corruption_is_fatal_not_empty(tmp_path: Path, damage: str) -> None:
    _, store, listing = inspect(tmp_path, [])
    with sqlite3.connect(store.path) as connection:
        if damage == "body":
            connection.execute("UPDATE marketplace_captures SET body=?", (b"{}",))
        elif damage == "route":
            connection.execute("UPDATE marketplace_captures SET route=?", ("/wrong",))
        else:
            connection.execute("UPDATE marketplace_captures SET observed_at=?", ("2026-11-02",))
    with pytest.raises(DiagnosticError):
        InspectDiscoveryDiagnostics(ArchiveDiscoveryDiagnostics(store)).execute(
            DiscoveryDiagnosticRequest(listing.reference)
        )


def test_only_explicitly_selected_detail_is_used(tmp_path: Path) -> None:
    _, store, listing = inspect(tmp_path, [{"id": "one", "slug": "one"}], capture(detail()))
    result = InspectDiscoveryDiagnostics(ArchiveDiscoveryDiagnostics(store)).execute(
        DiscoveryDiagnosticRequest(listing.reference)
    )
    assert result.normalized_count == 0
    assert result.items[0].reasons == (DiagnosticReason.DETAIL_NOT_PROVIDED,)


def test_oversized_capture_is_rejected_before_normalization(tmp_path: Path) -> None:
    store = RawArchive(tmp_path / "raw.sqlite3")
    listing = RawCapture("/api/agents/listings/live?take=1", NOW, b" " * 2_000_001)
    store.save(listing)
    with pytest.raises(DiagnosticError):
        InspectDiscoveryDiagnostics(ArchiveDiscoveryDiagnostics(store)).execute(
            DiscoveryDiagnosticRequest(listing.reference)
        )


def test_total_selected_byte_limit_is_explicit_failure(tmp_path: Path) -> None:
    rows = [{"id": str(index), "slug": str(index)} for index in range(5)]
    details = tuple(
        RawCapture("/api/agents/listings/details/" + str(index), NOW, b" " * 1_700_000)
        for index in range(5)
    )
    with pytest.raises(DiagnosticError) as caught:
        inspect(tmp_path, rows, *details)
    assert caught.value.reason == DiagnosticReason.LIMIT_EXCEEDED


def test_raw_get_cannot_create_missing_archive(tmp_path: Path) -> None:
    store = RawArchive(tmp_path / "missing.sqlite3")
    from agentmine.application.errors import PortError

    with pytest.raises(PortError):
        store.get(Reference("raw:sha256:" + "0" * 64))
    assert not store.path.exists()


def test_existing_write_behavior_and_actual_read_only_connection(tmp_path: Path) -> None:
    store = RawArchive(tmp_path / "raw.sqlite3")
    value = capture(detail())
    assert store.save(value) == store.save(value) == value.reference
    with store.reading() as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM marketplace_captures")
    assert store.get(value.reference) == value
