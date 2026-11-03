"""Immutable selected-evidence diagnostics, never opportunity lifecycle authority."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.values import Reference, require_aware_timestamp


class DiagnosticClassification(StrEnum):
    EMPTY_FEED = "EMPTY_FEED"
    NORMALIZED = "NORMALIZED"
    QUARANTINED = "QUARANTINED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    UNKNOWN_COVERAGE = "UNKNOWN_COVERAGE"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    INVALID_CAPTURE = "INVALID_CAPTURE"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"


class DiagnosticReason(StrEnum):
    ARCHIVE_UNAVAILABLE = "ARCHIVE_UNAVAILABLE"
    ARCHIVE_REQUIRES_RECONCILIATION = "ARCHIVE_REQUIRES_RECONCILIATION"
    MISSING_CAPTURE = "MISSING_CAPTURE"
    CAPTURE_INVALID = "CAPTURE_INVALID"
    ROUTE_MISMATCH = "ROUTE_MISMATCH"
    LIST_IDENTITY_CONFLICT = "LIST_IDENTITY_CONFLICT"
    DETAIL_IDENTITY_CONFLICT = "DETAIL_IDENTITY_CONFLICT"
    MULTIPLE_DETAILS = "MULTIPLE_DETAILS"
    DETAIL_NOT_PROVIDED = "DETAIL_NOT_PROVIDED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    READER_MISMATCH = "READER_MISMATCH"


class DiagnosticError(PortError):
    def __init__(
        self,
        reason: DiagnosticReason,
        classification: DiagnosticClassification = DiagnosticClassification.INVALID_CAPTURE,
        capture: "CaptureEvidence | None" = None,
    ) -> None:
        self.reason = reason
        self.capture = capture
        self.classification = classification
        code = (
            PortErrorCode.UNAVAILABLE
            if reason == DiagnosticReason.ARCHIVE_UNAVAILABLE
            else PortErrorCode.INVALID_RESPONSE
        )
        super().__init__(code, "discovery_diagnostics", reason.value)


def capture_reference(value: Reference) -> None:
    if (
        not isinstance(value, Reference)
        or re.fullmatch(r"raw:sha256:[0-9a-f]{64}", value.value) is None
    ):
        raise ValueError("Exact raw capture digest required")


@dataclass(frozen=True, slots=True)
class DiscoveryDiagnosticRequest:
    list_capture: Reference
    detail_captures: tuple[Reference, ...] = ()

    def __post_init__(self) -> None:
        capture_reference(self.list_capture)
        if not isinstance(self.detail_captures, tuple) or len(self.detail_captures) > 50:
            raise ValueError("At most 50 explicitly selected detail captures required")
        for reference in self.detail_captures:
            capture_reference(reference)
        if (
            len(set(self.detail_captures)) != len(self.detail_captures)
            or self.list_capture in self.detail_captures
        ):
            raise ValueError("Distinct list and detail references required")


@dataclass(frozen=True, slots=True)
class CaptureEvidence:
    reference: Reference
    observed_at: datetime

    def __post_init__(self) -> None:
        capture_reference(self.reference)
        require_aware_timestamp(self.observed_at)


@dataclass(frozen=True, slots=True)
class CaptureProblem:
    reference: Reference
    classification: DiagnosticClassification
    reason: DiagnosticReason
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        capture_reference(self.reference)
        if self.classification not in (
            DiagnosticClassification.INCOMPLETE_EVIDENCE,
            DiagnosticClassification.INVALID_CAPTURE,
            DiagnosticClassification.IDENTITY_CONFLICT,
        ) or not isinstance(self.reason, DiagnosticReason):
            raise ValueError("Typed capture problem required")
        if self.observed_at is not None:
            require_aware_timestamp(self.observed_at)


@dataclass(frozen=True, slots=True)
class ListingDiagnostic:
    listing_id: str
    slug: str
    detail_captures: tuple[CaptureEvidence, ...]
    classification: DiagnosticClassification
    issue_codes: tuple[str, ...] = ()
    reasons: tuple[DiagnosticReason, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.listing_id, self.slug):
            if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value) is None:
                raise ValueError("Bounded source identity required")
        if (
            not isinstance(self.detail_captures, tuple)
            or any(not isinstance(item, CaptureEvidence) for item in self.detail_captures)
            or len({item.reference for item in self.detail_captures}) != len(self.detail_captures)
        ):
            raise ValueError("Immutable distinct capture evidence required")
        if self.classification not in (
            DiagnosticClassification.NORMALIZED,
            DiagnosticClassification.QUARANTINED,
            DiagnosticClassification.INCOMPLETE_EVIDENCE,
            DiagnosticClassification.INVALID_CAPTURE,
            DiagnosticClassification.IDENTITY_CONFLICT,
        ):
            raise ValueError("Listing disposition required")
        if (
            not isinstance(self.issue_codes, tuple)
            or len(self.issue_codes) > 20
            or any(
                not isinstance(code, str) or re.fullmatch(r"[A-Z_]{1,100}", code) is None
                for code in self.issue_codes
            )
            or len(set(self.issue_codes)) != len(self.issue_codes)
        ):
            raise ValueError("Bounded machine-readable issues required")
        if not isinstance(self.reasons, tuple) or any(
            not isinstance(reason, DiagnosticReason) for reason in self.reasons
        ):
            raise ValueError("Typed evidence reasons required")
        if self.classification in (
            DiagnosticClassification.NORMALIZED,
            DiagnosticClassification.QUARANTINED,
        ):
            if (
                len(self.detail_captures) != 1
                or self.reasons
                or (
                    bool(self.issue_codes)
                    != (self.classification == DiagnosticClassification.QUARANTINED)
                )
            ):
                raise ValueError("Disposition must agree with normalization evidence")
        elif not self.reasons or self.issue_codes:
            raise ValueError("Unresolved evidence must not invent normalization issues")


@dataclass(frozen=True, slots=True)
class DiscoveryDiagnosticReport:
    list_capture: CaptureEvidence
    selected_details: tuple[Reference, ...]
    requested_limit: int
    raw_row_count: int
    duplicate_row_count: int
    items: tuple[ListingDiagnostic, ...]
    problems: tuple[CaptureProblem, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.list_capture, CaptureEvidence):
            raise ValueError("List evidence required")
        DiscoveryDiagnosticRequest(self.list_capture.reference, self.selected_details)
        if type(self.requested_limit) is not int or not 1 <= self.requested_limit <= 50:
            raise ValueError("Known bounded request required")
        if (
            type(self.raw_row_count) is not int
            or not 0 <= self.raw_row_count <= self.requested_limit
        ):
            raise ValueError("Bounded raw row count required")
        if type(self.duplicate_row_count) is not int or self.duplicate_row_count < 0:
            raise ValueError("Known duplicate count required")
        if not isinstance(self.items, tuple) or any(
            not isinstance(item, ListingDiagnostic) for item in self.items
        ):
            raise ValueError("Immutable listing inventory required")
        if len({item.listing_id for item in self.items}) != len(self.items) or len(
            {item.slug for item in self.items}
        ) != len(self.items):
            raise ValueError("Unambiguous listing identities required")
        if self.raw_row_count != len(self.items) + self.duplicate_row_count:
            raise ValueError("Raw and unique counts must reconcile")
        if not isinstance(self.problems, tuple) or any(
            not isinstance(item, CaptureProblem) for item in self.problems
        ):
            raise ValueError("Immutable capture problems required")
        used = tuple(e.reference for item in self.items for e in item.detail_captures)
        if len(set(used)) != len(used) or not set(used) <= set(self.selected_details):
            raise ValueError("Evidence must be selected and cannot have multiple owners")
        problem_refs = {problem.reference for problem in self.problems}
        if not problem_refs <= set(self.selected_details) or set(used) | problem_refs != set(
            self.selected_details
        ):
            raise ValueError("Every selected detail needs evidence or a typed problem")

    @property
    def unique_listing_count(self) -> int:
        return len(self.items)

    @property
    def normalized_count(self) -> int:
        return sum(
            item.classification == DiagnosticClassification.NORMALIZED for item in self.items
        )

    @property
    def quarantined_count(self) -> int:
        return sum(
            item.classification == DiagnosticClassification.QUARANTINED for item in self.items
        )

    @property
    def unresolved_count(self) -> int:
        return len(self.items) - self.normalized_count - self.quarantined_count

    @property
    def recomputed_with_current_normalizer(self) -> bool:
        return True

    @property
    def classifications(self) -> tuple[DiagnosticClassification, ...]:
        values = {item.classification for item in self.items} | {
            p.classification for p in self.problems
        }
        if self.raw_row_count == 0:
            values.add(DiagnosticClassification.EMPTY_FEED)
        if self.unresolved_count or self.problems:
            values.add(DiagnosticClassification.INCOMPLETE_EVIDENCE)
        if values.intersection(
            (DiagnosticClassification.INVALID_CAPTURE, DiagnosticClassification.IDENTITY_CONFLICT)
        ):
            # The list was inspected successfully; selected detail evidence failed.
            # This is NOT a reconstructed historical API failure.
            values.add(DiagnosticClassification.PARTIAL_FAILURE)
        values.add(DiagnosticClassification.UNKNOWN_COVERAGE)
        return tuple(value for value in DiagnosticClassification if value in values)
