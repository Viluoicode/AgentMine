"""One-operator review snapshots and durable decisions; no external side effects."""

import logging
from dataclasses import dataclass

from agentmine.application.contracts.operator import OperatorReview
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.approval import ApprovalRepository
from agentmine.application.ports.repositories import (
    CostLedgerRepository,
    ExecutionRepository,
    OpportunityRepository,
)
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.context import (
    check_content,
    load,
    refresh,
    require_state,
    save,
)
from agentmine.domain.approval import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalScope,
    OperatorDecision,
)
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference, require_reference
from agentmine.domain.work import HumanApproval


@dataclass(frozen=True, slots=True)
class PrepareOperatorReview:
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    ledger: CostLedgerRepository
    approvals: ApprovalRepository
    clock: Clock

    def execute(
        self,
        reference: Reference,
        opportunity_reference: Reference,
        ledger_reference: Reference,
        scope: ApprovalScope,
    ) -> OperatorReview:
        require_reference(reference, "review")
        existing = self.approvals.get_review(reference)
        if existing is not None:
            if (
                existing.opportunity.reference != opportunity_reference
                or existing.scope != scope
                or existing.ledger_reference != ledger_reference
            ):
                raise PortError(PortErrorCode.CONFLICT, "review", "Review identity reused")
            return existing
        previous = load(self.opportunities, opportunity_reference)
        opportunity = previous.value
        if scope.action == ApprovalAction.EXTERNAL_SUBMISSION:
            require_state(opportunity, OpportunityState.READY_FOR_HUMAN_REVIEW)
            if scope.deliverable != opportunity.deliverable:
                raise PortError(PortErrorCode.CONFLICT, "review", "Current deliverable required")
        if scope.action == ApprovalAction.SPENDING:
            assert scope.spending is not None
            context = scope.spending.context
            if (
                scope.destination != ledger_reference
                or context.opportunity_reference != opportunity_reference
                or (
                    context.task_reference is not None
                    and (
                        opportunity.task is None
                        or context.task_reference != opportunity.task.reference
                    )
                )
            ):
                raise PortError(
                    PortErrorCode.CONFLICT, "review", "Spending opportunity/ledger scope mismatch"
                )
        ledger = self.ledger.get(ledger_reference)
        if ledger is None:
            raise PortError(PortErrorCode.UNAVAILABLE, "review", "Budget ledger missing")
        content = None
        if opportunity.deliverable is not None:
            content = self.executions.get_content(opportunity.deliverable.content_reference)
            if content is None:
                raise PortError(PortErrorCode.UNAVAILABLE, "review", "Deliverable content missing")
            check_content(content, opportunity.deliverable.content_reference)
        costs = tuple(
            record
            for record in ledger.value.records
            if record.context.opportunity_reference == opportunity_reference
        )
        outstanding = tuple(
            auth
            for auth in ledger.value.outstanding
            if auth.request.context.opportunity_reference == opportunity_reference
        )
        risks = [
            "Potential reward and expected value are not verified revenue.",
            "Recorded costs may be incomplete; missing measurements are not zero.",
        ]
        if outstanding:
            risks.append(
                "Outstanding estimates include unresolved usage; they are not actual cost."
            )
        if opportunity.scoring_assessment is None:
            risks.append("Structured scoring/risk assessment unavailable.")
        else:
            signal = opportunity.scoring_assessment.signals.risk
            risks.append(f"Subjective risk estimate: {signal.value}; {signal.rationale}")
        if opportunity.economic_assessment is None:
            risks.append("Complete estimated cost unavailable.")
        if opportunity.qa is not None:
            risks.append("QA assessment: " + opportunity.qa.findings)
        if scope.action in (ApprovalAction.WALLET_FINANCIAL, ApprovalAction.SENSITIVE_ACCOUNT):
            risks.append(
                "Execution of this action is unsupported in V1; consent does not enable it."
            )
        review = OperatorReview(
            reference,
            previous,
            scope,
            self.clock.now(),
            ledger_reference,
            ledger.revision,
            costs,
            outstanding,
            content,
            tuple(risks),
        )
        self.approvals.save_review(review)
        return review


@dataclass(frozen=True, slots=True)
class DecideOperatorReview:
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    ledger: CostLedgerRepository
    approvals: ApprovalRepository
    source: OpportunitySource
    clock: Clock
    operator: Reference

    def execute(
        self, reference: Reference, decision: OperatorDecision, reason: str | None = None
    ) -> ApprovalDecision:
        review = self.approvals.get_review(reference)
        if review is None:
            raise PortError(PortErrorCode.UNAVAILABLE, "decide", "Review missing")
        recorded = self.approvals.get_decision(reference)
        candidate = ApprovalDecision(
            reference,
            self.operator,
            self.clock.now() if recorded is None else recorded.decided_at,
            decision,
            reason,
        )
        if recorded is not None and candidate != recorded:
            raise PortError(PortErrorCode.CONFLICT, "decide", "Review already decided")
        if not review.requested_at <= candidate.decided_at <= self.clock.now():
            raise PortError(PortErrorCode.CONFLICT, "decide", "Decision time invalid")
        original = review.opportunity
        updated: Opportunity = original
        submission = review.scope.action == ApprovalAction.EXTERNAL_SUBMISSION
        if submission:
            assert review.scope.deliverable is not None
            if decision == OperatorDecision.APPROVE:
                updated = original.approve(
                    HumanApproval(
                        review.scope.deliverable,
                        review.scope.destination,
                        self.operator,
                        candidate.decided_at,
                    )
                )
            elif decision == OperatorDecision.REJECT:
                updated = original.skip(reason or "Rejected by operator")
            else:
                updated = original.request_revision()
        current = load(self.opportunities, original.reference)
        if recorded is not None and current.value == updated:
            return recorded
        if current != review.opportunity_snapshot:
            raise PortError(
                PortErrorCode.CONFLICT, "decide", "Opportunity changed; prepare a new review"
            )
        if recorded is None:
            ledger = self.ledger.get(review.ledger_reference)
            if ledger is None or ledger.revision != review.ledger_revision:
                raise PortError(
                    PortErrorCode.CONFLICT, "decide", "Budget/costs changed; prepare a new review"
                )
        if decision == OperatorDecision.APPROVE and submission:
            refresh(self.opportunities, self.source, self.clock, original.reference)
            assert review.content is not None
            stored = self.executions.get_content(review.content.reference)
            if stored != review.content:
                raise PortError(PortErrorCode.CONFLICT, "decide", "Reviewed content changed")
            check_content(stored, review.content.reference)
        self.approvals.save_decision(candidate)
        if updated != original:
            save(self.opportunities, current, updated)
        logging.getLogger(__name__).info(
            "operator_decision_recorded",
            extra={
                "review_reference": reference.value,
                "actor": self.operator.value,
                "decision": decision.value,
            },
        )
        return candidate
