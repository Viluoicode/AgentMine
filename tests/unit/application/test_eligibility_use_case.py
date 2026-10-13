from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fakes import FakeClock, FakeOpportunities, FakeSource, economic_inputs, eligibility_request

from agentmine.application.contracts.eligibility import EligibilityCheckRequest
from agentmine.application.contracts.opportunities import (
    DiscoveryRequest,
    OpportunityObservation,
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.contracts.workflow import PlanTaskRequest
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.use_cases import (
    CheckEligibility,
    DiscoverOpportunities,
    EvaluateOpportunity,
    NormalizeOpportunity,
    PlanTask,
)
from agentmine.domain.eligibility import (
    AIParticipationPolicy,
    CountryCode,
    Deadline,
    DeadlineKind,
    EligibilityPolicy,
    GeographicRestrictions,
    ParticipantProfile,
    PaymentRequirements,
    SubmissionSupport,
)
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import Reward
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import EligibilityReason, EligibilityStatus, TaskType


@dataclass
class Case:
    clock: FakeClock
    source: FakeSource
    repository: FakeOpportunities
    request: EligibilityCheckRequest
    checker: CheckEligibility


@pytest.fixture
def case() -> Case:
    clock = FakeClock(datetime(2026, 10, 13, tzinfo=UTC))
    opportunity = Opportunity(
        Reference("opportunity"), "Research", Reward(Money(Decimal(100), "USD"))
    )
    observation = OpportunityObservation(
        opportunity,
        Reference("source"),
        "Requirements",
        clock.now(),
        True,
        clock.now() + timedelta(days=1),
    )
    source = FakeSource(clock, (observation,), deadline=observation.deadline)
    repository = FakeOpportunities()
    DiscoverOpportunities(source, repository, clock).execute(DiscoveryRequest(1))
    NormalizeOpportunity(repository).execute(opportunity.reference)
    return Case(
        clock,
        source,
        repository,
        eligibility_request(opportunity.reference),
        CheckEligibility(
            repository, source, clock, EligibilityEngine(EligibilityPolicy(timedelta(hours=1)))
        ),
    )


def test_engine_is_used_instead_of_accepting_an_asserted_assessment(case: Case) -> None:
    result = case.checker.execute(case.request)
    assert result.state == OpportunityState.ELIGIBLE
    assert result.eligibility is not None
    assert result.eligibility.reasons == (EligibilityReason.ALL_RULES_PASSED,)
    assert case.source.refreshes == 1


def test_unknown_stays_pending_and_can_resolve_when_evidence_arrives(case: Case) -> None:
    unknown = replace(
        case.request, facts=replace(case.request.facts, ai_policy=AIParticipationPolicy.UNKNOWN)
    )
    first = case.checker.execute(unknown)
    assert first.state == OpportunityState.ELIGIBILITY_CHECK
    assert first.eligibility is not None and first.eligibility.status == EligibilityStatus.UNKNOWN
    assert first.eligibility.reasons == (EligibilityReason.AI_POLICY_UNKNOWN,)
    revision = case.repository.snapshots[first.reference].revision
    assert case.checker.execute(unknown) == first
    assert case.repository.snapshots[first.reference].revision == revision
    assert case.checker.execute(case.request).state == OpportunityState.ELIGIBLE


def test_human_review_stays_pending_and_cannot_evaluate_or_plan(case: Case) -> None:
    request = replace(
        case.request, facts=replace(case.request.facts, payment=PaymentRequirements(True, False))
    )
    result = case.checker.execute(request)
    assert result.state == OpportunityState.ELIGIBILITY_CHECK
    assert result.eligibility is not None
    assert result.eligibility.status == EligibilityStatus.REQUIRES_HUMAN_REVIEW
    assert result.eligibility.reasons == (EligibilityReason.SUSPICIOUS_PAYMENT_REQUIREMENTS,)
    with pytest.raises(DomainError):
        EvaluateOpportunity(case.repository, case.source, case.clock).execute(
            result.reference, economic_inputs()
        )
    with pytest.raises(DomainError):
        PlanTask(case.repository, case.source, case.clock).execute(
            PlanTaskRequest(result.reference, Reference("task"), TaskType.RESEARCH, "Research")
        )


@pytest.mark.parametrize("closed", [True, False])
def test_refreshed_closed_or_expired_opportunity_returns_machine_reasons(
    case: Case, closed: bool
) -> None:
    if closed:
        case.source.is_open = False
    else:
        case.source.deadline = case.clock.now()
    result = case.checker.execute(case.request)
    assert result.state == OpportunityState.INELIGIBLE
    assert result.eligibility is not None
    assert result.eligibility.reasons == (
        EligibilityReason.OPPORTUNITY_CLOSED if closed else EligibilityReason.DEADLINE_EXPIRED,
    )


def test_unknown_source_status_is_not_guessed_from_caller_facts(case: Case) -> None:
    case.source.is_open = None
    case.source.deadline = None
    case.source.deadline_known = False
    request = replace(
        case.request,
        facts=replace(case.request.facts, is_open=True, deadline=Deadline(DeadlineKind.NONE)),
    )
    result = case.checker.execute(request)
    assert result.eligibility is not None
    assert result.eligibility.status == EligibilityStatus.UNKNOWN
    assert result.eligibility.reasons == (
        EligibilityReason.OPEN_STATUS_UNKNOWN,
        EligibilityReason.DEADLINE_UNKNOWN,
    )
    with pytest.raises(ApplicationError) as caught:
        PlanTask(case.repository, case.source, case.clock).execute(
            PlanTaskRequest(result.reference, Reference("task"), TaskType.RESEARCH, "Research")
        )
    assert caught.value.code == ApplicationErrorCode.UNRESOLVED
    case.source.is_open = True
    case.source.deadline_known = True  # Verified no deadline.
    assert case.checker.execute(case.request).state == OpportunityState.ELIGIBLE


def test_country_restriction_persists_machine_reason(case: Case) -> None:
    request = replace(
        case.request,
        facts=replace(
            case.request.facts,
            geography=GeographicRestrictions(allowed=frozenset({CountryCode("US")})),
        ),
        profile=ParticipantProfile(country=CountryCode("VN")),
    )
    result = case.checker.execute(request)
    assert result.eligibility is not None
    assert result.eligibility.status == EligibilityStatus.INELIGIBLE
    assert result.eligibility.reasons == (EligibilityReason.COUNTRY_RESTRICTION,)


def test_manual_submission_is_pending_human_review(case: Case) -> None:
    result = case.checker.execute(
        replace(
            case.request, facts=replace(case.request.facts, submission=SubmissionSupport.MANUAL)
        )
    )
    assert result.eligibility is not None
    assert result.eligibility.status == EligibilityStatus.REQUIRES_HUMAN_REVIEW
    assert result.eligibility.reasons == (EligibilityReason.MANUAL_SUBMISSION_REQUIRED,)


def test_closed_status_dominates_unknown_policy_but_retains_both_reasons(case: Case) -> None:
    case.source.is_open = False
    result = case.checker.execute(
        replace(
            case.request, facts=replace(case.request.facts, ai_policy=AIParticipationPolicy.UNKNOWN)
        )
    )
    assert result.eligibility is not None
    assert result.eligibility.status == EligibilityStatus.INELIGIBLE
    assert result.eligibility.reasons == (
        EligibilityReason.OPPORTUNITY_CLOSED,
        EligibilityReason.AI_POLICY_UNKNOWN,
    )


class WrongSource(FakeSource):
    def refresh(self, request: RefreshOpportunityRequest) -> OpportunityStatus:
        return replace(super().refresh(request), opportunity_reference=Reference("other"))


class StaleSource(FakeSource):
    def refresh(self, request: RefreshOpportunityRequest) -> OpportunityStatus:
        return replace(
            super().refresh(request), observed_at=self.clock.now() - timedelta(seconds=1)
        )


@pytest.mark.parametrize("source_type", [WrongSource, StaleSource])
def test_bad_source_response_cannot_create_eligibility(
    case: Case, source_type: type[FakeSource]
) -> None:
    source = source_type(case.clock, case.source.observations, deadline=case.source.deadline)
    with pytest.raises(PortError) as caught:
        replace(case.checker, source=source).execute(case.request)
    assert caught.value.code == PortErrorCode.INVALID_RESPONSE
    assert (
        case.repository.snapshots[case.request.facts.opportunity_reference].value.state
        == OpportunityState.NORMALIZED
    )


def test_conditional_write_failure_does_not_advance_lifecycle(case: Case) -> None:
    case.repository.fail_save = True
    with pytest.raises(PortError):
        case.checker.execute(case.request)
    assert (
        case.repository.snapshots[case.request.facts.opportunity_reference].value.eligibility
        is None
    )


def test_source_unknown_contract_distinguishes_no_deadline_and_bad_values(case: Case) -> None:
    unknown = OpportunityStatus(
        case.request.facts.opportunity_reference,
        Reference("source"),
        case.clock.now(),
        None,
        None,
        False,
    )
    assert unknown.is_open is None and not unknown.deadline_known
    with pytest.raises(DomainError):
        replace(unknown, deadline=case.clock.now())


def test_discovery_can_retain_unknown_availability_without_guessing(case: Case) -> None:
    original = case.source.observations[0]
    observation = replace(
        original,
        opportunity=Opportunity(
            Reference("unknown-opportunity"), "Research", original.opportunity.potential_reward
        ),
        is_open=None,
        deadline=None,
        deadline_known=False,
    )
    case.source.observations = (observation,)
    DiscoverOpportunities(case.source, case.repository, case.clock).execute(DiscoveryRequest(1))
    stored = case.repository.get_observation(observation.opportunity.reference)
    assert stored is not None and stored.is_open is None and not stored.deadline_known
