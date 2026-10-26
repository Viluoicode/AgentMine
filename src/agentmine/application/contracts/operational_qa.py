"""Inspection ownership and conditional lifecycle completion; no new QA rules."""

from dataclasses import dataclass
from datetime import datetime

from agentmine.application.contracts.qa import QAInspection, lifecycle_qa_result
from agentmine.application.contracts.records import Versioned
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.qa import QAReport
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import Deliverable


@dataclass(frozen=True, slots=True)
class QAApplicationBinding:
    reference: Reference
    execution_reference: Reference
    deliverable: Deliverable
    opportunity_snapshot: Versioned[Opportunity]
    actor: Reference
    requested_at: datetime

    def __post_init__(self) -> None:
        for value in (self.reference, self.execution_reference, self.actor):
            require_reference(value, "qa_binding")
        require_aware_timestamp(self.requested_at)
        op = self.opportunity_snapshot.value
        if (
            op.state != OpportunityState.QA_PENDING
            or op.execution is None
            or op.execution.reference != self.execution_reference
            or self.deliverable != op.deliverable
            or self.deliverable.execution_reference != self.execution_reference
            or self.requested_at < op.execution.started_at
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "qa_binding",
                "Matching pending deliverable and execution required",
            )


@dataclass(frozen=True, slots=True)
class QACompletion:
    binding: QAApplicationBinding
    inspection: QAInspection
    report: QAReport

    def __post_init__(self) -> None:
        if (
            self.inspection.reference != self.binding.reference
            or self.report.reference != self.binding.reference
            or self.inspection.deliverable != self.binding.deliverable
            or self.report.deliverable != self.binding.deliverable
            or self.inspection.plan.execution != self.binding.opportunity_snapshot.value.execution
            or self.report.checked_at < self.binding.requested_at
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "qa_completion", "Matching bound QA evidence required"
            )

    @property
    def opportunity(self) -> Opportunity:
        result = lifecycle_qa_result(self.report)
        return (
            self.binding.opportunity_snapshot.value
            if result is None
            else self.binding.opportunity_snapshot.value.review_qa(result)
        )


@dataclass(frozen=True, slots=True)
class OperationalQAStatus:
    binding: QAApplicationBinding | None
    report: QAReport | None
    applied: bool
