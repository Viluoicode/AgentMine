"""Bounded metadata-only JSON for offline selected-evidence diagnostics."""

import argparse
import json
from typing import TextIO

from agentmine.application.contracts.discovery_diagnostics import (
    DiagnosticClassification as C,
)
from agentmine.application.contracts.discovery_diagnostics import (
    DiagnosticError,
    DiscoveryDiagnosticReport,
    DiscoveryDiagnosticRequest,
)
from agentmine.application.errors import PortError
from agentmine.application.use_cases.discovery_diagnostics import InspectDiscoveryDiagnostics
from agentmine.domain.errors import DomainError
from agentmine.domain.values import Reference


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Offline discovery diagnostics; no live API or ingestion"
    )
    result.add_argument(
        "--archive", required=True, help="Existing local raw SQLite archive (read-only)"
    )
    result.add_argument("--list-capture", required=True, help="Exact retained raw:sha256 reference")
    result.add_argument(
        "--detail-capture",
        action="append",
        default=[],
        help="Explicit detail reference; at most 50",
    )
    return result


def report_view(report: DiscoveryDiagnosticReport) -> dict[str, object]:
    return {
        "status": "diagnostic_complete"
        if not report.unresolved_count and not report.problems
        else "diagnostic_incomplete",
        "classifications": [value.value for value in report.classifications],
        "coverage": C.UNKNOWN_COVERAGE.value,
        "api_run_outcome": "UNKNOWN",
        "association_basis": "EXPLICIT_SELECTED_CAPTURES_NOT_A_DISCOVERY_RUN",
        "recomputed_with_current_normalizer": report.recomputed_with_current_normalizer,
        "diagnostic_version": "offline-discovery-v1",
        "normalized_meaning": "Normalization compatibility only; not inventory or eligibility",
        "partial_failure_scope": "Selected evidence inspection only; not historical "
        "network failure",
        "opportunities_ingested": False,
        "external_actions": False,
        "list_capture": {
            "reference": report.list_capture.reference.value,
            "observed_at": report.list_capture.observed_at.isoformat(),
            "requested_limit": report.requested_limit,
        },
        "counts": {
            "raw_row_count": report.raw_row_count,
            "unique_listing_count": report.unique_listing_count,
            "duplicate_row_count": report.duplicate_row_count,
            "normalized_count": report.normalized_count,
            "quarantined_count": report.quarantined_count,
            "unresolved_count": report.unresolved_count,
        },
        "items": [
            {
                "listing_id": item.listing_id,
                "slug": item.slug,
                "classification": item.classification.value,
                "detail_captures": [
                    {
                        "reference": evidence.reference.value,
                        "observed_at": evidence.observed_at.isoformat(),
                    }
                    for evidence in item.detail_captures
                ],
                "issue_codes": list(item.issue_codes),
                "reasons": [reason.value for reason in item.reasons],
            }
            for item in report.items
        ],
        "capture_problems": [
            {
                "reference": problem.reference.value,
                "observed_at": None
                if problem.observed_at is None
                else problem.observed_at.isoformat(),
                "classification": problem.classification.value,
                "reason": problem.reason.value,
            }
            for problem in report.problems
        ],
    }


def run_diagnostics(
    args: argparse.Namespace, use_case: InspectDiscoveryDiagnostics, output: TextIO
) -> int:
    failure_capture: dict[str, str] | None = None
    try:
        request = DiscoveryDiagnosticRequest(
            Reference(args.list_capture),
            tuple(Reference(value) for value in args.detail_capture),
        )
        report = use_case.execute(request)
        print(json.dumps(report_view(report), ensure_ascii=True), file=output)
        return 0 if not report.unresolved_count and not report.problems else 1
    except DiagnosticError as error:
        classification, reason = error.classification.value, error.reason.value
        if error.capture is not None:
            failure_capture = {
                "reference": error.capture.reference.value,
                "observed_at": error.capture.observed_at.isoformat(),
            }
    except (PortError, DomainError, ValueError):
        classification, reason = C.INVALID_CAPTURE.value, "INVALID_DIAGNOSTIC_INPUT_OR_RESPONSE"
    print(
        json.dumps(
            {
                "status": "failed",
                "classifications": [classification, C.UNKNOWN_COVERAGE.value],
                "coverage": C.UNKNOWN_COVERAGE.value,
                "api_run_outcome": "UNKNOWN",
                "reason": reason,
                "counts": None,
                "list_capture": failure_capture,
                "opportunities_ingested": False,
                "external_actions": False,
            }
        ),
        file=output,
    )
    return 1
