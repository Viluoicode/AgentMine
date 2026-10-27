"""Local financial-control consistency boundary; no provider or dispatch capability."""

from typing import Protocol

from agentmine.application.contracts.budget_control import (
    BudgetControlSnapshot,
    BudgetPolicyApplication,
    BudgetPolicyChange,
    BudgetPolicyChangeReceipt,
)
from agentmine.domain.values import Reference


class BudgetControlRepository(Protocol):
    def read(self, ledger: Reference) -> BudgetControlSnapshot:
        """Consistent sole-ledger/run/wait evidence; missing/corrupt authority fails closed."""
        ...

    def get_change(self, reference: Reference) -> BudgetPolicyChange | None: ...
    def get_receipt(self, reference: Reference) -> BudgetPolicyChangeReceipt | None: ...

    def prepare(self, change: BudgetPolicyChange) -> BudgetPolicyChange:
        """Immutable insert against exact ledger revision/policy; identical retry is readback."""
        ...

    def apply(self, command: BudgetPolicyApplication) -> BudgetPolicyChangeReceipt:
        """CAS ledger + existing audit + approved decision + receipt in ONE transaction.

        Verify retained change and full snapshot. Original receipt wins identical
        retry even after later policy changes. Never mutate costs/commitment history.
        """
        ...
