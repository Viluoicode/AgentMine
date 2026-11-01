"""No real permitted manual channel is selected in the offline B2 checkpoint."""

from dataclasses import dataclass

from agentmine.application.contracts.manual_handoff import ChannelPermission, PermissionStatus
from agentmine.application.contracts.submission_context import SubmissionEnvelope
from agentmine.application.ports.services import Clock
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class UnverifiedManualChannel:
    clock: Clock

    def inspect(self, envelope: SubmissionEnvelope) -> ChannelPermission:
        return ChannelPermission(
            envelope.scope,
            self.clock.now(),
            PermissionStatus.UNVERIFIED,
            Reference("manual-channel:not-selected"),
        )
