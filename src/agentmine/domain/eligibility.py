"""Normalized facts and participant capabilities; absent evidence stays explicit."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import TaskType


class DeadlineKind(StrEnum):
    UNKNOWN = "unknown"
    NONE = "none"
    AT = "at"


@dataclass(frozen=True, slots=True)
class Deadline:
    kind: DeadlineKind = DeadlineKind.UNKNOWN
    at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DeadlineKind) or (self.kind == DeadlineKind.AT) != (
            self.at is not None
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "deadline", "Explicit deadline knowledge required"
            )
        if self.at is not None:
            require_aware_timestamp(self.at)


class AIParticipationPolicy(StrEnum):
    UNKNOWN = "unknown"
    ALLOWED = "allowed"
    PROHIBITED = "prohibited"
    DISCLOSURE_REQUIRED = "disclosure_required"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class Requirement(StrEnum):
    UNKNOWN = "unknown"
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


class SubmissionSupport(StrEnum):
    UNKNOWN = "unknown"
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    UNSUPPORTED = "unsupported"


class ProhibitedAction(StrEnum):
    CRYPTO_MINING = "crypto_mining"
    TRADING = "trading"
    TOKEN_CREATION = "token_creation"
    AUTONOMOUS_WALLET = "autonomous_wallet"
    CODING_EXECUTION = "coding_execution"
    SECURITY_EXPLOITATION = "security_exploitation"
    MULTI_AGENT_SWARM = "multi_agent_swarm"
    SAAS = "saas"
    MULTI_TENANCY = "multi_tenancy"


@dataclass(frozen=True, slots=True)
class CountryCode:
    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or len(self.value) != 2
            or not self.value.isascii()
            or not self.value.isalpha()
            or not self.value.isupper()
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "country", "Two uppercase ASCII letters required"
            )


@dataclass(frozen=True, slots=True)
class GeographicRestrictions:
    """Empty verified sets mean unrestricted; None at the facts boundary means unknown."""

    allowed: frozenset[CountryCode] = frozenset()
    excluded: frozenset[CountryCode] = frozenset()

    def __post_init__(self) -> None:
        for countries in (self.allowed, self.excluded):
            if not isinstance(countries, frozenset) or any(
                not isinstance(country, CountryCode) for country in countries
            ):
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "countries", "Immutable country codes required"
                )


def _optional_bool(value: bool | None, field: str) -> None:
    if value is not None and type(value) is not bool:
        raise DomainError(ErrorCode.INVALID_VALUE, field, "Boolean or explicit unknown required")


def _skills(value: frozenset[str] | None) -> None:
    if value is not None and (
        not isinstance(value, frozenset)
        or any(
            not isinstance(skill, str) or not skill.strip() or skill != skill.strip()
            for skill in value
        )
    ):
        raise DomainError(
            ErrorCode.INVALID_VALUE, "skills", "Immutable canonical skill names required"
        )


@dataclass(frozen=True, slots=True)
class PaymentRequirements:
    """Payment demands: upfront fee or handing private credentials to the requester."""

    upfront_fee: bool | None = None
    secret_credentials: bool | None = None

    def __post_init__(self) -> None:
        _optional_bool(self.upfront_fee, "upfront_fee")
        _optional_bool(self.secret_credentials, "secret_credentials")


@dataclass(frozen=True, slots=True)
class ParticipantProfile:
    country: CountryCode | None = None
    account_requirement_met: bool | None = None
    identity_requirement_met: bool | None = None
    will_disclose_ai: bool | None = None
    skills: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.country is not None and not isinstance(self.country, CountryCode):
            raise DomainError(ErrorCode.INVALID_VALUE, "country", "CountryCode or unknown required")
        for name in ("account_requirement_met", "identity_requirement_met", "will_disclose_ai"):
            _optional_bool(getattr(self, name), name)
        _skills(self.skills)


@dataclass(frozen=True, slots=True)
class EligibilityFacts:
    opportunity_reference: Reference
    is_open: bool | None = None
    deadline: Deadline = Deadline()
    ai_policy: AIParticipationPolicy = AIParticipationPolicy.UNKNOWN
    geography: GeographicRestrictions | None = None
    account: Requirement = Requirement.UNKNOWN
    identity: Requirement = Requirement.UNKNOWN
    physical_presence: Requirement = Requirement.UNKNOWN
    task_type: TaskType | str | None = None
    required_skills: frozenset[str] | None = None
    submission: SubmissionSupport = SubmissionSupport.UNKNOWN
    payment: PaymentRequirements = PaymentRequirements()
    prohibited_actions: frozenset[ProhibitedAction] | None = None

    def __post_init__(self) -> None:
        require_reference(self.opportunity_reference, "opportunity_reference")
        _optional_bool(self.is_open, "is_open")
        for name, value, expected in (
            ("deadline", self.deadline, Deadline),
            ("ai_policy", self.ai_policy, AIParticipationPolicy),
            ("account", self.account, Requirement),
            ("identity", self.identity, Requirement),
            ("physical_presence", self.physical_presence, Requirement),
            ("submission", self.submission, SubmissionSupport),
            ("payment", self.payment, PaymentRequirements),
        ):
            if not isinstance(value, expected):
                raise DomainError(ErrorCode.INVALID_VALUE, name, "Explicit domain value required")
        if self.geography is not None and not isinstance(self.geography, GeographicRestrictions):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "geography", "Explicit restrictions required"
            )
        if self.task_type is not None and (
            not isinstance(self.task_type, str) or not self.task_type.strip()
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "task_type", "Known task label or unknown required"
            )
        _skills(self.required_skills)
        if self.prohibited_actions is not None and (
            not isinstance(self.prohibited_actions, frozenset)
            or any(not isinstance(action, ProhibitedAction) for action in self.prohibited_actions)
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "actions", "Immutable prohibited actions required"
            )


@dataclass(frozen=True, slots=True)
class EligibilityPolicy:
    minimum_time_remaining: timedelta

    def __post_init__(self) -> None:
        if not isinstance(
            self.minimum_time_remaining, timedelta
        ) or self.minimum_time_remaining < timedelta(0):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "time", "Nonnegative time threshold required"
            )
