"""Supported AI assistance; recommendations never advance the domain lifecycle."""

from dataclasses import dataclass

from agentmine.domain.budget import BudgetAuthorization
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import CostCategory, ExpectedValue
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.spending import CostRecord, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable, Execution, QAStatus


def _validate_authorization(
    authorization: BudgetAuthorization,
    operation: OperationType,
    opportunity_reference: Reference,
    task_reference: Reference | None = None,
) -> None:
    request = authorization.request
    if (
        request.category != CostCategory.AI
        or request.context.operation != operation
        or request.context.opportunity_reference != opportunity_reference
        or request.context.task_reference != task_reference
    ):
        raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "authorization", "AI scope mismatch")


@dataclass(frozen=True, slots=True)
class ReferencedText:
    reference: Reference
    text: str


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    opportunity: Opportunity
    requirements: str
    authorization: BudgetAuthorization

    def __post_init__(self) -> None:
        _validate_authorization(
            self.authorization, OperationType.SCORING, self.opportunity.reference
        )


@dataclass(frozen=True, slots=True)
class EvaluationAdvice:
    expected_value: ExpectedValue
    rationale: str
    evidence: tuple[Reference, ...]


@dataclass(frozen=True, slots=True)
class WorkRequest:
    """Execution already binds a supported Research/Data task to authorization."""

    execution: Execution
    inputs: tuple[ReferencedText, ...]

    def __post_init__(self) -> None:
        _validate_authorization(
            self.execution.authorization,
            OperationType.TASK_EXECUTION,
            self.execution.task.opportunity_reference,
            self.execution.task.reference,
        )


@dataclass(frozen=True, slots=True)
class DeliverableDraft:
    content: str
    evidence: tuple[Reference, ...]


@dataclass(frozen=True, slots=True)
class QARequest:
    execution: Execution
    deliverable: Deliverable
    content: ReferencedText
    criteria: str
    authorization: BudgetAuthorization
    deterministic_insufficient: bool = False

    def __post_init__(self) -> None:
        if type(self.deterministic_insufficient) is not bool:
            raise DomainError(ErrorCode.INVALID_VALUE, "qa", "Explicit QA fallback flag required")
        _validate_authorization(
            self.authorization,
            OperationType.QA,
            self.execution.task.opportunity_reference,
            self.execution.task.reference,
        )
        if (
            self.deliverable.execution_reference != self.execution.reference
            or self.content.reference != self.deliverable.content_reference
        ):
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "deliverable", "QA content mismatch")


@dataclass(frozen=True, slots=True)
class QAAdvice:
    recommendation: QAStatus
    findings: str


@dataclass(frozen=True, slots=True)
class AIResponse[T]:
    operation_reference: Reference
    result: T
    actual_cost: CostRecord | None
    evidence: Reference

    def __post_init__(self) -> None:
        if self.actual_cost is not None and (
            self.actual_cost.context.operation_reference != self.operation_reference
            or self.actual_cost.cost.category != CostCategory.AI
        ):
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "cost", "AI measurement mismatch")
