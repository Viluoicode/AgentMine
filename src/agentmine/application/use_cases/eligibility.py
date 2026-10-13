"""Refresh availability, evaluate pure rules and persist pending/resolved decisions."""

from dataclasses import dataclass, replace

from agentmine.application.contracts.eligibility import EligibilityCheckRequest
from agentmine.application.ports.repositories import OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.context import load, observe_status, save
from agentmine.domain.eligibility import Deadline, DeadlineKind
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.opportunity import Opportunity, OpportunityState


@dataclass(frozen=True, slots=True)
class CheckEligibility:
    opportunities: OpportunityRepository
    source: OpportunitySource
    clock: Clock
    engine: EligibilityEngine

    def execute(self, request: EligibilityCheckRequest) -> Opportunity:
        reference = request.facts.opportunity_reference
        previous = load(self.opportunities, reference)
        status = observe_status(self.opportunities, self.source, self.clock, reference)
        deadline = (
            Deadline()
            if not status.deadline_known
            else Deadline(DeadlineKind.AT, status.deadline)
            if status.deadline is not None
            else Deadline(DeadlineKind.NONE)
        )
        facts = replace(request.facts, is_open=status.is_open, deadline=deadline)
        assessment = self.engine.evaluate(facts, request.profile, self.clock.now())
        if previous.value.eligibility == assessment:
            return previous.value
        checking = previous.value
        if checking.state != OpportunityState.ELIGIBILITY_CHECK:
            checking = checking.check_eligibility()
        return save(self.opportunities, previous, checking.assess_eligibility(assessment))
