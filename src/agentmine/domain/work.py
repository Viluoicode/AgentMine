"""Supported work, immutable deliverable versions and submission evidence."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from agentmine.domain.budget import BudgetAuthorization, OperatingMode
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import Reward, RewardStage
from agentmine.domain.spending import OperationType
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference


class TaskType(StrEnum):
    RESEARCH = "research"
    DATA_PROCESSING = "data_processing"


class TaskStatus(StrEnum):
    READY = "ready"
    WAITING_FOR_BUDGET = "waiting_for_budget"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class EligibilityStatus(StrEnum):
    UNKNOWN = "unknown"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


class EligibilityReason(StrEnum):
    MANUAL_ASSESSMENT = "MANUAL_ASSESSMENT"
    ALL_RULES_PASSED = "ALL_RULES_PASSED"
    OPPORTUNITY_CLOSED = "OPPORTUNITY_CLOSED"
    OPEN_STATUS_UNKNOWN = "OPEN_STATUS_UNKNOWN"
    DEADLINE_EXPIRED = "DEADLINE_EXPIRED"
    DEADLINE_UNKNOWN = "DEADLINE_UNKNOWN"
    AI_NOT_ALLOWED = "AI_NOT_ALLOWED"
    AI_POLICY_UNKNOWN = "AI_POLICY_UNKNOWN"
    AI_DISCLOSURE_REQUIRED = "AI_DISCLOSURE_REQUIRED"
    AI_DISCLOSURE_UNKNOWN = "AI_DISCLOSURE_UNKNOWN"
    AI_POLICY_REVIEW_REQUIRED = "AI_POLICY_REVIEW_REQUIRED"
    COUNTRY_RESTRICTION = "COUNTRY_RESTRICTION"
    GEOGRAPHIC_RESTRICTIONS_UNKNOWN = "GEOGRAPHIC_RESTRICTIONS_UNKNOWN"
    COUNTRY_UNKNOWN = "COUNTRY_UNKNOWN"
    ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
    ACCOUNT_REQUIREMENT_UNKNOWN = "ACCOUNT_REQUIREMENT_UNKNOWN"
    ACCOUNT_STATUS_UNKNOWN = "ACCOUNT_STATUS_UNKNOWN"
    IDENTITY_REQUIRED = "IDENTITY_REQUIRED"
    IDENTITY_REQUIREMENT_UNKNOWN = "IDENTITY_REQUIREMENT_UNKNOWN"
    IDENTITY_STATUS_UNKNOWN = "IDENTITY_STATUS_UNKNOWN"
    PHYSICAL_PRESENCE_REQUIRED = "PHYSICAL_PRESENCE_REQUIRED"
    PHYSICAL_PRESENCE_UNKNOWN = "PHYSICAL_PRESENCE_UNKNOWN"
    UNSUPPORTED_TASK_TYPE = "UNSUPPORTED_TASK_TYPE"
    TASK_TYPE_UNKNOWN = "TASK_TYPE_UNKNOWN"
    REQUIRED_SKILLS_UNKNOWN = "REQUIRED_SKILLS_UNKNOWN"
    PARTICIPANT_SKILLS_UNKNOWN = "PARTICIPANT_SKILLS_UNKNOWN"
    MISSING_REQUIRED_SKILL = "MISSING_REQUIRED_SKILL"
    SUBMISSION_UNSUPPORTED = "SUBMISSION_UNSUPPORTED"
    SUBMISSION_SUPPORT_UNKNOWN = "SUBMISSION_SUPPORT_UNKNOWN"
    MANUAL_SUBMISSION_REQUIRED = "MANUAL_SUBMISSION_REQUIRED"
    INSUFFICIENT_TIME_REMAINING = "INSUFFICIENT_TIME_REMAINING"
    SUSPICIOUS_PAYMENT_REQUIREMENTS = "SUSPICIOUS_PAYMENT_REQUIREMENTS"
    SENSITIVE_CREDENTIALS_REQUIRED = "SENSITIVE_CREDENTIALS_REQUIRED"
    PAYMENT_REQUIREMENTS_UNKNOWN = "PAYMENT_REQUIREMENTS_UNKNOWN"
    PROHIBITED_ACTION = "PROHIBITED_ACTION"
    PROHIBITED_ACTIONS_UNKNOWN = "PROHIBITED_ACTIONS_UNKNOWN"


@dataclass(frozen=True, slots=True)
class Eligibility:
    status: EligibilityStatus
    reason: str
    reasons: tuple[EligibilityReason, ...] = (EligibilityReason.MANUAL_ASSESSMENT,)

    def __post_init__(self) -> None:
        if not isinstance(self.status, EligibilityStatus) or not self.reason.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "eligibility", "Status and reason required")
        if (
            not isinstance(self.reasons, tuple)
            or not self.reasons
            or any(not isinstance(reason, EligibilityReason) for reason in self.reasons)
            or len(set(self.reasons)) != len(self.reasons)
        ):
            raise DomainError(ErrorCode.INVALID_VALUE, "reasons", "Unique reason codes required")


@dataclass(frozen=True, slots=True)
class Task:
    reference: Reference
    opportunity_reference: Reference
    task_type: TaskType
    description: str
    deadline: datetime | None = None
    status: TaskStatus = field(default=TaskStatus.READY, init=False)
    waiting_since: datetime | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        require_reference(self.reference, "task_reference")
        require_reference(self.opportunity_reference, "opportunity_reference")
        if not isinstance(self.task_type, TaskType):
            raise DomainError(
                ErrorCode.EXECUTION_FORBIDDEN, "task_type", "Unsupported V1 task type"
            )
        if not self.description.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "description", "Task description required")
        if self.deadline is not None:
            require_aware_timestamp(self.deadline)

    def wait_for_budget(self, at: datetime) -> Task:
        require_aware_timestamp(at)
        if self.status != TaskStatus.READY:
            raise DomainError(ErrorCode.INVALID_TRANSITION, "task", "Only ready tasks can wait")
        updated = copy(self)
        object.__setattr__(updated, "status", TaskStatus.WAITING_FOR_BUDGET)
        object.__setattr__(updated, "waiting_since", at)
        return updated

    def _finish_budget_wait(self, status: TaskStatus, deadline: datetime | None) -> Task:
        """Opportunity owns revalidation; this is an internal nested-model update."""
        if self.status != TaskStatus.WAITING_FOR_BUDGET or status == TaskStatus.WAITING_FOR_BUDGET:
            raise DomainError(ErrorCode.INVALID_TRANSITION, "task", "Task is not waiting")
        updated = copy(self)
        object.__setattr__(updated, "status", status)
        object.__setattr__(updated, "deadline", deadline)
        object.__setattr__(updated, "waiting_since", None)
        return updated


@dataclass(frozen=True, slots=True)
class Execution:
    reference: Reference
    task: Task
    mode: OperatingMode
    started_at: datetime
    authorization: BudgetAuthorization

    def __post_init__(self) -> None:
        require_reference(self.reference, "execution_reference")
        require_aware_timestamp(self.started_at)
        if not isinstance(self.task, Task):
            raise DomainError(ErrorCode.EXECUTION_FORBIDDEN, "task", "Supported task required")
        if not isinstance(self.mode, OperatingMode):
            raise DomainError(ErrorCode.INVALID_VALUE, "operating_mode", "Unknown operating mode")
        if not isinstance(self.authorization, BudgetAuthorization):
            raise DomainError(
                ErrorCode.EXECUTION_FORBIDDEN, "authorization", "Budget authorization required"
            )
        request = self.authorization.request
        if (
            self.task.status != TaskStatus.READY
            or request.context.operation != OperationType.TASK_EXECUTION
            or request.context.task_reference != self.task.reference
            or request.context.opportunity_reference != self.task.opportunity_reference
            or self.mode != self.authorization.mode
            or self.started_at < request.context.occurred_at
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "authorization", "Execution authorization mismatch"
            )
        if self.task.deadline is not None and self.started_at >= self.task.deadline:
            raise DomainError(ErrorCode.EXECUTION_FORBIDDEN, "deadline", "Task expired")
        if self.mode == OperatingMode.SCOUT_ONLY and request.estimated_cost.amount > 0:
            raise DomainError(
                ErrorCode.EXECUTION_FORBIDDEN,
                "operating_mode",
                "SCOUT_ONLY cannot execute paid work",
            )
        if not isinstance(self.task.task_type, TaskType):
            raise DomainError(
                ErrorCode.EXECUTION_FORBIDDEN, "task_type", "Unsupported V1 task type"
            )


@dataclass(frozen=True, slots=True)
class Deliverable:
    reference: Reference
    execution_reference: Reference
    version: int
    content_reference: Reference

    def __post_init__(self) -> None:
        require_reference(self.reference, "deliverable_reference")
        require_reference(self.execution_reference, "execution_reference")
        require_reference(self.content_reference, "content_reference")
        if type(self.version) is not int or self.version < 1:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "version", "Version must be a positive integer"
            )


class QAStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class QAResult:
    deliverable: Deliverable
    status: QAStatus
    findings: str

    def __post_init__(self) -> None:
        if not isinstance(self.deliverable, Deliverable):
            raise DomainError(ErrorCode.INVALID_VALUE, "deliverable", "QA requires a deliverable")
        if not isinstance(self.status, QAStatus) or not self.findings.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "qa", "QA status and findings required")


@dataclass(frozen=True, slots=True)
class HumanApproval:
    deliverable: Deliverable
    target: Reference
    actor: Reference
    approved_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.deliverable, Deliverable):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "deliverable", "Approval requires a deliverable"
            )
        require_reference(self.actor, "actor")
        require_reference(self.target, "target")
        require_aware_timestamp(self.approved_at)


@dataclass(frozen=True, slots=True)
class Submission:
    reference: Reference
    deliverable: Deliverable
    qa: QAResult
    approval: HumanApproval
    target: Reference
    receipt: Reference
    submitted_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.deliverable, Deliverable)
            or not isinstance(self.qa, QAResult)
            or not isinstance(self.approval, HumanApproval)
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "submission", "Deliverable, QA and approval required"
            )
        require_reference(self.reference, "submission_reference")
        require_reference(self.target, "target")
        require_reference(self.receipt, "receipt")
        require_aware_timestamp(self.submitted_at)
        if self.qa.status != QAStatus.PASSED:
            raise DomainError(ErrorCode.INVALID_VALUE, "qa", "Submission requires passing QA")
        if (
            self.qa.deliverable != self.deliverable
            or self.approval.deliverable != self.deliverable
            or self.approval.target != self.target
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "submission", "QA/approval binding mismatch"
            )
        if self.submitted_at < self.approval.approved_at:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "submitted_at", "Submission precedes approval"
            )


class OutcomeStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Outcome:
    submission_reference: Reference
    status: OutcomeStatus
    evidence: Reference
    accepted_reward: Reward | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        require_reference(self.submission_reference, "submission_reference")
        require_reference(self.evidence, "evidence")
        if not isinstance(self.status, OutcomeStatus):
            raise DomainError(ErrorCode.INVALID_VALUE, "outcome", "Unknown outcome status")
        if self.rejection_reason is not None and (
            self.status != OutcomeStatus.REJECTED
            or not isinstance(self.rejection_reason, str)
            or not self.rejection_reason.strip()
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "rejection_reason", "Reason belongs to a rejected outcome"
            )
        if self.accepted_reward is not None and (
            self.status != OutcomeStatus.ACCEPTED
            or self.accepted_reward.stage != RewardStage.ACCEPTED
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "accepted_reward", "Accepted reward requires acceptance"
            )
        if self.accepted_reward is not None and (
            self.accepted_reward.submission_reference != self.submission_reference
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "accepted_reward", "Reward submission mismatch"
            )
