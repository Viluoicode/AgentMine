"""Narrow durable inspection ownership and atomic report application."""

from typing import Protocol

from agentmine.application.contracts.operational_qa import QAApplicationBinding, QACompletion
from agentmine.application.contracts.qa import QAInspection
from agentmine.domain.values import Reference


class OperationalQARepository(Protocol):
    def get_binding(self, inspection: Reference) -> QAApplicationBinding | None: ...
    def for_execution(self, execution: Reference) -> QAApplicationBinding | None: ...
    def get_inspection(self, inspection: Reference) -> QAInspection | None: ...
    def applied(self, inspection: Reference) -> bool: ...
    def claim(self, binding: QAApplicationBinding, inspection: QAInspection) -> bool:
        """Atomically bind one inspection per deliverable/version with Opportunity CAS checks.

        Same frozen binding/inspection is readback; changed identity conflicts.
        Never adopt unbound legacy reports or inspections.
        """
        ...

    def complete(self, completion: QACompletion) -> bool:
        """Require retained report and exact original Opportunity snapshot.

        Atomically save lifecycle QA result, apply Domain transition and completion
        marker. Original completed retries are readback, never a later state write.
        Report persistence is deliberately earlier and recoverable on its own.
        """
        ...
