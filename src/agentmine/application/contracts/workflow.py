"""Explicit workflow commands/results; no provider or presentation payloads."""

from dataclasses import dataclass
from datetime import datetime

from agentmine.application.contracts.ai import ReferencedText
from agentmine.domain.budget import AuthorizationDecision
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.scoring import ScoringSignals
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable, QAResult, TaskType


@dataclass(frozen=True, slots=True)
class PlanTaskRequest:
    opportunity_reference: Reference
    task_reference: Reference
    task_type: TaskType | str
    description: str


@dataclass(frozen=True, slots=True)
class ScoreRequest:
    opportunity_reference: Reference
    evaluation_reference: Reference
    signals: ScoringSignals
    evidence: tuple[Reference, ...]


@dataclass(frozen=True, slots=True)
class ExecuteTaskRequest:
    opportunity_reference: Reference
    ledger_reference: Reference
    operation_reference: Reference
    execution_reference: Reference
    deliverable_reference: Reference
    version: int
    estimated_cost: Money
    inputs: tuple[ReferencedText, ...] = ()
    spending_approval: Reference | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    opportunity: Opportunity
    decision: AuthorizationDecision | None


@dataclass(frozen=True, slots=True)
class HumanReviewRequest:
    opportunity_reference: Reference
    deliverable: Deliverable
    qa: QAResult
    content: ReferencedText
    requested_at: datetime
