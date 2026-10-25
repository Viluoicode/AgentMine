import json
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from fakes import FakeOpportunities

from agentmine.application.contracts.opportunities import (
    DiscoveryRequest,
    RefreshOpportunityRequest,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.services import OpportunitySource
from agentmine.application.use_cases import DiscoverOpportunities, NormalizeOpportunity
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.infrastructure.marketplaces.deferred import (
    AlgoraOpportunitySource,
    OpireOpportunitySource,
)
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive
from agentmine.infrastructure.marketplaces.superteam import SuperteamOpportunitySource
from agentmine.infrastructure.marketplaces.superteam_http import ReadFailure, SuperteamReadError
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository


def test_review_source_version_is_content_bound_not_capture_time(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    payload = json.loads(transport.detail)
    request = RefreshOpportunityRequest(
        Reference("superteam:" + payload["id"]), Reference("superteam:" + payload["slug"])
    )
    first = adapter.refresh(request)
    assert first.terms_reference == Reference(
        "source:sha256:" + sha256(transport.detail).hexdigest()
    )
    assert first.requirements is not None
    assert adapter.refresh(request).terms_reference == first.terms_reference
    payload["requirements"] = "Changed manual channel requirements"
    transport.detail = json.dumps(payload).encode()
    changed = adapter.refresh(request)
    assert changed.terms_reference != first.terms_reference
    assert changed.requirements != first.requirements


class FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 14, tzinfo=UTC)


class OfflineTransport:
    def __init__(self) -> None:
        fixtures = Path(__file__).parent / "fixtures/superteam"
        self.live = (fixtures / "live.json").read_bytes()
        self.detail = (fixtures / "detail.json").read_bytes()
        self.routes: list[str] = []
        self.detail_failure: PortError | None = None
        self.details_by_slug: dict[str, bytes] = {}

    def get(self, route: str) -> bytes:
        self.routes.append(route)
        if route.startswith("/api/agents/listings/live?"):
            return self.live
        assert route.startswith("/api/agents/listings/details/")
        if self.detail_failure is not None:
            raise self.detail_failure
        return self.details_by_slug.get(route.rsplit("/", 1)[-1], self.detail)


def source(tmp_path: Path) -> tuple[SuperteamOpportunitySource, OfflineTransport]:
    transport = OfflineTransport()
    return SuperteamOpportunitySource(
        transport, RawArchive(tmp_path / "raw.db"), FrozenClock()
    ), transport


def test_read_adapter_can_feed_existing_application_and_preserve_exact_raw(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    report = adapter.inspect(DiscoveryRequest(20))
    assert len(report.batch.observations) == 1 and report.batch.continuation is None
    listing_raw = adapter.archive.get(report.list_capture)
    assert listing_raw is not None and listing_raw.body == transport.live
    raw = adapter.archive.get(report.items[0].raw_reference)
    assert raw is not None and raw.body == transport.detail
    port: OpportunitySource = adapter
    repository = FakeOpportunities()
    DiscoverOpportunities(port, repository, FrozenClock()).execute(DiscoveryRequest(20))
    reference = report.batch.observations[0].opportunity.reference
    normalized = NormalizeOpportunity(repository).execute(reference)
    assert normalized.state == OpportunityState.NORMALIZED
    refreshed = port.refresh(RefreshOpportunityRequest(reference, report.items[0].source_reference))
    assert refreshed.is_open is True
    assert refreshed.observed_at == FrozenClock().now()


def test_quarantine_is_visible_and_unknown_metadata_survives(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    data = json.loads(transport.detail)
    data.update(token="USDC", type="bounty", future={"secret_meaning": [1, 2]})
    transport.detail = json.dumps(data).encode()
    report = adapter.inspect(DiscoveryRequest(1))
    assert report.batch.observations == ()
    assert report.batch.continuation is not None
    assert len(report.items[0].issues) == 2
    raw = adapter.archive.get(report.items[0].raw_reference)
    assert raw is not None and raw.body == transport.detail
    with pytest.raises(PortError) as error:
        adapter.discover(DiscoveryRequest(1, report.batch.continuation))
    assert error.value.code == PortErrorCode.UNSUPPORTED
    assert len(transport.routes) == 2


def test_limit_is_capped_and_empty_response_is_not_an_error(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    transport.live = b"[]"
    batch = adapter.discover(DiscoveryRequest(100))
    assert batch.observations == () and batch.continuation is None
    assert transport.routes == ["/api/agents/listings/live?take=50"]


@pytest.mark.parametrize("body", [b"{}", b'{"items":[]}', b"not-json", b"[null]"])
def test_invalid_envelopes_are_archived_before_failure(tmp_path: Path, body: bytes) -> None:
    adapter, transport = source(tmp_path)
    transport.live = body
    with pytest.raises(PortError):
        adapter.discover(DiscoveryRequest(10))
    with sqlite3.connect(adapter.archive.path) as connection:
        assert connection.execute("SELECT body FROM marketplace_captures").fetchone()[0] == body


def test_saved_duplicate_ids_fetch_detail_once_and_preserve_raw_count(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    transport.live = (
        Path(__file__).parent / "fixtures/superteam/live_duplicates.json"
    ).read_bytes()
    report = adapter.inspect(DiscoveryRequest(2))
    assert len(report.batch.observations) == 1
    assert report.duplicate_count == 1
    assert report.batch.continuation is not None  # Full raw page, not a false exhaustion signal.
    assert len(transport.routes) == 2
    raw = adapter.archive.get(report.list_capture)
    assert raw is not None and raw.body == transport.live


def test_page_larger_than_requested_fails(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    transport.live = json.dumps(json.loads(transport.live) * 2).encode()
    with pytest.raises(PortError):
        adapter.discover(DiscoveryRequest(1))


@pytest.mark.parametrize("field", ["id", "slug"])
def test_mismatched_detail_identity_never_reaches_application(tmp_path: Path, field: str) -> None:
    adapter, transport = source(tmp_path)
    data = json.loads(transport.detail)
    data[field] = "different"
    transport.detail = json.dumps(data).encode()
    with pytest.raises(PortError):
        adapter.discover(DiscoveryRequest(10))


def test_wrong_source_refresh_makes_no_read(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    with pytest.raises(PortError):
        adapter.refresh(
            RefreshOpportunityRequest(Reference("other:id"), Reference("superteam:slug"))
        )
    assert transport.routes == []


@pytest.mark.parametrize("adapter", [AlgoraOpportunitySource(), OpireOpportunitySource()])
def test_unverified_adapters_fail_with_no_empty_success(adapter: OpportunitySource) -> None:
    with pytest.raises(PortError) as discovery:
        adapter.discover(DiscoveryRequest(1))
    with pytest.raises(PortError) as refresh:
        adapter.refresh(RefreshOpportunityRequest(Reference("id"), Reference("source")))
    assert discovery.value.code == refresh.value.code == PortErrorCode.UNSUPPORTED


@pytest.mark.parametrize("changed_field", ["id", "slug"])
def test_ambiguous_id_slug_mapping_fails_before_detail(tmp_path: Path, changed_field: str) -> None:
    adapter, transport = source(tmp_path)
    entries = json.loads(transport.live) * 2
    entries[1] = entries[1] | {changed_field: "other"}
    transport.live = json.dumps(entries).encode()
    with pytest.raises(PortError) as error:
        adapter.discover(DiscoveryRequest(10))
    assert error.value.code == PortErrorCode.CONFLICT
    assert len(transport.routes) == 1


def test_repeat_ingestion_after_reopen_preserves_original_and_advanced_state(
    tmp_path: Path,
) -> None:
    adapter, transport = source(tmp_path)
    path = tmp_path / "opportunities.db"
    repository = SQLiteOpportunityRepository(SQLiteDatabase(path))
    first = DiscoverOpportunities(adapter, repository, FrozenClock()).execute(DiscoveryRequest(20))
    reference = first.observations[0].opportunity.reference
    NormalizeOpportunity(repository).execute(reference)
    original = repository.get_observation(reference)
    snapshot = repository.get(reference)
    # Same ID, changed title/content and new raw capture must not insert or downgrade.
    transport.detail = transport.detail.replace(b"Synthetic research brief", b"Revised brief")
    reopened = SQLiteOpportunityRepository(SQLiteDatabase(path))
    reopened_source = SuperteamOpportunitySource(
        transport, RawArchive(adapter.archive.path), FrozenClock()
    )
    repeat = DiscoverOpportunities(reopened_source, reopened, FrozenClock()).execute(
        DiscoveryRequest(20)
    )
    assert repeat.observations[0].opportunity.reference == reference
    assert repeat.observations[0].opportunity.title == "Revised brief"
    assert reopened.get(reference) == snapshot
    assert reopened.get_observation(reference) == original
    assert len(reopened.list_by_status(OpportunityState.NORMALIZED)) == 1
    assert reopened.list_by_status(OpportunityState.DISCOVERED) == ()
    assert reopened.verified_revenue("SOL").amount == 0
    with sqlite3.connect(adapter.archive.path) as connection:
        bodies = [row[0] for row in connection.execute("SELECT body FROM marketplace_captures")]
    assert transport.detail in bodies
    assert any(b"Synthetic research brief" in body for body in bodies)


def test_slug_rename_conflicts_without_duplicate_or_loss(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    repository = SQLiteOpportunityRepository(SQLiteDatabase(tmp_path / "opportunities.db"))
    workflow = DiscoverOpportunities(adapter, repository, FrozenClock())
    first = workflow.execute(DiscoveryRequest(20))
    reference = first.observations[0].opportunity.reference
    before = repository.get(reference)
    transport.live = transport.live.replace(b"fixture-research-project", b"renamed")
    transport.detail = transport.detail.replace(b"fixture-research-project", b"renamed")
    with pytest.raises(PortError) as error:
        workflow.execute(DiscoveryRequest(20))
    assert error.value.code == PortErrorCode.CONFLICT
    assert repository.get(reference) == before
    assert len(repository.list_by_status(OpportunityState.DISCOVERED)) == 1


@pytest.mark.parametrize(
    "reason,status",
    [
        (ReadFailure.AUTHENTICATION, 401),
        (ReadFailure.ACCESS_DENIED, 403),
        (ReadFailure.NOT_FOUND, 404),
        (ReadFailure.RATE_LIMITED, 429),
        (ReadFailure.HTTP, 503),
        (ReadFailure.NETWORK, None),
    ],
)
def test_detail_failure_is_not_empty_success_or_partial_ingestion(
    tmp_path: Path,
    reason: ReadFailure,
    status: int | None,
) -> None:
    adapter, transport = source(tmp_path)
    transport.detail_failure = SuperteamReadError(reason, status)
    repository = FakeOpportunities()
    with pytest.raises(SuperteamReadError) as error:
        DiscoverOpportunities(adapter, repository, FrozenClock()).execute(DiscoveryRequest(20))
    assert error.value.reason == reason
    assert repository.get(Reference("superteam:fixture-project-1")) is None
    assert len(transport.routes) == 2
    with sqlite3.connect(adapter.archive.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM marketplace_captures").fetchone()[0] == 1


def test_bad_detail_is_archived_and_database_is_unchanged(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    transport.detail = b"<html>unexpected sign-in</html>"
    repository = FakeOpportunities()
    with pytest.raises(PortError) as error:
        DiscoverOpportunities(adapter, repository, FrozenClock()).execute(DiscoveryRequest(20))
    assert error.value.code == PortErrorCode.INVALID_RESPONSE
    assert repository.get(Reference("superteam:fixture-project-1")) is None
    with sqlite3.connect(adapter.archive.path) as connection:
        assert (transport.detail,) in connection.execute(
            "SELECT body FROM marketplace_captures"
        ).fetchall()


@pytest.mark.parametrize("policy", [None, "NEW_POLICY", "HUMAN_ONLY"])
def test_unconfirmed_agent_permission_is_quarantined_and_refresh_is_blocked(
    tmp_path: Path,
    policy: object,
) -> None:
    adapter, transport = source(tmp_path)
    payload = json.loads(transport.detail)
    payload["agentAccess"] = policy
    transport.detail = json.dumps(payload).encode()
    report = adapter.inspect(DiscoveryRequest(20))
    assert report.batch.observations == ()
    assert report.items[0].issues
    with pytest.raises(PortError) as error:
        adapter.refresh(
            RefreshOpportunityRequest(
                Reference("superteam:fixture-project-1"),
                Reference("superteam:fixture-research-project"),
            )
        )
    assert error.value.code == PortErrorCode.UNSUPPORTED


def test_archive_failure_prevents_normalization_and_ingestion(tmp_path: Path) -> None:
    transport = OfflineTransport()
    adapter = SuperteamOpportunitySource(
        transport, RawArchive(tmp_path / "missing" / "raw.db"), FrozenClock()
    )
    repository = FakeOpportunities()
    with pytest.raises(PortError) as error:
        DiscoverOpportunities(adapter, repository, FrozenClock()).execute(DiscoveryRequest(20))
    assert error.value.code == PortErrorCode.UNAVAILABLE
    assert len(transport.routes) == 1
    assert repository.get(Reference("superteam:fixture-project-1")) is None


def test_same_title_different_external_ids_are_distinct_opportunities(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    entries = json.loads(transport.live)
    entries.append(entries[0] | {"id": "fixture-project-2", "slug": "second-project"})
    transport.live = json.dumps(entries).encode()
    transport.details_by_slug["second-project"] = transport.detail.replace(
        b"fixture-project-1", b"fixture-project-2"
    ).replace(b"fixture-research-project", b"second-project")
    repository = SQLiteOpportunityRepository(SQLiteDatabase(tmp_path / "opportunities.db"))
    batch = DiscoverOpportunities(adapter, repository, FrozenClock()).execute(DiscoveryRequest(20))
    assert len(batch.observations) == 2
    assert len(repository.list_by_status(OpportunityState.DISCOVERED)) == 2
    assert len({item.opportunity.title for item in batch.observations}) == 1
    assert len({item.opportunity.reference for item in batch.observations}) == 2
    assert len(transport.routes) == 3
