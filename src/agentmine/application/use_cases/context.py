"""Shared workflow preconditions and content integrity, without mutable context."""

from hashlib import sha256

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.opportunities import (
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.contracts.records import OpportunitySave, Versioned
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.ports.repositories import OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference, require_aware_timestamp


def load(repository: OpportunityRepository, reference: Reference) -> Versioned[Opportunity]:
    snapshot = repository.get(reference)
    if snapshot is None:
        raise ApplicationError(ApplicationErrorCode.NOT_FOUND, "load", "Opportunity not found")
    if snapshot.value.reference != reference:
        raise PortError(PortErrorCode.INVALID_RESPONSE, "load", "Opportunity identity mismatch")
    return snapshot


def save(
    repository: OpportunityRepository, previous: Versioned[Opportunity], updated: Opportunity
) -> Opportunity:
    return repository.save(OpportunitySave(updated, previous.revision)).value


def require_state(opportunity: Opportunity, state: OpportunityState) -> None:
    if opportunity.state != state:
        raise ApplicationError(
            ApplicationErrorCode.INVALID_STATE, "workflow", f"Action requires {state}"
        )


def observe_status(
    repository: OpportunityRepository, source: OpportunitySource, clock: Clock, reference: Reference
) -> OpportunityStatus:
    observation = repository.get_observation(reference)
    if observation is None or observation.opportunity.reference != reference:
        raise ApplicationError(
            ApplicationErrorCode.NOT_FOUND, "refresh", "Source provenance missing"
        )
    started_at = clock.now()
    require_aware_timestamp(started_at)
    status = source.refresh(RefreshOpportunityRequest(reference, observation.source_reference))
    now = clock.now()
    require_aware_timestamp(now)
    if (
        status.opportunity_reference != reference
        or status.source_reference != observation.source_reference
        or not started_at <= status.observed_at <= now
    ):
        raise PortError(PortErrorCode.INVALID_RESPONSE, "refresh", "Fresh matching status required")
    return status


def refresh(
    repository: OpportunityRepository, source: OpportunitySource, clock: Clock, reference: Reference
) -> OpportunityStatus:
    status = observe_status(repository, source, clock, reference)
    now = clock.now()
    if status.is_open is None or not status.deadline_known:
        raise ApplicationError(
            ApplicationErrorCode.UNRESOLVED, "refresh", "Availability is unknown"
        )
    if status.deadline is not None and now >= status.deadline:
        raise ApplicationError(
            ApplicationErrorCode.EXPIRED, "refresh", "Opportunity deadline passed"
        )
    if not status.is_open:
        raise ApplicationError(ApplicationErrorCode.CLOSED, "refresh", "Opportunity is closed")
    return status


def content_reference(text: str) -> Reference:
    return Reference("sha256:" + sha256(text.encode("utf-8")).hexdigest())


def check_content(content: ReferencedText, expected: Reference) -> None:
    if content.reference != expected or content_reference(content.text) != expected:
        raise PortError(
            PortErrorCode.INVALID_RESPONSE, "content", "Approved content digest mismatch"
        )
