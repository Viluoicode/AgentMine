"""Narrow offline manual-intent and permission-observation boundaries."""

from typing import Protocol

from agentmine.application.contracts.manual_handoff import (
    ChannelPermission,
    ManualHandoffClaim,
    ManualHandoffDraft,
    ManualHandoffView,
    ManualReceipt,
)
from agentmine.application.contracts.submission_context import SubmissionEnvelope
from agentmine.domain.values import Reference


class ManualChannelPermission(Protocol):
    def inspect(self, envelope: SubmissionEnvelope) -> ChannelPermission:
        """Read an offline fixture assertion; production defaults to unverified."""
        ...


class ManualHandoffRepository(Protocol):
    def prepare(self, draft: ManualHandoffDraft) -> ManualHandoffDraft: ...
    def inspect(self, reference: Reference) -> ManualHandoffView | None: ...
    def claim(self, claim: ManualHandoffClaim) -> ManualHandoffClaim:
        """Atomically claim exact request/version/account ownership and Opportunity revision."""
        ...

    def retain_receipt(self, receipt: ManualReceipt) -> ManualReceipt: ...
    def complete_receipt(self, receipt: ManualReceipt) -> None:
        """Atomically apply provisional Submission, attempt, lifecycle and completion marker."""
        ...
