"""Shared validation and durable receipt recovery for API and manual submission."""

import logging

from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.submission import SubmissionRequest, SubmissionResult
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.repositories import OpportunityRepository, SubmissionRepository
from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.context import save
from agentmine.domain.opportunity import Opportunity


def retain_result(
    opportunities: OpportunityRepository,
    submissions: SubmissionRepository,
    clock: Clock,
    previous: Versioned[Opportunity],
    request: SubmissionRequest,
    result: SubmissionResult,
) -> SubmissionResult:
    if (
        result.reference != request.reference
        or not request.approval.approved_at <= result.observed_at <= clock.now()
    ):
        raise PortError(
            PortErrorCode.INVALID_RESPONSE, "submit", "Submission result identity/time mismatch"
        )
    receipt = result.submission
    if receipt is not None and (
        receipt.deliverable != request.deliverable
        or receipt.qa != request.qa
        or receipt.approval != request.approval
        or receipt.target != request.target
    ):
        raise PortError(
            PortErrorCode.INVALID_RESPONSE, "submit", "Receipt does not match approved request"
        )
    if result.manual_package is not None and (
        result.manual_package.target != request.target
        or result.manual_package.deliverable != request.deliverable
        or result.manual_package.content != request.content
    ):
        raise PortError(
            PortErrorCode.INVALID_RESPONSE, "submit", "Manual package does not match approval"
        )
    updated = None
    if receipt is not None and previous.value.submission != receipt:
        updated = previous.value.submit(receipt)
    # Evidence first: a later receipt/aggregate failure reuses this result without another send.
    submissions.record_attempt(result)
    if receipt is not None:
        submissions.save(receipt)
        if updated is not None:
            save(opportunities, previous, updated)
    logging.getLogger(__name__).info(
        "submission_observed",
        extra={
            "submission_reference": result.reference.value,
            "submission_status": result.status.value,
            "mode": request.mode.value,
        },
    )
    return result
