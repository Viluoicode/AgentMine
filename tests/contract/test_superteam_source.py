import json
import sqlite3
from datetime import UTC, datetime
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


class FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 14, tzinfo=UTC)


class OfflineTransport:
    def __init__(self) -> None:
        fixtures = Path(__file__).parent / "fixtures/superteam"
        self.live = (fixtures / "live.json").read_bytes()
        self.detail = (fixtures / "detail.json").read_bytes()
        self.routes: list[str] = []

    def get(self, route: str) -> bytes:
        self.routes.append(route)
        if route.startswith("/api/agents/listings/live?"):
            return self.live
        assert route == "/api/agents/listings/details/fixture-research-project"
        return self.detail


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


def test_duplicate_listing_ids_fail_before_detail_fetch(tmp_path: Path) -> None:
    adapter, transport = source(tmp_path)
    transport.live = json.dumps(json.loads(transport.live) * 2).encode()
    with pytest.raises(PortError):
        adapter.discover(DiscoveryRequest(10))
    assert len(transport.routes) == 1


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
