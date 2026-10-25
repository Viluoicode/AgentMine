"""Opportunity lifecycle aggregate; transitions require domain evidence."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypedDict, Unpack

from agentmine.domain.budget import AuthorizationDecision, Budget
from agentmine.domain.economics import EconomicAssessment
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import ExpectedValue, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.payment import PaymentEvidence
from agentmine.domain.revalidation import ResumeAssessment
from agentmine.domain.scoring import ScoringAssessment
from agentmine.domain.spending import AuthorizationStatus, OperationType, SpendingRequest
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import (
    Deliverable,
    Eligibility,
    EligibilityStatus,
    Execution,
    HumanApproval,
    Outcome,
    OutcomeStatus,
    QAResult,
    QAStatus,
    Submission,
    Task,
    TaskStatus,
)


class _OpportunityChanges(TypedDict, total=False):
    """Typed internal snapshot updates, excluded from the public constructor."""

    eligibility: Eligibility
    expected_value: ExpectedValue
    economic_assessment: EconomicAssessment | None
    scoring_assessment: ScoringAssessment | None
    score: Decimal
    task: Task
    execution: Execution
    deliverable: Deliverable | None
    qa: QAResult
    approval: HumanApproval | None
    submission: Submission
    outcome: Outcome
    payment: Reward
    payment_verification: PaymentEvidence
    skip_reason: str
    waiting_request: SpendingRequest | None
    waiting_state: OpportunityState | None


class OpportunityState(StrEnum):
    DISCOVERED = "discovered"
    NORMALIZED = "normalized"
    ELIGIBILITY_CHECK = "eligibility_check"
    INELIGIBLE = "ineligible"
    ELIGIBLE = "eligible"
    EVALUATED = "evaluated"
    SCORED = "scored"
    SKIPPED = "skipped"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    QA_PENDING = "qa_pending"
    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
    APPROVED_FOR_SUBMISSION = "approved_for_submission"
    SUBMISSION_IN_FLIGHT = "submission_in_flight"
    SUBMITTED = "submitted"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    PAID = "paid"
    WAITING_FOR_BUDGET = "waiting_for_budget"

    @property
    def successors(self) -> frozenset[OpportunityState]:
        """Explicit graph. Rework must go through execution and QA again."""
        match self:
            case OpportunityState.DISCOVERED:
                return frozenset((OpportunityState.NORMALIZED, OpportunityState.SKIPPED))
            case OpportunityState.NORMALIZED:
                return frozenset((OpportunityState.ELIGIBILITY_CHECK, OpportunityState.SKIPPED))
            case OpportunityState.ELIGIBILITY_CHECK:
                return frozenset(
                    (
                        OpportunityState.ELIGIBILITY_CHECK,
                        OpportunityState.ELIGIBLE,
                        OpportunityState.INELIGIBLE,
                    )
                )
            case OpportunityState.ELIGIBLE:
                return frozenset((OpportunityState.EVALUATED, OpportunityState.SKIPPED))
            case OpportunityState.EVALUATED:
                return frozenset((OpportunityState.SCORED, OpportunityState.SKIPPED))
            case OpportunityState.SCORED:
                return frozenset((OpportunityState.PLANNED, OpportunityState.SKIPPED))
            case OpportunityState.PLANNED:
                return frozenset(
                    (
                        OpportunityState.IN_PROGRESS,
                        OpportunityState.SKIPPED,
                        OpportunityState.WAITING_FOR_BUDGET,
                    )
                )
            case OpportunityState.WAITING_FOR_BUDGET:
                return frozenset(
                    (
                        OpportunityState.PLANNED,
                        OpportunityState.IN_PROGRESS,
                        OpportunityState.QA_PENDING,
                        OpportunityState.SKIPPED,
                        OpportunityState.INELIGIBLE,
                    )
                )
            case OpportunityState.IN_PROGRESS:
                return frozenset((OpportunityState.QA_PENDING, OpportunityState.WAITING_FOR_BUDGET))
            case OpportunityState.QA_PENDING:
                return frozenset(
                    (
                        OpportunityState.READY_FOR_HUMAN_REVIEW,
                        OpportunityState.IN_PROGRESS,
                        OpportunityState.WAITING_FOR_BUDGET,
                    )
                )
            case OpportunityState.READY_FOR_HUMAN_REVIEW:
                return frozenset(
                    (
                        OpportunityState.APPROVED_FOR_SUBMISSION,
                        OpportunityState.SKIPPED,
                        OpportunityState.IN_PROGRESS,
                    )
                )
            case OpportunityState.APPROVED_FOR_SUBMISSION:
                return frozenset(
                    (
                        OpportunityState.SUBMITTED,
                        OpportunityState.SKIPPED,
                        OpportunityState.SUBMISSION_IN_FLIGHT,
                    )
                )
            case OpportunityState.SUBMISSION_IN_FLIGHT:
                return frozenset((OpportunityState.SUBMITTED,))
            case OpportunityState.SUBMITTED:
                return frozenset((OpportunityState.ACCEPTED, OpportunityState.REJECTED))
            case OpportunityState.ACCEPTED:
                return frozenset((OpportunityState.PAID,))
            case _:
                return frozenset()


@dataclass(frozen=True, slots=True)
class Opportunity:
    reference: Reference
    title: str
    potential_reward: Reward
    eligibility: Eligibility | None = field(default=None, init=False)
    expected_value: ExpectedValue | None = field(default=None, init=False)
    economic_assessment: EconomicAssessment | None = field(default=None, init=False)
    scoring_assessment: ScoringAssessment | None = field(default=None, init=False)
    score: Decimal | None = field(default=None, init=False)
    task: Task | None = field(default=None, init=False)
    execution: Execution | None = field(default=None, init=False)
    deliverable: Deliverable | None = field(default=None, init=False)
    qa: QAResult | None = field(default=None, init=False)
    approval: HumanApproval | None = field(default=None, init=False)
    submission: Submission | None = field(default=None, init=False)
    outcome: Outcome | None = field(default=None, init=False)
    payment: Reward | None = field(default=None, init=False)
    payment_verification: PaymentEvidence | None = field(default=None, init=False)
    skip_reason: str | None = field(default=None, init=False)
    waiting_request: SpendingRequest | None = field(default=None, init=False)
    waiting_state: OpportunityState | None = field(default=None, init=False)
    state: OpportunityState = field(default=OpportunityState.DISCOVERED, init=False)
    history: tuple[OpportunityState, ...] = field(
        default=(OpportunityState.DISCOVERED,), init=False
    )

    def __post_init__(self) -> None:
        require_reference(self.reference, "opportunity_reference")
        if not self.title.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "title", "Opportunity title required")
        if self.potential_reward.stage != RewardStage.POTENTIAL:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "potential_reward", "Potential reward required"
            )

    def _move(
        self, target: OpportunityState, **changes: Unpack[_OpportunityChanges]
    ) -> Opportunity:
        if target not in self.state.successors:
            raise DomainError(
                ErrorCode.INVALID_TRANSITION, "state", f"Cannot move from {self.state} to {target}"
            )
        candidate = copy(self)
        for name, value in changes.items():
            object.__setattr__(candidate, name, value)
        object.__setattr__(candidate, "state", target)
        object.__setattr__(candidate, "history", (*self.history, target))
        return candidate

    def normalize(self) -> Opportunity:
        return self._move(OpportunityState.NORMALIZED)

    def _require_state(self, expected: OpportunityState) -> None:
        if self.state != expected:
            raise DomainError(ErrorCode.INVALID_TRANSITION, "state", f"Action requires {expected}")

    def check_eligibility(self) -> Opportunity:
        return self._move(OpportunityState.ELIGIBILITY_CHECK)

    def assess_eligibility(self, assessment: Eligibility) -> Opportunity:
        self._require_state(OpportunityState.ELIGIBILITY_CHECK)
        if assessment.status in (
            EligibilityStatus.UNKNOWN,
            EligibilityStatus.REQUIRES_HUMAN_REVIEW,
        ):
            return self._move(OpportunityState.ELIGIBILITY_CHECK, eligibility=assessment)
        target = (
            OpportunityState.ELIGIBLE
            if assessment.status == EligibilityStatus.ELIGIBLE
            else OpportunityState.INELIGIBLE
        )
        return self._move(target, eligibility=assessment)

    def evaluate(self, estimate: ExpectedValue | EconomicAssessment) -> Opportunity:
        assessment = estimate if isinstance(estimate, EconomicAssessment) else None
        value = assessment.expected_net_value if assessment is not None else estimate
        assert isinstance(value, ExpectedValue)
        self.potential_reward.amount.require_same_currency(value.amount)
        if assessment is not None and assessment.potential_reward != self.potential_reward:
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "reward", "Forecast reward mismatch")
        return self._move(
            OpportunityState.EVALUATED, expected_value=value, economic_assessment=assessment
        )

    def assign_score(self, score: Decimal | ScoringAssessment) -> Opportunity:
        assessment = score if isinstance(score, ScoringAssessment) else None
        value = assessment.score if assessment is not None else score
        if not isinstance(value, Decimal) or not value.is_finite() or not 0 <= value <= 100:
            raise DomainError(ErrorCode.INVALID_VALUE, "score", "Finite score in [0, 100] required")
        if assessment is not None and assessment.economics != self.economic_assessment:
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "economics", "Scoring forecast mismatch")
        return self._move(OpportunityState.SCORED, score=value, scoring_assessment=assessment)

    def skip(self, reason: str) -> Opportunity:
        if not reason.strip():
            raise DomainError(ErrorCode.INVALID_VALUE, "skip_reason", "Skip reason required")
        if self.state == OpportunityState.WAITING_FOR_BUDGET and self.task is not None:
            return self._move(
                OpportunityState.SKIPPED,
                skip_reason=reason,
                task=self.task._finish_budget_wait(TaskStatus.CANCELLED, self.task.deadline),
                waiting_request=None,
                waiting_state=None,
            )
        return self._move(OpportunityState.SKIPPED, skip_reason=reason)

    def plan(self, task: Task) -> Opportunity:
        self._require_state(OpportunityState.SCORED)
        if task.opportunity_reference != self.reference:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "task", "Task belongs to another opportunity"
            )
        return self._move(OpportunityState.PLANNED, task=task)

    def start(self, execution: Execution) -> Opportunity:
        self._require_state(OpportunityState.PLANNED)
        if execution.task != self.task:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "execution", "Execution must match planned task"
            )
        return self._move(OpportunityState.IN_PROGRESS, execution=execution)

    def wait_for_budget(self, decision: AuthorizationDecision) -> Opportunity:
        context = decision.request.context
        if (
            decision.status != AuthorizationStatus.DENIED
            or decision.request.estimated_cost.amount <= 0
            or self.task is None
            or context.operation not in (OperationType.TASK_EXECUTION, OperationType.QA)
            or context.task_reference != self.task.reference
            or context.opportunity_reference != self.reference
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "budget", "Matching denied paid execution required"
            )
        expected_operation = (
            OperationType.QA
            if self.state == OpportunityState.QA_PENDING
            else OperationType.TASK_EXECUTION
        )
        if context.operation != expected_operation:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "operation", "Operation does not match phase"
            )
        return self._move(
            OpportunityState.WAITING_FOR_BUDGET,
            task=self.task.wait_for_budget(context.occurred_at),
            waiting_request=decision.request,
            waiting_state=self.state,
        )

    def resume_after_budget(
        self,
        assessment: ResumeAssessment,
        budget: Budget,
        at: datetime,
    ) -> BudgetResumeResult:
        require_aware_timestamp(at)
        if (
            self.state != OpportunityState.WAITING_FOR_BUDGET
            or self.task is None
            or self.waiting_request is None
        ):
            raise DomainError(
                ErrorCode.INVALID_TRANSITION, "state", "Opportunity is not waiting for budget"
            )
        if (
            assessment.opportunity_reference != self.reference
            or self.task.waiting_since is None
            or assessment.refreshed_at < self.task.waiting_since
            or assessment.refreshed_at > at
        ):
            raise DomainError(
                ErrorCode.REVALIDATION_REQUIRED, "refresh", "Fresh opportunity assessment required"
            )
        if assessment.deadline is not None and at >= assessment.deadline:
            updated = self._move(
                OpportunityState.SKIPPED,
                skip_reason="Expired while waiting for budget",
                task=self.task._finish_budget_wait(TaskStatus.EXPIRED, assessment.deadline),
                waiting_request=None,
                waiting_state=None,
            )
            return BudgetResumeResult(updated, budget)
        if not assessment.is_open:
            updated = self._move(
                OpportunityState.SKIPPED,
                skip_reason="Opportunity is no longer open",
                task=self.task._finish_budget_wait(TaskStatus.CANCELLED, assessment.deadline),
                waiting_request=None,
                waiting_state=None,
            )
            return BudgetResumeResult(updated, budget)
        if assessment.eligibility is None or assessment.eligibility.status not in (
            EligibilityStatus.ELIGIBLE,
            EligibilityStatus.INELIGIBLE,
        ):
            raise DomainError(
                ErrorCode.REVALIDATION_REQUIRED, "eligibility", "Fresh eligibility required"
            )
        if assessment.eligibility.status == EligibilityStatus.INELIGIBLE:
            updated = self._move(
                OpportunityState.INELIGIBLE,
                eligibility=assessment.eligibility,
                task=self.task._finish_budget_wait(TaskStatus.CANCELLED, assessment.deadline),
                waiting_request=None,
                waiting_state=None,
            )
            return BudgetResumeResult(updated, budget)
        if assessment.expected_value is None or assessment.score is None:
            raise DomainError(
                ErrorCode.REVALIDATION_REQUIRED, "score", "Fresh evaluation and score required"
            )
        self.potential_reward.amount.require_same_currency(assessment.expected_value.amount)
        request = self.waiting_request
        context = replace(
            request.context,
            occurred_at=at,
            human_approval=assessment.human_approval or request.context.human_approval,
        )
        decision = budget.authorize(request.estimated_cost, request.category, context)
        if decision.status != AuthorizationStatus.AUTHORIZED:
            return BudgetResumeResult(self, decision.budget, decision)
        if self.waiting_state is None:
            raise DomainError(
                ErrorCode.REVALIDATION_REQUIRED, "waiting_state", "Saved phase required"
            )
        updated = self._move(
            self.waiting_state,
            task=self.task._finish_budget_wait(TaskStatus.READY, assessment.deadline),
            eligibility=assessment.eligibility,
            expected_value=assessment.expected_value,
            score=assessment.score,
            economic_assessment=None,
            scoring_assessment=None,
            waiting_request=None,
            waiting_state=None,
        )
        return BudgetResumeResult(updated, decision.budget, decision)

    def finish(self, deliverable: Deliverable) -> Opportunity:
        self._require_state(OpportunityState.IN_PROGRESS)
        if self.execution is None or deliverable.execution_reference != self.execution.reference:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "deliverable", "Deliverable execution mismatch"
            )
        if self.qa is not None and deliverable.version <= self.qa.deliverable.version:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "version",
                "Rework requires a newer deliverable version",
            )
        return self._move(OpportunityState.QA_PENDING, deliverable=deliverable)

    def review_qa(self, result: QAResult) -> Opportunity:
        self._require_state(OpportunityState.QA_PENDING)
        if result.deliverable != self.deliverable:
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "qa", "QA deliverable mismatch")
        if result.status == QAStatus.FAILED:
            return self._move(
                OpportunityState.IN_PROGRESS,
                qa=result,
                deliverable=None,
                approval=None,
            )
        return self._move(OpportunityState.READY_FOR_HUMAN_REVIEW, qa=result)

    def request_revision(self) -> Opportunity:
        self._require_state(OpportunityState.READY_FOR_HUMAN_REVIEW)
        return self._move(OpportunityState.IN_PROGRESS, deliverable=None, approval=None)

    def approve(self, approval: HumanApproval) -> Opportunity:
        if (
            approval.deliverable != self.deliverable
            or self.qa is None
            or self.qa.status != QAStatus.PASSED
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "approval", "Approval requires current passing QA"
            )
        return self._move(OpportunityState.APPROVED_FOR_SUBMISSION, approval=approval)

    def begin_submission(self) -> Opportunity:
        """A durable API claim wins over cancellation; receipt is still unknown."""
        self._require_state(OpportunityState.APPROVED_FOR_SUBMISSION)
        return self._move(OpportunityState.SUBMISSION_IN_FLIGHT)

    def submit(self, submission: Submission) -> Opportunity:
        if (
            submission.deliverable != self.deliverable
            or submission.qa != self.qa
            or submission.approval != self.approval
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "submission", "Submission evidence mismatch"
            )
        return self._move(OpportunityState.SUBMITTED, submission=submission)

    def record_outcome(self, outcome: Outcome) -> Opportunity:
        if self.submission is None or outcome.submission_reference != self.submission.reference:
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "outcome", "Outcome submission mismatch")
        if outcome.accepted_reward is not None:
            self.potential_reward.amount.require_same_currency(outcome.accepted_reward.amount)
        target = (
            OpportunityState.ACCEPTED
            if outcome.status == OutcomeStatus.ACCEPTED
            else OpportunityState.REJECTED
        )
        return self._move(target, outcome=outcome)

    def verify_payment(
        self, payment: Reward, evidence: PaymentEvidence | None = None
    ) -> Opportunity:
        self._require_state(OpportunityState.ACCEPTED)
        if not isinstance(evidence, PaymentEvidence) or evidence.reward != payment:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "payment", "Independent settlement evidence required"
            )
        if self.submission is None or evidence.payment_timestamp < self.submission.submitted_at:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "payment_timestamp", "Payment predates submission"
            )
        if payment.stage != RewardStage.VERIFIED_PAYMENT:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "payment", "Verified payment evidence required"
            )
        if self.submission is None or payment.submission_reference != self.submission.reference:
            raise DomainError(ErrorCode.EVIDENCE_MISMATCH, "payment", "Payment submission mismatch")
        self.potential_reward.amount.require_same_currency(payment.amount)
        return self._move(OpportunityState.PAID, payment=payment, payment_verification=evidence)

    @property
    def accepted_reward(self) -> Reward | None:
        return None if self.outcome is None else self.outcome.accepted_reward

    @property
    def verified_reward(self) -> Reward | None:
        return (
            self.payment
            if self.state == OpportunityState.PAID and self.payment_verification is not None
            else None
        )

    @property
    def payment_reference(self) -> Reference | None:
        return (
            None
            if self.payment_verification is None
            else self.payment_verification.payment_reference
        )

    @property
    def payment_timestamp(self) -> datetime | None:
        return (
            None
            if self.payment_verification is None
            else self.payment_verification.payment_timestamp
        )

    @property
    def currency(self) -> str:
        return self.potential_reward.amount.currency

    @property
    def verified_revenue(self) -> Money:
        if (
            self.state == OpportunityState.PAID
            and self.payment is not None
            and self.payment_verification is not None
            and self.payment_verification.reward == self.payment
        ):
            return self.payment.amount
        return Money(Decimal(0), self.potential_reward.amount.currency)


@dataclass(frozen=True, slots=True)
class BudgetResumeResult:
    opportunity: Opportunity
    budget: Budget
    decision: AuthorizationDecision | None = None
