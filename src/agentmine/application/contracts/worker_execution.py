"""Commands and typed outcomes; these statuses do not replace Opportunity's lifecycle."""

from dataclasses import dataclass
from enum import StrEnum

from agentmine.application.contracts.data import DataResult
from agentmine.application.contracts.runtime import ExecutionBinding
from agentmine.domain.budget import AuthorizationDecision
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.opportunity import Opportunity


@dataclass(frozen=True, slots=True)
class ExecuteWorkerRequest:
    binding: ExecutionBinding
    expected_opportunity_revision: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.binding, ExecutionBinding)
            or type(self.expected_opportunity_revision) is not int
            or self.expected_opportunity_revision < 1
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE,
                "worker_request",
                "Binding and positive initial revision required",
            )


class WorkerExecutionStatus(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    RECOVERABLE = "recoverable"


class WorkerExecutionReason(StrEnum):
    NONE = "none"
    NOT_FOUND = "not_found"
    STALE_REVISION = "stale_revision"
    STATE_CONFLICT = "state_conflict"
    IDENTITY_CONFLICT = "identity_conflict"
    EVIDENCE_INVALID = "evidence_invalid"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_CHANGED = "source_changed"
    ELIGIBILITY_BLOCKED = "eligibility_blocked"
    APPROVAL_DENIED = "approval_denied"
    BUDGET_DENIED = "budget_denied"
    SPENDING_APPROVAL_REQUIRED = "spending_approval_required"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"
    PERSISTENCE_OUTCOME_UNKNOWN = "persistence_outcome_unknown"
    EXTERNAL_OUTCOME_UNKNOWN = "external_outcome_unknown"
    WORKER_FAILED = "worker_failed"
    REWORK_REQUIRED = "rework_required"


@dataclass(frozen=True, slots=True)
class WorkerExecutionOutcome:
    status: WorkerExecutionStatus
    reason: WorkerExecutionReason
    opportunity: Opportunity | None = None
    result: DataResult | None = None
    decision: AuthorizationDecision | None = None
