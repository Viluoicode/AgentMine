"""Immutable report/capture attachment only; no credit, verifier or financial writes."""

from typing import Protocol

from agentmine.application.contracts.payment_evidence import (
    PaymentEvidenceView,
    PaymentObservation,
    PaymentReport,
)
from agentmine.domain.values import Reference


class PaymentEvidenceRepository(Protocol):
    def prepare(self, report: PaymentReport) -> PaymentReport:
        """Atomically freeze exact retained context before capture; no monetary owner."""
        ...

    def attach(self, observation: PaymentObservation) -> None:
        """Attach matching B1 provisional capture under the original context only."""
        ...

    def inspect(self, reference: Reference) -> PaymentEvidenceView:
        """Consistent historical read and missing/conflict/recovery projection."""
        ...
