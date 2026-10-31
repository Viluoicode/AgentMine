"""Immutable operator view: estimates and observed costs remain separate."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.submission_context import SubmissionEnvelope
from agentmine.domain.approval import ApprovalDecision, ApprovalScope
from agentmine.domain.budget import BudgetAuthorization
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import ExpectedValue, Reward
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Deliverable, Eligibility, QAResult


@dataclass(frozen=True, slots=True)
class RecordedOperatorReview:
    review: "OperatorReview"
    decision: ApprovalDecision | None
    submission_envelope: SubmissionEnvelope | None = None


@dataclass(frozen=True, slots=True)
class OperatorReview:
    reference: Reference
    opportunity_snapshot: Versioned[Opportunity]
    scope: ApprovalScope
    requested_at: datetime
    ledger_reference: Reference
    ledger_revision: int
    actual_costs: tuple[CostRecord, ...]
    outstanding: tuple[BudgetAuthorization, ...]
    content: ReferencedText | None
    risks: tuple[str, ...]

    def __post_init__(self) -> None:
        require_reference(self.reference, "review")
        require_reference(self.ledger_reference, "ledger")
        require_aware_timestamp(self.requested_at)
        if (
            not isinstance(self.scope, ApprovalScope)
            or type(self.ledger_revision) is not int
            or self.ledger_revision < 1
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "review", "Scope and ledger revision required"
            )
        if (
            not isinstance(self.risks, tuple)
            or not self.risks
            or any(not isinstance(risk, str) or not risk.strip() for risk in self.risks)
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "risks", "Explicit risks/uncertainties required"
            )
        if not isinstance(self.actual_costs, tuple) or any(
            not isinstance(record, CostRecord)
            or record.context.opportunity_reference != self.opportunity.reference
            for record in self.actual_costs
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "costs", "Costs must belong to reviewed opportunity"
            )
        if not isinstance(self.outstanding, tuple) or any(
            not isinstance(auth, BudgetAuthorization)
            or auth.request.context.opportunity_reference != self.opportunity.reference
            for auth in self.outstanding
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "costs",
                "Reservations must belong to reviewed opportunity",
            )

    @property
    def opportunity(self) -> Opportunity:
        return self.opportunity_snapshot.value

    @property
    def reward(self) -> Reward:
        return self.opportunity.potential_reward

    @property
    def eligibility(self) -> Eligibility | None:
        return self.opportunity.eligibility

    @property
    def score(self) -> Decimal | None:
        return self.opportunity.score

    @property
    def expected_value(self) -> ExpectedValue | None:
        return self.opportunity.expected_value

    @property
    def estimated_cost(self) -> Money | None:
        assessment = self.opportunity.economic_assessment
        return None if assessment is None else assessment.inputs.estimated_cost.total

    @property
    def actual_cost_so_far(self) -> tuple[Money, ...]:
        # Separate currencies; absent measurements are not represented as a free execution.
        totals: dict[str, Money] = {}
        for record in self.actual_costs:
            amount = record.actual_cost
            totals[amount.currency] = (
                totals.get(amount.currency, Money(Decimal(0), amount.currency)) + amount
            )
        return tuple(totals[key] for key in sorted(totals))

    @property
    def deliverable(self) -> Deliverable | None:
        return self.opportunity.deliverable

    @property
    def qa_result(self) -> QAResult | None:
        return self.opportunity.qa

    @property
    def submission_destination(self) -> Reference:
        return self.scope.destination
