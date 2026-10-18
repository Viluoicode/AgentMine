"""Operator evidence of a completed manual submission; never sends externally."""

from dataclasses import dataclass
from datetime import datetime

from agentmine.application.contracts.submission import (
    SubmissionAttemptStatus,
    SubmissionMode,
    SubmissionResult,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.repositories import OpportunityRepository, SubmissionRepository
from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.context import load
from agentmine.application.use_cases.submission_result import retain_result
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.domain.work import Submission


@dataclass(frozen=True, slots=True)
class RecordManualSubmission:
    opportunities: OpportunityRepository
    submissions: SubmissionRepository
    clock: Clock
    operator: Reference

    def execute(
        self,
        opportunity_reference: Reference,
        submission_reference: Reference,
        submitted_at: datetime,
        evidence: Reference,
        external_submission_id: str | None,
        marketplace_response: str,
        external_url: str | None = None,
    ) -> SubmissionResult:
        require_aware_timestamp(submitted_at)
        previous = load(self.opportunities, opportunity_reference)
        request = self.submissions.get_request(submission_reference)
        if request is None or request.mode != SubmissionMode.MANUAL:
            raise PortError(
                PortErrorCode.CONFLICT, "manual_submission", "Retained manual intent required"
            )
        if (
            previous.value.deliverable != request.deliverable
            or previous.value.approval != request.approval
            or not request.approval.approved_at <= submitted_at <= self.clock.now()
        ):
            raise PortError(
                PortErrorCode.CONFLICT,
                "manual_submission",
                "Current approval and valid receipt time required",
            )
        receipt = Submission(
            request.reference,
            request.deliverable,
            request.qa,
            request.approval,
            request.target,
            evidence,
            submitted_at,
        )
        for attempt in self.submissions.attempts_for(request.reference):
            if attempt.status == SubmissionAttemptStatus.CONFIRMED:
                if (
                    attempt.submission != receipt
                    or attempt.external_submission_id != external_submission_id
                    or attempt.marketplace_response != marketplace_response
                    or attempt.external_url != external_url
                    or attempt.recorded_by != self.operator
                ):
                    raise PortError(
                        PortErrorCode.CONFLICT,
                        "manual_submission",
                        "Manual receipt already recorded differently",
                    )
                return retain_result(
                    self.opportunities, self.submissions, self.clock, previous, request, attempt
                )
        result = SubmissionResult(
            request.reference,
            SubmissionAttemptStatus.CONFIRMED,
            self.clock.now(),
            receipt,
            "Operator-reported receipt; acceptance and payment remain unknown",
            external_submission_id,
            marketplace_response,
            external_url,
            recorded_by=self.operator,
        )
        return retain_result(
            self.opportunities, self.submissions, self.clock, previous, request, result
        )
