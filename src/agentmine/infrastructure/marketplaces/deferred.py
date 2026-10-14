"""Disabled sources: no verified current external discovery contract, no I/O."""

from agentmine.application.contracts.opportunities import (
    DiscoveryRequest,
    OpportunityBatch,
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.errors import PortError, PortErrorCode


class AlgoraOpportunitySource:
    """Enable only after supported API and applicable access permission are verified."""

    def discover(self, request: DiscoveryRequest) -> OpportunityBatch:
        raise PortError(PortErrorCode.UNSUPPORTED, "discovery", "Algora contract/access unverified")

    def refresh(self, request: RefreshOpportunityRequest) -> OpportunityStatus:
        raise PortError(PortErrorCode.UNSUPPORTED, "refresh", "Algora contract/access unverified")


class OpireOpportunitySource:
    """Bot/PR documentation does not establish a programmatic discovery API."""

    def discover(self, request: DiscoveryRequest) -> OpportunityBatch:
        raise PortError(
            PortErrorCode.UNSUPPORTED, "discovery", "Opire discovery contract unverified"
        )

    def refresh(self, request: RefreshOpportunityRequest) -> OpportunityStatus:
        raise PortError(PortErrorCode.UNSUPPORTED, "refresh", "Opire discovery contract unverified")
