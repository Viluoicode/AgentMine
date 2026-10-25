"""Refresh availability, evaluate pure rules and persist pending/resolved decisions."""

from dataclasses import dataclass

from agentmine.application.contracts.eligibility import (
    EligibilityCheckRequest,
    EligibilityInspection,
)
from agentmine.application.ports.repositories import OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.context import load, observe_status, save
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.opportunity import Opportunity, OpportunityState


@dataclass(frozen=True, slots=True)
class CheckEligibility:
    opportunities: OpportunityRepository
    source: OpportunitySource
    clock: Clock
    engine: EligibilityEngine

    def inspect(self, request: EligibilityCheckRequest) -> EligibilityInspection:
        status = observe_status(
            self.opportunities, self.source, self.clock, request.facts.opportunity_reference
        )
        fresh = request.refreshed(status)
        now = self.clock.now()
        return EligibilityInspection(
            fresh, status, self.engine.evaluate(fresh.facts, fresh.profile, now), now
        )

    def execute(self, request: EligibilityCheckRequest) -> Opportunity:
        reference = request.facts.opportunity_reference
        previous = load(self.opportunities, reference)
        assessment = self.inspect(request).result
        if previous.value.eligibility == assessment:
            return previous.value
        checking = previous.value
        if checking.state != OpportunityState.ELIGIBILITY_CHECK:
            checking = checking.check_eligibility()
        return save(self.opportunities, previous, checking.assess_eligibility(assessment))
