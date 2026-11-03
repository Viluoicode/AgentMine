"""Explicit raw-capture projection; no live source, ingestion or run reconstruction."""

import re
import sqlite3
from dataclasses import dataclass

from agentmine.application.contracts.discovery_diagnostics import (
    CaptureEvidence,
    CaptureProblem,
    DiagnosticError,
    DiscoveryDiagnosticReport,
    DiscoveryDiagnosticRequest,
    ListingDiagnostic,
)
from agentmine.application.contracts.discovery_diagnostics import (
    DiagnosticClassification as C,
)
from agentmine.application.contracts.discovery_diagnostics import (
    DiagnosticReason as R,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.errors import DomainError
from agentmine.infrastructure.marketplaces.raw_archive import RawArchive, RawCapture
from agentmine.infrastructure.marketplaces.superteam_normalization import (
    decode_json,
    identity,
    listing_object,
    normalize_detail,
)


def bounded_identity(value: object) -> tuple[str, str]:
    result = identity(listing_object(value))
    if any(len(part) > 256 for part in result):
        raise DiagnosticError(R.CAPTURE_INVALID)
    return result


@dataclass(frozen=True, slots=True)
class ArchiveDiscoveryDiagnostics:
    archive: RawArchive

    def inspect(self, request: DiscoveryDiagnosticRequest) -> DiscoveryDiagnosticReport:
        try:
            with self.archive.reading() as connection:
                listing = self.archive.read_capture(connection, request.list_capture)
                if listing is None:
                    raise DiagnosticError(R.MISSING_CAPTURE, C.INCOMPLETE_EVIDENCE)
                try:
                    return self._inspect(connection, request, listing)
                except DiagnosticError as error:
                    error.capture = CaptureEvidence(listing.reference, listing.observed_at)
                    raise
                except PortError:
                    raise DiagnosticError(
                        R.CAPTURE_INVALID,
                        capture=CaptureEvidence(listing.reference, listing.observed_at),
                    ) from None
        except DiagnosticError:
            raise
        except PortError as error:
            if error.code == PortErrorCode.UNSUPPORTED:
                raise DiagnosticError(
                    R.ARCHIVE_REQUIRES_RECONCILIATION, C.INCOMPLETE_EVIDENCE
                ) from None
            reason = (
                R.ARCHIVE_UNAVAILABLE
                if error.code == PortErrorCode.UNAVAILABLE
                else R.CAPTURE_INVALID
            )
            raise DiagnosticError(reason) from None

    def _inspect(
        self,
        connection: sqlite3.Connection,
        request: DiscoveryDiagnosticRequest,
        listing: RawCapture,
    ) -> DiscoveryDiagnosticReport:
        route = re.fullmatch(
            r"/api/agents/listings/live\?take=([1-9]|[1-4][0-9]|50)", listing.route
        )
        if route is None:
            raise DiagnosticError(R.ROUTE_MISMATCH)
        take = int(route[1])
        rows = decode_json(listing.body)
        if not isinstance(rows, list) or len(rows) > take:
            raise DiagnosticError(R.CAPTURE_INVALID)
        identities: dict[str, str] = {}
        slugs: dict[str, str] = {}
        for row in rows:
            item_id, slug = bounded_identity(row)
            if (item_id in identities and identities[item_id] != slug) or (
                slug in slugs and slugs[slug] != item_id
            ):
                raise DiagnosticError(R.LIST_IDENTITY_CONFLICT, C.IDENTITY_CONFLICT)
            identities[item_id], slugs[slug] = slug, item_id
        grouped: dict[str, list[RawCapture]] = {slug: [] for slug in slugs}
        problems: list[CaptureProblem] = []
        size = len(listing.body)
        for reference in request.detail_captures:
            try:
                detail = self.archive.read_capture(connection, reference)
            except PortError as error:
                if error.code != PortErrorCode.INVALID_RESPONSE:
                    raise
                problems.append(CaptureProblem(reference, C.INVALID_CAPTURE, R.CAPTURE_INVALID))
                continue
            if detail is None:
                problems.append(CaptureProblem(reference, C.INCOMPLETE_EVIDENCE, R.MISSING_CAPTURE))
                continue
            size += len(detail.body)
            if size > 8_000_000:
                raise DiagnosticError(R.LIMIT_EXCEEDED)
            match = re.fullmatch(
                r"/api/agents/listings/details/([A-Za-z0-9_-]{1,256})", detail.route
            )
            if match is None or match[1] not in slugs:
                problems.append(
                    CaptureProblem(
                        reference, C.IDENTITY_CONFLICT, R.ROUTE_MISMATCH, detail.observed_at
                    )
                )
                continue
            grouped[match[1]].append(detail)
        items = tuple(
            self._item(item_id, slug, grouped[slug]) for item_id, slug in identities.items()
        )
        return DiscoveryDiagnosticReport(
            CaptureEvidence(listing.reference, listing.observed_at),
            request.detail_captures,
            take,
            len(rows),
            len(rows) - len(items),
            items,
            tuple(problems),
        )

    def _item(self, item_id: str, slug: str, details: list[RawCapture]) -> ListingDiagnostic:
        evidence = tuple(CaptureEvidence(item.reference, item.observed_at) for item in details)
        if not details:
            return ListingDiagnostic(
                item_id, slug, (), C.INCOMPLETE_EVIDENCE, reasons=(R.DETAIL_NOT_PROVIDED,)
            )
        if len(details) > 1:
            return ListingDiagnostic(
                item_id, slug, evidence, C.IDENTITY_CONFLICT, reasons=(R.MULTIPLE_DETAILS,)
            )
        detail = details[0]
        try:
            value = listing_object(decode_json(detail.body))
            if bounded_identity(value) != (item_id, slug):
                return ListingDiagnostic(
                    item_id,
                    slug,
                    evidence,
                    C.IDENTITY_CONFLICT,
                    reasons=(R.DETAIL_IDENTITY_CONFLICT,),
                )
            result = normalize_detail(value, detail.observed_at, detail.reference)
        except (PortError, DomainError, ValueError, RecursionError):
            return ListingDiagnostic(
                item_id, slug, evidence, C.INVALID_CAPTURE, reasons=(R.CAPTURE_INVALID,)
            )
        return ListingDiagnostic(
            item_id,
            slug,
            evidence,
            C.NORMALIZED if result.observation is not None else C.QUARANTINED,
            tuple(issue.value for issue in result.issues),
        )
