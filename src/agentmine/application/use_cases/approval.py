"""Human review packages and explicit approvals; no autonomous approval or messaging."""

from dataclasses import dataclass

from agentmine.application.contracts.workflow import HumanReviewRequest
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.repositories import ExecutionRepository, OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.context import (
    check_content,
    load,
    refresh,
    require_state,
    save,
)
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import HumanApproval


@dataclass(frozen=True, slots=True)
class RequestHumanApproval:
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    clock: Clock

    def execute(self, reference: Reference) -> HumanReviewRequest:
        opportunity = load(self.opportunities, reference).value
        require_state(opportunity, OpportunityState.READY_FOR_HUMAN_REVIEW)
        assert opportunity.deliverable is not None and opportunity.qa is not None
        content = self.executions.get_content(opportunity.deliverable.content_reference)
        if content is None:
            raise PortError(PortErrorCode.INVALID_RESPONSE, "review", "Review content missing")
        check_content(content, opportunity.deliverable.content_reference)
        return HumanReviewRequest(
            reference, opportunity.deliverable, opportunity.qa, content, self.clock.now()
        )


@dataclass(frozen=True, slots=True)
class ApproveSubmission:
    opportunities: OpportunityRepository
    source: OpportunitySource
    clock: Clock

    def execute(self, reference: Reference, approval: HumanApproval) -> Opportunity:
        previous = load(self.opportunities, reference)
        if previous.value.approval == approval:
            return previous.value
        refresh(self.opportunities, self.source, self.clock, reference)
        if (
            approval.approved_at > self.clock.now()
            or previous.value.execution is None
            or approval.approved_at < previous.value.execution.started_at
        ):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "approve", "Approval time is invalid")
        return save(self.opportunities, previous, previous.value.approve(approval))
