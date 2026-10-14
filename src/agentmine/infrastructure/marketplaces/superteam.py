"""Bounded Superteam discovery with raw evidence and no write capabilities."""

import logging
from dataclasses import dataclass

from agentmine.application.contracts.opportunities import (
    DiscoveryRequest,
    OpportunityBatch,
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.services import Clock
from agentmine.domain.eligibility import DeadlineKind
from agentmine.domain.values import Reference
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive, RawCapture
from agentmine.infrastructure.marketplaces.superteam_http import SuperteamTransport
from agentmine.infrastructure.marketplaces.superteam_normalization import (
    JSONObject,
    NormalizationResult,
    availability,
    decode_json,
    identity,
    invalid_response,
    listing_object,
    normalize_detail,
)


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    batch: OpportunityBatch
    list_capture: Reference
    items: tuple[NormalizationResult, ...]


@dataclass(frozen=True, slots=True)
class SuperteamOpportunitySource:
    transport: SuperteamTransport
    archive: RawArchive
    clock: Clock

    def _read(self, route: str) -> tuple[object, RawCapture]:
        body = self.transport.get(route)
        capture = RawCapture(route, self.clock.now(), body)
        self.archive.save(capture)
        return decode_json(body), capture

    def _detail(self, item_id: str, slug: str) -> tuple[JSONObject, RawCapture]:
        value, capture = self._read(f"/api/agents/listings/details/{slug}")
        detail = listing_object(value)
        if identity(detail) != (item_id, slug):
            raise invalid_response()
        return detail, capture

    def inspect(self, request: DiscoveryRequest) -> DiscoveryReport:
        if request.continuation is not None:
            raise PortError(
                PortErrorCode.UNSUPPORTED, "discovery", "Pagination contract unverified"
            )
        take = min(request.limit, 50)
        value, capture = self._read(f"/api/agents/listings/live?take={take}")
        if not isinstance(value, list) or len(value) > take:
            raise invalid_response()
        identities = [identity(listing_object(item)) for item in value]
        if len({item[0] for item in identities}) != len(identities) or len(
            {item[1] for item in identities}
        ) != len(identities):
            raise invalid_response()
        results = []
        for item_id, slug in identities:
            detail, raw = self._detail(item_id, slug)
            results.append(normalize_detail(detail, raw.observed_at, raw.reference))
        batch = OpportunityBatch(
            tuple(item.observation for item in results if item.observation is not None),
            Reference("superteam:pagination-unverified") if len(value) == take else None,
        )
        logging.getLogger(__name__).info(
            "marketplace_discovery",
            extra={
                "source": "superteam",
                "observed_count": len(results),
                "normalized_count": len(batch.observations),
                "normalization_issues": [issue.value for item in results for issue in item.issues],
            },
        )
        return DiscoveryReport(batch, capture.reference, tuple(results))

    def discover(self, request: DiscoveryRequest) -> OpportunityBatch:
        return self.inspect(request).batch

    def refresh(self, request: RefreshOpportunityRequest) -> OpportunityStatus:
        item_id = request.opportunity_reference.value.removeprefix("superteam:")
        slug = request.source_reference.value.removeprefix("superteam:")
        if not request.opportunity_reference.value.startswith(
            "superteam:"
        ) or not request.source_reference.value.startswith("superteam:"):
            raise PortError(PortErrorCode.UNSUPPORTED, "refresh", "Source reference mismatch")
        identity({"id": item_id, "slug": slug})
        detail, capture = self._detail(item_id, slug)
        is_open, deadline = availability(detail)
        return OpportunityStatus(
            request.opportunity_reference,
            request.source_reference,
            capture.observed_at,
            is_open,
            deadline.at,
            deadline.kind != DeadlineKind.UNKNOWN,
        )
