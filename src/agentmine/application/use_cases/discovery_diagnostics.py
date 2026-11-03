"""Offline diagnostics do not grant eligibility, execution or financial authority."""

from dataclasses import dataclass, replace

from agentmine.application.contracts.discovery_diagnostics import (
    DiagnosticError,
    DiagnosticReason,
    DiscoveryDiagnosticReport,
    DiscoveryDiagnosticRequest,
)
from agentmine.application.ports.discovery_diagnostics import DiscoveryDiagnosticsReader


@dataclass(frozen=True, slots=True)
class InspectDiscoveryDiagnostics:
    reader: DiscoveryDiagnosticsReader

    def execute(self, request: DiscoveryDiagnosticRequest) -> DiscoveryDiagnosticReport:
        selected = replace(request)
        report = self.reader.inspect(selected)
        for item in report.items:
            replace(item)
        for problem in report.problems:
            replace(problem)
        replace(report)
        if (
            report.list_capture.reference != selected.list_capture
            or report.selected_details != selected.detail_captures
        ):
            raise DiagnosticError(DiagnosticReason.READER_MISMATCH)
        return report
