from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from itertools import product
from typing import TypedDict, cast

import pytest

from agentmine.domain.eligibility import (
    AIParticipationPolicy,
    CountryCode,
    Deadline,
    DeadlineKind,
    EligibilityFacts,
    EligibilityPolicy,
    GeographicRestrictions,
    ParticipantProfile,
    PaymentRequirements,
    ProhibitedAction,
    Requirement,
    SubmissionSupport,
)
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.errors import DomainError
from agentmine.domain.values import Reference
from agentmine.domain.work import Eligibility, EligibilityReason, EligibilityStatus, TaskType


class FactChanges(TypedDict, total=False):
    is_open: bool | None
    deadline: Deadline
    ai_policy: AIParticipationPolicy
    geography: GeographicRestrictions | None
    account: Requirement
    identity: Requirement
    physical_presence: Requirement
    task_type: TaskType | str | None
    required_skills: frozenset[str] | None
    submission: SubmissionSupport
    payment: PaymentRequirements
    prohibited_actions: frozenset[ProhibitedAction] | None


def change(facts: EligibilityFacts, field: str, value: object) -> EligibilityFacts:
    """Typed constructor changes for the parameter tables below."""
    return replace(facts, **cast(FactChanges, {field: value}))


@pytest.fixture
def at() -> datetime:
    return datetime(2026, 10, 13, 12, tzinfo=UTC)


@pytest.fixture
def facts(at: datetime) -> EligibilityFacts:
    return EligibilityFacts(
        Reference("opportunity"),
        True,
        Deadline(DeadlineKind.AT, at + timedelta(hours=2)),
        AIParticipationPolicy.ALLOWED,
        GeographicRestrictions(),
        Requirement.NOT_REQUIRED,
        Requirement.NOT_REQUIRED,
        Requirement.NOT_REQUIRED,
        TaskType.RESEARCH,
        frozenset(),
        SubmissionSupport.AUTOMATIC,
        PaymentRequirements(False, False),
        frozenset(),
    )


@pytest.fixture
def engine() -> EligibilityEngine:
    return EligibilityEngine(EligibilityPolicy(timedelta(hours=1)))


