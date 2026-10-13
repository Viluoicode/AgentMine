"""Pure deterministic rules. All criteria run; known blockers dominate incomplete facts."""

from dataclasses import dataclass
from datetime import UTC, datetime

from agentmine.domain.eligibility import (
    AIParticipationPolicy,
    DeadlineKind,
    EligibilityFacts,
    EligibilityPolicy,
    ParticipantProfile,
    Requirement,
    SubmissionSupport,
)
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.values import require_aware_timestamp
from agentmine.domain.work import Eligibility, EligibilityReason, EligibilityStatus, TaskType


@dataclass(frozen=True, slots=True)
class EligibilityEngine:
    policy: EligibilityPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.policy, EligibilityPolicy):
            raise DomainError(ErrorCode.INVALID_VALUE, "policy", "EligibilityPolicy required")

    def evaluate(
        self, facts: EligibilityFacts, profile: ParticipantProfile, at: datetime
    ) -> Eligibility:
        require_aware_timestamp(at)
        blockers: list[EligibilityReason] = []
        unknowns: list[EligibilityReason] = []
        reviews: list[EligibilityReason] = []
        ordered: list[EligibilityReason] = []

        def add(group: list[EligibilityReason], reason: EligibilityReason) -> None:
            group.append(reason)
            ordered.append(reason)

        if facts.is_open is None:
            add(unknowns, EligibilityReason.OPEN_STATUS_UNKNOWN)
        elif not facts.is_open:
            add(blockers, EligibilityReason.OPPORTUNITY_CLOSED)
        remaining = None
        if facts.deadline.kind == DeadlineKind.UNKNOWN:
            add(unknowns, EligibilityReason.DEADLINE_UNKNOWN)
        elif facts.deadline.at is not None:
            remaining = facts.deadline.at.astimezone(UTC) - at.astimezone(UTC)
            if remaining.total_seconds() <= 0:
                add(blockers, EligibilityReason.DEADLINE_EXPIRED)

        match facts.ai_policy:
            case AIParticipationPolicy.UNKNOWN:
                add(unknowns, EligibilityReason.AI_POLICY_UNKNOWN)
            case AIParticipationPolicy.PROHIBITED:
                add(blockers, EligibilityReason.AI_NOT_ALLOWED)
            case AIParticipationPolicy.HUMAN_REVIEW_REQUIRED:
                add(reviews, EligibilityReason.AI_POLICY_REVIEW_REQUIRED)
            case AIParticipationPolicy.DISCLOSURE_REQUIRED:
                if profile.will_disclose_ai is None:
                    add(unknowns, EligibilityReason.AI_DISCLOSURE_UNKNOWN)
                elif not profile.will_disclose_ai:
                    add(blockers, EligibilityReason.AI_DISCLOSURE_REQUIRED)

        geography = facts.geography
        if geography is None:
            add(unknowns, EligibilityReason.GEOGRAPHIC_RESTRICTIONS_UNKNOWN)
        elif geography.allowed or geography.excluded:
            if profile.country is None:
                add(unknowns, EligibilityReason.COUNTRY_UNKNOWN)
            elif profile.country in geography.excluded or (
                geography.allowed and profile.country not in geography.allowed
            ):
                add(blockers, EligibilityReason.COUNTRY_RESTRICTION)

        for requirement, met, requirement_unknown, status_unknown, missing in (
            (
                facts.account,
                profile.account_requirement_met,
                EligibilityReason.ACCOUNT_REQUIREMENT_UNKNOWN,
                EligibilityReason.ACCOUNT_STATUS_UNKNOWN,
                EligibilityReason.ACCOUNT_REQUIRED,
            ),
            (
                facts.identity,
                profile.identity_requirement_met,
                EligibilityReason.IDENTITY_REQUIREMENT_UNKNOWN,
                EligibilityReason.IDENTITY_STATUS_UNKNOWN,
                EligibilityReason.IDENTITY_REQUIRED,
            ),
        ):
            if requirement == Requirement.UNKNOWN:
                add(unknowns, requirement_unknown)
            elif requirement == Requirement.REQUIRED:
                if met is None:
                    add(unknowns, status_unknown)
                elif not met:
                    add(blockers, missing)

        if facts.physical_presence == Requirement.UNKNOWN:
            add(unknowns, EligibilityReason.PHYSICAL_PRESENCE_UNKNOWN)
        elif facts.physical_presence == Requirement.REQUIRED:
            add(blockers, EligibilityReason.PHYSICAL_PRESENCE_REQUIRED)
        if facts.task_type is None:
            add(unknowns, EligibilityReason.TASK_TYPE_UNKNOWN)
        elif facts.task_type not in (TaskType.RESEARCH, TaskType.DATA_PROCESSING):
            add(blockers, EligibilityReason.UNSUPPORTED_TASK_TYPE)
        if facts.required_skills is None:
            add(unknowns, EligibilityReason.REQUIRED_SKILLS_UNKNOWN)
        elif facts.required_skills:
            if profile.skills is None:
                add(unknowns, EligibilityReason.PARTICIPANT_SKILLS_UNKNOWN)
            elif not facts.required_skills <= profile.skills:
                add(blockers, EligibilityReason.MISSING_REQUIRED_SKILL)

        match facts.submission:
            case SubmissionSupport.UNKNOWN:
                add(unknowns, EligibilityReason.SUBMISSION_SUPPORT_UNKNOWN)
            case SubmissionSupport.UNSUPPORTED:
                add(blockers, EligibilityReason.SUBMISSION_UNSUPPORTED)
            case SubmissionSupport.MANUAL:
                add(reviews, EligibilityReason.MANUAL_SUBMISSION_REQUIRED)
        if (
            remaining is not None
            and remaining.total_seconds() > 0
            and remaining < self.policy.minimum_time_remaining
        ):
            add(blockers, EligibilityReason.INSUFFICIENT_TIME_REMAINING)
        if facts.payment.upfront_fee is True:
            add(reviews, EligibilityReason.SUSPICIOUS_PAYMENT_REQUIREMENTS)
        if facts.payment.secret_credentials is True:
            add(blockers, EligibilityReason.SENSITIVE_CREDENTIALS_REQUIRED)
        if facts.payment.upfront_fee is None or facts.payment.secret_credentials is None:
            add(unknowns, EligibilityReason.PAYMENT_REQUIREMENTS_UNKNOWN)
        if facts.prohibited_actions is None:
            add(unknowns, EligibilityReason.PROHIBITED_ACTIONS_UNKNOWN)
        elif facts.prohibited_actions:
            add(blockers, EligibilityReason.PROHIBITED_ACTION)

        status = (
            EligibilityStatus.INELIGIBLE
            if blockers
            else EligibilityStatus.UNKNOWN
            if unknowns
            else EligibilityStatus.REQUIRES_HUMAN_REVIEW
            if reviews
            else EligibilityStatus.ELIGIBLE
        )
        reasons = tuple(ordered) if ordered else (EligibilityReason.ALL_RULES_PASSED,)
        return Eligibility(status, "; ".join(reason.value for reason in reasons), reasons)
