"""Operator decision values and explicit revision lifecycle invariants."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agentmine.domain.approval import (
    ApprovalAction,
    ApprovalDecision,
    ApprovalScope,
    OperatorDecision,
)
from agentmine.domain.errors import DomainError
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference


@pytest.mark.parametrize("reason", ["", " ", "x" * 4001])
def test_invalid_decision_reason(reason: str) -> None:
    with pytest.raises(DomainError):
        ApprovalDecision(
            Reference("review"),
            Reference("operator"),
            datetime.now(UTC),
            OperatorDecision.APPROVE,
            reason,
        )


def test_approval_requires_aware_time() -> None:
    with pytest.raises(DomainError):
        ApprovalDecision(
            Reference("review"),
            Reference("operator"),
            datetime(2026, 10, 17),
            OperatorDecision.APPROVE,
        )


@pytest.mark.parametrize("action", [ApprovalAction.EXTERNAL_SUBMISSION, ApprovalAction.SPENDING])
def test_action_requires_its_bound_evidence(action: ApprovalAction) -> None:
    with pytest.raises(DomainError):
        ApprovalScope(action, Reference("destination"), Reference("payload"))


def test_submission_digest_and_revision_binding(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    opportunity = lifecycle[OpportunityState.READY_FOR_HUMAN_REVIEW]
    deliverable = opportunity.deliverable
    assert deliverable is not None
    with pytest.raises(DomainError):
        ApprovalScope(
            ApprovalAction.EXTERNAL_SUBMISSION,
            Reference("destination"),
            Reference("different-content"),
            deliverable,
        )
    revised = opportunity.request_revision()
    assert revised.approval is None and revised.deliverable is None
    with pytest.raises(DomainError):
        revised.finish(deliverable)
    pending = revised.finish(replace(deliverable, version=deliverable.version + 1))
    assert pending.state == OpportunityState.QA_PENDING
    assert pending.approval is None


@pytest.mark.parametrize(
    "state",
    [state for state in OpportunityState if state != OpportunityState.READY_FOR_HUMAN_REVIEW],
)
def test_revision_only_from_human_review(
    state: OpportunityState, lifecycle: dict[OpportunityState, Opportunity]
) -> None:
    with pytest.raises(DomainError):
        lifecycle[state].request_revision()
