"""Read only explicitly selected retained evidence; no source calls or ingestion."""

from typing import Protocol

from agentmine.application.contracts.discovery_diagnostics import (
    DiscoveryDiagnosticReport,
    DiscoveryDiagnosticRequest,
)


class DiscoveryDiagnosticsReader(Protocol):
    def inspect(self, request: DiscoveryDiagnosticRequest) -> DiscoveryDiagnosticReport: ...
