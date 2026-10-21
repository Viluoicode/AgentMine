"""Explicit offline configuration; missing live refresh can never authorize approval."""

from agentmine.application.contracts.opportunities import (
    DiscoveryRequest,
    OpportunityBatch,
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.errors import PortError, PortErrorCode


class DisabledOpportunitySource:
    def discover(self, request: DiscoveryRequest) -> OpportunityBatch:
        raise PortError(PortErrorCode.UNSUPPORTED, "discover", "Source not configured")

    def refresh(self, request: RefreshOpportunityRequest) -> OpportunityStatus:
        raise PortError(
            PortErrorCode.UNSUPPORTED,
            "refresh",
            "Approval requires a configured fresh source; offline refresh disabled",
        )
