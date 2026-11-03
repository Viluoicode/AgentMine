"""Bounded immutable requests and application-owned diagnostic contracts."""

import pytest

from agentmine.application.contracts.discovery_diagnostics import DiscoveryDiagnosticRequest
from agentmine.domain.values import Reference


def ref(number: int) -> Reference:
    return Reference("raw:sha256:" + f"{number:064x}")


@pytest.mark.parametrize("details", [(ref(2),) * 2, (ref(1),), tuple(ref(i) for i in range(2, 53))])
def test_selection_is_bounded_and_unambiguous(details: tuple[Reference, ...]) -> None:
    with pytest.raises(ValueError):
        DiscoveryDiagnosticRequest(ref(1), details)


@pytest.mark.parametrize("value", ["raw:missing", "https://untrusted", "raw:sha256:" + "Z" * 64])
def test_only_exact_capture_digests(value: str) -> None:
    with pytest.raises(ValueError):
        DiscoveryDiagnosticRequest(Reference(value))


def test_application_rejects_reader_returning_different_selection() -> None:
    from datetime import UTC, datetime

    from agentmine.application.contracts.discovery_diagnostics import (
        CaptureEvidence,
        DiagnosticError,
        DiagnosticReason,
        DiscoveryDiagnosticReport,
    )
    from agentmine.application.use_cases.discovery_diagnostics import InspectDiscoveryDiagnostics

    class WrongSelection:
        def inspect(self, request: DiscoveryDiagnosticRequest) -> DiscoveryDiagnosticReport:
            return DiscoveryDiagnosticReport(
                CaptureEvidence(ref(2), datetime(2026, 11, 2, tzinfo=UTC)), (), 1, 0, 0, ()
            )

    with pytest.raises(DiagnosticError) as caught:
        InspectDiscoveryDiagnostics(WrongSelection()).execute(DiscoveryDiagnosticRequest(ref(1)))
    assert caught.value.reason == DiagnosticReason.READER_MISMATCH
