"""Explicit, idempotent initialization of a single operator budget ledger."""

from dataclasses import dataclass

from agentmine.application.contracts.opportunities import DiscoveryRequest, OpportunityBatch
from agentmine.application.contracts.records import BudgetCommit, Versioned
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.operator import OperatorReadRepository
from agentmine.application.ports.repositories import CostLedgerRepository, OpportunityRepository
from agentmine.application.use_cases.context import load
from agentmine.application.use_cases.planning import DiscoverOpportunities, NormalizeOpportunity
from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class InitializeWorkspace:
    ledger: CostLedgerRepository

    def execute(
        self,
        reference: Reference,
        policy: BudgetPolicy,
        mode: OperatingMode = OperatingMode.FULL,
    ) -> Versioned[Budget]:
        requested = Budget(policy, mode)
        current = self.ledger.get(reference)
        if current is not None:
            if current.value.policy == policy and current.value.requested_mode == mode:
                return current
            raise PortError(
                PortErrorCode.CONFLICT,
                "workspace_initialize",
                "Ledger already initialized with different policy or requested mode",
            )
        return self.ledger.commit(BudgetCommit(reference, requested, None, None))


@dataclass(frozen=True, slots=True)
class WorkspaceLoadResult:
    batch: OpportunityBatch
    opportunities: tuple[Opportunity, ...]
    normalized_count: int


@dataclass(frozen=True, slots=True)
class LoadWorkspaceOpportunities:
    workspace: OperatorReadRepository
    discover: DiscoverOpportunities
    normalize: NormalizeOpportunity
    opportunities: OpportunityRepository

    def execute(
        self, ledger_reference: Reference, request: DiscoveryRequest
    ) -> WorkspaceLoadResult:
        # Fail before any source I/O if the workspace is missing/ambiguous.
        self.workspace.read(ledger_reference)
        batch = self.discover.execute(request)
        retained: dict[Reference, Opportunity] = {}
        normalized_count = 0
        for observation in batch.observations:
            reference = observation.opportunity.reference
            current = load(self.opportunities, reference).value
            if current.state == OpportunityState.DISCOVERED:
                current = self.normalize.execute(reference)
                normalized_count += 1
            retained[reference] = current
        return WorkspaceLoadResult(batch, tuple(retained.values()), normalized_count)