@pytest.mark.parametrize(
    "task_type", [TaskType.RESEARCH, TaskType.DATA_PROCESSING, "research", "data_processing"]
)
def test_verified_rules_allow_supported_work_without_irrelevant_profile_facts(
    task_type: TaskType | str, facts: EligibilityFacts, engine: EligibilityEngine, at: datetime
) -> None:
    result = engine.evaluate(replace(facts, task_type=task_type), ParticipantProfile(), at)
    assert result.status == EligibilityStatus.ELIGIBLE
    assert result.reasons == (EligibilityReason.ALL_RULES_PASSED,)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("is_open", EligibilityReason.OPEN_STATUS_UNKNOWN),
        ("geography", EligibilityReason.GEOGRAPHIC_RESTRICTIONS_UNKNOWN),
        ("task_type", EligibilityReason.TASK_TYPE_UNKNOWN),
        ("required_skills", EligibilityReason.REQUIRED_SKILLS_UNKNOWN),
        ("prohibited_actions", EligibilityReason.PROHIBITED_ACTIONS_UNKNOWN),
    ],
)
def test_missing_facts_are_unknown_not_guessed(
    field: str,
    reason: EligibilityReason,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    result = engine.evaluate(change(facts, field, None), ParticipantProfile(), at)
    assert result.status == EligibilityStatus.UNKNOWN
    assert result.reasons == (reason,)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("deadline", Deadline(), EligibilityReason.DEADLINE_UNKNOWN),
        ("ai_policy", AIParticipationPolicy.UNKNOWN, EligibilityReason.AI_POLICY_UNKNOWN),
        ("account", Requirement.UNKNOWN, EligibilityReason.ACCOUNT_REQUIREMENT_UNKNOWN),
        ("identity", Requirement.UNKNOWN, EligibilityReason.IDENTITY_REQUIREMENT_UNKNOWN),
        ("physical_presence", Requirement.UNKNOWN, EligibilityReason.PHYSICAL_PRESENCE_UNKNOWN),
        ("submission", SubmissionSupport.UNKNOWN, EligibilityReason.SUBMISSION_SUPPORT_UNKNOWN),
        ("payment", PaymentRequirements(), EligibilityReason.PAYMENT_REQUIREMENTS_UNKNOWN),
    ],
)
def test_explicit_unknown_enums_do_not_default_to_eligible(
    field: str,
    value: object,
    reason: EligibilityReason,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    result = engine.evaluate(change(facts, field, value), ParticipantProfile(), at)
    assert result.status == EligibilityStatus.UNKNOWN
    assert result.reasons == (reason,)


def test_entirely_unknown_facts_report_all_missing_criteria(
    engine: EligibilityEngine, at: datetime
) -> None:
    result = engine.evaluate(EligibilityFacts(Reference("unknown")), ParticipantProfile(), at)
    assert result.status == EligibilityStatus.UNKNOWN
    assert len(result.reasons) == 12
    assert all(isinstance(reason, EligibilityReason) for reason in result.reasons)
    assert EligibilityReason.ALL_RULES_PASSED not in result.reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("is_open", False, EligibilityReason.OPPORTUNITY_CLOSED),
        ("ai_policy", AIParticipationPolicy.PROHIBITED, EligibilityReason.AI_NOT_ALLOWED),
        ("physical_presence", Requirement.REQUIRED, EligibilityReason.PHYSICAL_PRESENCE_REQUIRED),
        ("task_type", "coding", EligibilityReason.UNSUPPORTED_TASK_TYPE),
        ("task_type", "RESEARCH", EligibilityReason.UNSUPPORTED_TASK_TYPE),
        ("submission", SubmissionSupport.UNSUPPORTED, EligibilityReason.SUBMISSION_UNSUPPORTED),
        (
            "payment",
            PaymentRequirements(False, True),
            EligibilityReason.SENSITIVE_CREDENTIALS_REQUIRED,
        ),
    ],
)
def test_known_blockers_are_ineligible(
    field: str,
    value: object,
    reason: EligibilityReason,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    result = engine.evaluate(change(facts, field, value), ParticipantProfile(), at)
    assert result.status == EligibilityStatus.INELIGIBLE
    assert result.reasons == (reason,)


@pytest.mark.parametrize("action", list(ProhibitedAction))
def test_every_constitution_prohibited_action_is_blocked(
    action: ProhibitedAction, facts: EligibilityFacts, engine: EligibilityEngine, at: datetime
) -> None:
    result = engine.evaluate(
        replace(facts, prohibited_actions=frozenset({action})), ParticipantProfile(), at
    )
    assert result.status == EligibilityStatus.INELIGIBLE
    assert result.reasons == (EligibilityReason.PROHIBITED_ACTION,)


@pytest.mark.parametrize(
    ("requirement", "met", "status", "reason"),
    [
        (
            Requirement.NOT_REQUIRED,
            None,
            EligibilityStatus.ELIGIBLE,
            EligibilityReason.ALL_RULES_PASSED,
        ),
        (
            Requirement.NOT_REQUIRED,
            False,
            EligibilityStatus.ELIGIBLE,
            EligibilityReason.ALL_RULES_PASSED,
        ),
        (
            Requirement.REQUIRED,
            True,
            EligibilityStatus.ELIGIBLE,
            EligibilityReason.ALL_RULES_PASSED,
        ),
        (
            Requirement.REQUIRED,
            False,
            EligibilityStatus.INELIGIBLE,
            EligibilityReason.ACCOUNT_REQUIRED,
        ),
        (
            Requirement.REQUIRED,
            None,
            EligibilityStatus.UNKNOWN,
            EligibilityReason.ACCOUNT_STATUS_UNKNOWN,
        ),
        (
            Requirement.UNKNOWN,
            True,
            EligibilityStatus.UNKNOWN,
            EligibilityReason.ACCOUNT_REQUIREMENT_UNKNOWN,
        ),
    ],
)
def test_account_requirements_and_participant_capabilities(
    requirement: Requirement,
    met: bool | None,
    status: EligibilityStatus,
    reason: EligibilityReason,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    result = engine.evaluate(
        replace(facts, account=requirement), ParticipantProfile(account_requirement_met=met), at
    )
    assert result.status == status and result.reasons == (reason,)


@pytest.mark.parametrize("met", [None, False, True])
def test_identity_requirement_is_independent_from_account(
    met: bool | None, facts: EligibilityFacts, engine: EligibilityEngine, at: datetime
) -> None:
    result = engine.evaluate(
        replace(facts, identity=Requirement.REQUIRED),
        ParticipantProfile(account_requirement_met=True, identity_requirement_met=met),
        at,
    )
    expected = {
        None: EligibilityStatus.UNKNOWN,
        False: EligibilityStatus.INELIGIBLE,
        True: EligibilityStatus.ELIGIBLE,
    }
    reasons = {
        None: EligibilityReason.IDENTITY_STATUS_UNKNOWN,
        False: EligibilityReason.IDENTITY_REQUIRED,
        True: EligibilityReason.ALL_RULES_PASSED,
    }
    assert result.status == expected[met] and result.reasons == (reasons[met],)


@pytest.mark.parametrize("will_disclose", [None, False, True])
def test_ai_disclosure_is_not_assumed(
    will_disclose: bool | None, facts: EligibilityFacts, engine: EligibilityEngine, at: datetime
) -> None:
    result = engine.evaluate(
        replace(facts, ai_policy=AIParticipationPolicy.DISCLOSURE_REQUIRED),
        ParticipantProfile(will_disclose_ai=will_disclose),
        at,
    )
    expected = {
        None: EligibilityStatus.UNKNOWN,
        False: EligibilityStatus.INELIGIBLE,
        True: EligibilityStatus.ELIGIBLE,
    }
    reasons = {
        None: EligibilityReason.AI_DISCLOSURE_UNKNOWN,
        False: EligibilityReason.AI_DISCLOSURE_REQUIRED,
        True: EligibilityReason.ALL_RULES_PASSED,
    }
    assert result.status == expected[will_disclose] and result.reasons == (reasons[will_disclose],)


@pytest.mark.parametrize(
    ("allowed", "excluded", "country", "status"),
    [
        ((), (), None, EligibilityStatus.ELIGIBLE),
        (("VN",), (), "VN", EligibilityStatus.ELIGIBLE),
        (("US",), (), "VN", EligibilityStatus.INELIGIBLE),
        ((), ("VN",), "VN", EligibilityStatus.INELIGIBLE),
        (("VN",), ("VN",), "VN", EligibilityStatus.INELIGIBLE),
        (("VN",), (), None, EligibilityStatus.UNKNOWN),
        ((), ("US",), None, EligibilityStatus.UNKNOWN),
    ],
)
def test_geography_allow_exclude_and_missing_country(
    allowed: tuple[str, ...],
    excluded: tuple[str, ...],
    country: str | None,
    status: EligibilityStatus,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    geography = GeographicRestrictions(
        frozenset(CountryCode(code) for code in allowed),
        frozenset(CountryCode(code) for code in excluded),
    )
    result = engine.evaluate(
        replace(facts, geography=geography),
        ParticipantProfile(country=CountryCode(country) if country else None),
        at,
    )
    assert result.status == status
    if status == EligibilityStatus.INELIGIBLE:
        assert result.reasons == (EligibilityReason.COUNTRY_RESTRICTION,)


@pytest.mark.parametrize(
    ("available", "status", "reason"),
    [
        (None, EligibilityStatus.UNKNOWN, EligibilityReason.PARTICIPANT_SKILLS_UNKNOWN),
        (frozenset(), EligibilityStatus.INELIGIBLE, EligibilityReason.MISSING_REQUIRED_SKILL),
        (frozenset({"research"}), EligibilityStatus.ELIGIBLE, EligibilityReason.ALL_RULES_PASSED),
        (
            frozenset({"Research"}),
            EligibilityStatus.INELIGIBLE,
            EligibilityReason.MISSING_REQUIRED_SKILL,
        ),
        (
            frozenset({"research", "data"}),
            EligibilityStatus.ELIGIBLE,
            EligibilityReason.ALL_RULES_PASSED,
        ),
    ],
)
def test_required_skills_use_exact_canonical_names(
    available: frozenset[str] | None,
    status: EligibilityStatus,
    reason: EligibilityReason,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    result = engine.evaluate(
        replace(facts, required_skills=frozenset({"research"})),
        ParticipantProfile(skills=available),
        at,
    )
    assert result.status == status and result.reasons == (reason,)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "ai_policy",
            AIParticipationPolicy.HUMAN_REVIEW_REQUIRED,
            EligibilityReason.AI_POLICY_REVIEW_REQUIRED,
        ),
        ("submission", SubmissionSupport.MANUAL, EligibilityReason.MANUAL_SUBMISSION_REQUIRED),
        (
            "payment",
            PaymentRequirements(True, False),
            EligibilityReason.SUSPICIOUS_PAYMENT_REQUIREMENTS,
        ),
    ],
)
def test_human_review_never_becomes_automatic_eligibility(
    field: str,
    value: object,
    reason: EligibilityReason,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    result = engine.evaluate(change(facts, field, value), ParticipantProfile(), at)
    assert result.status == EligibilityStatus.REQUIRES_HUMAN_REVIEW
    assert result.reasons == (reason,)


@pytest.mark.parametrize(("blocked", "unknown", "review"), list(product([False, True], repeat=3)))
def test_status_precedence_and_all_combined_reasons(
    blocked: bool,
    unknown: bool,
    review: bool,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    changed = replace(
        facts,
        is_open=not blocked,
        ai_policy=AIParticipationPolicy.UNKNOWN if unknown else AIParticipationPolicy.ALLOWED,
        submission=SubmissionSupport.MANUAL if review else SubmissionSupport.AUTOMATIC,
    )
    result = engine.evaluate(changed, ParticipantProfile(), at)
    expected = (
        EligibilityStatus.INELIGIBLE
        if blocked
        else EligibilityStatus.UNKNOWN
        if unknown
        else EligibilityStatus.REQUIRES_HUMAN_REVIEW
        if review
        else EligibilityStatus.ELIGIBLE
    )
    assert result.status == expected
    assert (EligibilityReason.OPPORTUNITY_CLOSED in result.reasons) == blocked
    assert (EligibilityReason.AI_POLICY_UNKNOWN in result.reasons) == unknown
    assert (EligibilityReason.MANUAL_SUBMISSION_REQUIRED in result.reasons) == review
    assert len(result.reasons) == len(set(result.reasons))


@pytest.mark.parametrize(
    ("remaining", "status", "reason"),
    [
        (timedelta(seconds=-1), EligibilityStatus.INELIGIBLE, EligibilityReason.DEADLINE_EXPIRED),
        (timedelta(0), EligibilityStatus.INELIGIBLE, EligibilityReason.DEADLINE_EXPIRED),
        (
            timedelta(microseconds=1),
            EligibilityStatus.INELIGIBLE,
            EligibilityReason.INSUFFICIENT_TIME_REMAINING,
        ),
        (
            timedelta(hours=1) - timedelta(microseconds=1),
            EligibilityStatus.INELIGIBLE,
            EligibilityReason.INSUFFICIENT_TIME_REMAINING,
        ),
        (timedelta(hours=1), EligibilityStatus.ELIGIBLE, EligibilityReason.ALL_RULES_PASSED),
        (timedelta(days=100), EligibilityStatus.ELIGIBLE, EligibilityReason.ALL_RULES_PASSED),
    ],
)
def test_deadline_and_minimum_remaining_time_boundaries(
    remaining: timedelta,
    status: EligibilityStatus,
    reason: EligibilityReason,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    result = engine.evaluate(
        replace(facts, deadline=Deadline(DeadlineKind.AT, at + remaining)), ParticipantProfile(), at
    )
    assert result.status == status and result.reasons == (reason,)


def test_no_deadline_is_distinct_from_unknown_deadline(
    facts: EligibilityFacts, engine: EligibilityEngine, at: datetime
) -> None:
    no_deadline = engine.evaluate(
        replace(facts, deadline=Deadline(DeadlineKind.NONE)), ParticipantProfile(), at
    )
    unknown = engine.evaluate(replace(facts, deadline=Deadline()), ParticipantProfile(), at)
    assert no_deadline.status == EligibilityStatus.ELIGIBLE
    assert unknown.status == EligibilityStatus.UNKNOWN


def test_timezone_offset_does_not_change_evaluation(
    facts: EligibilityFacts, engine: EligibilityEngine, at: datetime
) -> None:
    shifted = replace(
        facts,
        deadline=Deadline(
            DeadlineKind.AT, (at + timedelta(hours=2)).astimezone(timezone(timedelta(hours=7)))
        ),
    )
    assert engine.evaluate(shifted, ParticipantProfile(), at) == engine.evaluate(
        facts, ParticipantProfile(), at
    )


class RepeatedHour(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=-5 if dt is not None and dt.fold else -4)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "Test repeated hour"


def test_remaining_time_uses_instants_across_repeated_local_hour(
    facts: EligibilityFacts, engine: EligibilityEngine
) -> None:
    zone = RepeatedHour()
    start = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    deadline = start.replace(fold=1)
    result = engine.evaluate(
        replace(facts, deadline=Deadline(DeadlineKind.AT, deadline)), ParticipantProfile(), start
    )
    assert (
        result.status == EligibilityStatus.ELIGIBLE
    )  # Exactly one real hour, not zero wall hours.


@pytest.mark.parametrize("country", ["", "vn", "VNM", "V1", "VÑ", " VN"])
def test_country_value_validation(country: str) -> None:
    with pytest.raises(DomainError):
        CountryCode(country)


def test_invalid_model_values_are_structured_errors(
    facts: EligibilityFacts, at: datetime, engine: EligibilityEngine
) -> None:
    with pytest.raises(DomainError):
        replace(facts, is_open=cast(bool, 1))
    with pytest.raises(DomainError):
        PaymentRequirements(cast(bool, "false"), False)
    with pytest.raises(DomainError):
        ParticipantProfile(skills=cast(frozenset[str], {"research"}))
    with pytest.raises(DomainError):
        replace(facts, required_skills=frozenset({" research "}))
    with pytest.raises(DomainError):
        replace(facts, ai_policy=cast(AIParticipationPolicy, "allowed"))
    with pytest.raises(DomainError):
        replace(facts, prohibited_actions=frozenset({cast(ProhibitedAction, "unknown-action")}))
    with pytest.raises(DomainError):
        EligibilityPolicy(timedelta(seconds=-1))
    with pytest.raises(DomainError):
        Deadline(DeadlineKind.AT)
    with pytest.raises(DomainError):
        Deadline(DeadlineKind.UNKNOWN, at)
    with pytest.raises(DomainError):
        Deadline(DeadlineKind.AT, at.replace(tzinfo=None))
    with pytest.raises(DomainError):
        engine.evaluate(facts, ParticipantProfile(), at.replace(tzinfo=None))


def test_every_result_has_unique_machine_readable_codes(
    facts: EligibilityFacts, engine: EligibilityEngine, at: datetime
) -> None:
    result = engine.evaluate(facts, ParticipantProfile(), at)
    assert tuple(reason.value for reason in result.reasons) == ("ALL_RULES_PASSED",)
    for reasons in (
        (),
        (EligibilityReason.ALL_RULES_PASSED,) * 2,
        (cast(EligibilityReason, "free-text"),),
    ):
        with pytest.raises(DomainError):
            Eligibility(EligibilityStatus.ELIGIBLE, "Description", reasons)
    assert Eligibility(EligibilityStatus.UNKNOWN, "Legacy assessment").reasons == (
        EligibilityReason.MANUAL_ASSESSMENT,
    )
    with pytest.raises(FrozenInstanceError):
        result.status = EligibilityStatus.INELIGIBLE  # type: ignore[misc]
    assert engine.evaluate(facts, ParticipantProfile(), at) == result


@pytest.mark.parametrize(("upfront", "secret"), list(product([None, False, True], repeat=2)))
def test_payment_flags_keep_partial_knowledge_and_precedence(
    upfront: bool | None,
    secret: bool | None,
    facts: EligibilityFacts,
    engine: EligibilityEngine,
    at: datetime,
) -> None:
    result = engine.evaluate(
        replace(facts, payment=PaymentRequirements(upfront, secret)), ParticipantProfile(), at
    )
    expected = (
        EligibilityStatus.INELIGIBLE
        if secret is True
        else EligibilityStatus.UNKNOWN
        if upfront is None or secret is None
        else EligibilityStatus.REQUIRES_HUMAN_REVIEW
        if upfront
        else EligibilityStatus.ELIGIBLE
    )
    assert result.status == expected
    assert (EligibilityReason.SUSPICIOUS_PAYMENT_REQUIREMENTS in result.reasons) == (
        upfront is True
    )
    assert (EligibilityReason.SENSITIVE_CREDENTIALS_REQUIRED in result.reasons) == (secret is True)
    assert (EligibilityReason.PAYMENT_REQUIREMENTS_UNKNOWN in result.reasons) == (
        upfront is None or secret is None
    )


def test_multiple_known_blockers_are_all_retained_in_stable_order(
    facts: EligibilityFacts, engine: EligibilityEngine, at: datetime
) -> None:
    changed = replace(
        facts,
        is_open=False,
        deadline=Deadline(DeadlineKind.AT, at),
        ai_policy=AIParticipationPolicy.PROHIBITED,
        geography=GeographicRestrictions(excluded=frozenset({CountryCode("VN")})),
        account=Requirement.REQUIRED,
        identity=Requirement.REQUIRED,
        physical_presence=Requirement.REQUIRED,
        task_type="coding",
        submission=SubmissionSupport.UNSUPPORTED,
        prohibited_actions=frozenset({ProhibitedAction.SECURITY_EXPLOITATION}),
    )
    result = engine.evaluate(
        changed,
        ParticipantProfile(
            country=CountryCode("VN"), account_requirement_met=False, identity_requirement_met=False
        ),
        at,
    )
    assert result.status == EligibilityStatus.INELIGIBLE
    assert result.reasons == (
        EligibilityReason.OPPORTUNITY_CLOSED,
        EligibilityReason.DEADLINE_EXPIRED,
        EligibilityReason.AI_NOT_ALLOWED,
        EligibilityReason.COUNTRY_RESTRICTION,
        EligibilityReason.ACCOUNT_REQUIRED,
        EligibilityReason.IDENTITY_REQUIRED,
        EligibilityReason.PHYSICAL_PRESENCE_REQUIRED,
        EligibilityReason.UNSUPPORTED_TASK_TYPE,
        EligibilityReason.SUBMISSION_UNSUPPORTED,
        EligibilityReason.PROHIBITED_ACTION,
    )
