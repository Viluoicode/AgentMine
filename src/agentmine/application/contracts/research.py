"""Validated research plans, source snapshots and reusable worker results."""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from agentmine.application.contracts.ai import DeliverableDraft, WorkRequest
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.budget import BudgetAuthorization
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Execution, TaskType


def nonblank(value: str, field: str, limit: int = 32_000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DomainError(ErrorCode.INVALID_VALUE, field, "Bounded nonempty text required")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise DomainError(ErrorCode.INVALID_VALUE, field, "UTF-8 text required") from None


@dataclass(frozen=True, slots=True)
class ResearchStep:
    operation_reference: Reference
    tool: Reference
    locator: str
    estimated_cost: Money
    spending_approval: Reference | None = None

    def __post_init__(self) -> None:
        require_reference(self.operation_reference, "operation")
        require_reference(self.tool, "tool")
        nonblank(self.locator, "locator", 2048)
        self.estimated_cost.require_nonnegative("tool_estimate")
        if self.spending_approval is not None:
            require_reference(self.spending_approval, "approval")


@dataclass(frozen=True, slots=True)
class TaskPlan:
    """Caller-validated scope; never construct by trusting arbitrary model JSON."""

    execution: Execution
    questions: tuple[str, ...]
    sources: tuple[ResearchStep, ...]

    def __post_init__(self) -> None:
        WorkRequest(self.execution, ())  # Enforce existing AI operation/scope contract.
        if self.execution.task.task_type != TaskType.RESEARCH:
            raise DomainError(ErrorCode.EXECUTION_FORBIDDEN, "task_type", "Research required")
        if not isinstance(self.questions, tuple) or not 1 <= len(self.questions) <= 20:
            raise DomainError(ErrorCode.INVALID_VALUE, "questions", "1-20 questions required")
        for question in self.questions:
            nonblank(question, "question", 2000)
        if not isinstance(self.sources, tuple) or not 1 <= len(self.sources) <= 10:
            raise DomainError(ErrorCode.INVALID_VALUE, "sources", "1-10 explicit sources required")
        operations = {self.execution.authorization.request.context.operation_reference}
        targets: set[tuple[Reference, str]] = set()
        for step in self.sources:
            if not isinstance(step, ResearchStep):
                raise DomainError(ErrorCode.INVALID_VALUE, "source", "Research step required")
            if step.operation_reference in operations or (step.tool, step.locator) in targets:
                raise DomainError(
                    ErrorCode.DUPLICATE_REFERENCE, "sources", "Duplicate operation/source"
                )
            operations.add(step.operation_reference)
            targets.add((step.tool, step.locator))
            step.estimated_cost.require_same_currency(
                self.execution.authorization.request.estimated_cost
            )


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    step: ResearchStep
    authorization: BudgetAuthorization

    def __post_init__(self) -> None:
        request = self.authorization.request
        if (
            request.category != CostCategory.TOOL
            or request.context.operation_reference != self.step.operation_reference
            or request.estimated_cost != self.step.estimated_cost
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "research", "Tool authorization mismatch"
            )


class VerificationStatus(StrEnum):
    VERIFIED_CONTENT = "verified_content"
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    """Verification means captured content provenance, not that its assertions are true."""

    operation_reference: Reference
    tool: Reference
    locator: str
    title: str
    text: str
    collected_at: datetime
    status: VerificationStatus
    verification_note: str
    verification_reference: Reference | None = None

    def __post_init__(self) -> None:
        require_reference(self.operation_reference, "operation")
        require_reference(self.tool, "tool")
        require_aware_timestamp(self.collected_at)
        for name, value in (
            ("locator", self.locator),
            ("title", self.title),
            ("text", self.text),
            ("verification_note", self.verification_note),
        ):
            nonblank(value, name)
        if not isinstance(self.status, VerificationStatus):
            raise DomainError(ErrorCode.INVALID_VALUE, "verification", "Explicit status required")
        if (
            self.status == VerificationStatus.VERIFIED_CONTENT
            and self.verification_reference is None
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "verification", "Verification evidence required"
            )
        if self.verification_reference is not None:
            require_reference(self.verification_reference, "verification")

    @property
    def content_digest(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchObservation:
    request: ResearchRequest
    source: SourceEvidence
    actual_cost: CostRecord | None


@dataclass(frozen=True, slots=True)
class ResearchClaim:
    plan: TaskPlan
    operation_reference: Reference


class ResearchWarning(StrEnum):
    UNVERIFIED_SOURCE = "unverified_source"
    NO_VERIFIED_SOURCES = "no_verified_sources"
    UNKNOWN_COST = "unknown_cost"
    MODEL_ANALYSIS_UNVERIFIED = "model_analysis_unverified"
    COST_ESTIMATE_EXCEEDED = "cost_estimate_exceeded"


@dataclass(frozen=True, slots=True)
class ResearchFact:
    source: Reference
    quote: str


@dataclass(frozen=True, slots=True)
class ResearchFindings:
    facts: tuple[ResearchFact, ...]
    analysis: str
    uncertainties: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchArtifact:
    name: str
    media_type: str
    content: str

    @property
    def digest(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchResult:
    execution_reference: Reference
    findings: ResearchFindings
    sources: tuple[SourceEvidence, ...]
    artifacts: tuple[ResearchArtifact, ...]
    costs: tuple[CostRecord, ...]
    warnings: tuple[ResearchWarning, ...]


def research_analysis(draft: DeliverableDraft, sources: tuple[SourceEvidence, ...]) -> str:
    """Validate the 4A research draft again at the worker boundary; never execute its plan."""

    def invalid() -> PortError:
        return PortError(
            PortErrorCode.INVALID_RESPONSE, "research", "Invalid research draft schema"
        )

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise invalid()
            result[key] = value
        return result

    if not isinstance(draft.content, str) or len(draft.content) > 64_000:
        raise invalid()
    try:
        value = json.loads(draft.content, object_pairs_hook=pairs)
    except (ValueError, RecursionError):
        raise invalid() from None
    if not isinstance(value, dict) or set(value) != {"plan", "content", "evidence"}:
        raise invalid()
    steps, content, evidence = value["plan"], value["content"], value["evidence"]
    if (
        not isinstance(steps, list)
        or not 1 <= len(steps) <= 20
        or any(not isinstance(step, str) or not step.strip() for step in steps)
        or not isinstance(content, str)
        or not content.strip()
        or not isinstance(evidence, list)
    ):
        raise invalid()
    aliases = {
        f"source-{index}": source.operation_reference for index, source in enumerate(sources)
    }
    if any(not isinstance(alias, str) or alias not in aliases for alias in evidence):
        raise invalid()
    if (
        len(set(evidence)) != len(evidence)
        or tuple(aliases[alias] for alias in evidence) != draft.evidence
    ):
        raise invalid()
    try:
        content.encode("utf-8")
    except UnicodeError:
        raise invalid() from None
    return content
