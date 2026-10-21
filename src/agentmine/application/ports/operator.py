"""Consistent complete workspace reads owned by the operator application."""

from typing import Protocol

from agentmine.application.contracts.dashboard import OperatorSnapshot
from agentmine.domain.values import Reference


class OperatorReadRepository(Protocol):
    def read(self, ledger_reference: Reference) -> OperatorSnapshot:
        """Read all opportunities and the sole budget atomically.

        Fail if missing or ambiguous; never report a truncated list as a total.
        No authorization, currency conversion or financial calculation belongs here.
        """
        ...
