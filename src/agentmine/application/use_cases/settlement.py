"""Approved submission, observed outcome and verified payment orchestration."""

from dataclasses import dataclass

from agentmine.application.contracts.submission import (
    PaymentVerificationRequest,
    SubmissionAttemptStatus,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.repositories import (
    ExecutionRepository,
    OpportunityRepository,
    SubmissionRepository,
)
from agentmine.application.ports.services import (
    Clock,
    OpportunitySource,
    PaymentVerifier,
    SubmissionGateway,
)
from agentmine.application.use_cases.context import (
    check_content,
    load,
    refresh,
    require_state,
    save,
)
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class SubmitTask:
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    submissions: SubmissionRepository
    gateway: SubmissionGateway
    source: OpportunitySource
    clock: Clock

    def execute(self, reference: Reference, submission_reference: Reference) -> SubmissionResult:
        previous = load(self.opportunities, reference)
        opportunity = previous.value
        if opportunity.submission is not None:
            if opportunity.submission.reference != submission_reference:
                raise PortError(
                    PortErrorCode.CONFLICT, "submit", "Already submitted with another identity"
                )
            return SubmissionResult(
                submission_reference,
                SubmissionAttemptStatus.CONFIRMED,
                self.clock.now(),
                opportunity.submission,
                "Already confirmed",
            )
        require_state(opportunity, OpportunityState.APPROVED_FOR_SUBMISSION)
        assert (
            opportunity.deliverable is not None
            and opportunity.qa is not None
            and opportunity.approval is not None
        )
        content = self.executions.get_content(opportunity.deliverable.content_reference)
        if content is None:
            raise PortError(PortErrorCode.INVALID_RESPONSE, "submit", "Approved content missing")
        check_content(content, opportunity.deliverable.content_reference)
        request = SubmissionRequest(
            submission_reference,
            opportunity.deliverable,
            opportunity.qa,
            opportunity.approval,
            opportunity.approval.target,
            content,
        )
        original = self.submissions.get_request(submission_reference)
        if original is not None and original != request:
            raise PortError(PortErrorCode.CONFLICT, "submit", "Submission intent changed")
        confirmed = self.submissions.get(submission_reference)
        if confirmed is not None:
            result = SubmissionResult(
                submission_reference,
                SubmissionAttemptStatus.CONFIRMED,
                self.clock.now(),
                confirmed,
                "Recovered confirmed receipt",
            )
        else:
            if original is None:
                refresh(self.opportunities, self.source, self.clock, reference)
            claimed = self.submissions.claim_request(request)
            # Existing intents reconcile even if now expired: the effect may already exist.
            try:
                result = (
                    self.gateway.submit(request) if claimed else self.gateway.reconcile(request)
                )
            except PortError:
                self.submissions.record_attempt(
                    SubmissionResult(
                        submission_reference,
                        SubmissionAttemptStatus.UNKNOWN,
                        self.clock.now(),
                        None,
                        "Adapter failure; reconcile intent",
                    )
                )
                raise
        if result.reference != submission_reference or result.observed_at > self.clock.now():
            raise PortError(PortErrorCode.INVALID_RESPONSE, "submit", "Submission result mismatch")
        updated: Opportunity | None = None
        if result.submission is not None:
            if result.submission.target != request.target:
                raise PortError(PortErrorCode.INVALID_RESPONSE, "submit", "Receipt target mismatch")
            updated = opportunity.submit(result.submission)
        self.submissions.record_attempt(result)
        if result.submission is not None and updated is not None:
            self.submissions.save(result.submission)
            save(self.opportunities, previous, updated)
        return result


@dataclass(frozen=True, slots=True)
class TrackOutcome:
    opportunities: OpportunityRepository
    submissions: SubmissionRepository
    gateway: SubmissionGateway
    clock: Clock

    def execute(self, reference: Reference) -> Opportunity:
        previous = load(self.opportunities, reference)
        if previous.value.outcome is not None:
            return previous.value
        require_state(previous.value, OpportunityState.SUBMITTED)
        assert previous.value.submission is not None
        observation = self.gateway.track_outcome(previous.value.submission)
        if (
            observation.submission_reference != previous.value.submission.reference
            or not previous.value.submission.submitted_at
            <= observation.observed_at
            <= self.clock.now()
        ):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "outcome", "Outcome observation mismatch"
            )
        if observation.outcome is None:
            return previous.value
        updated = previous.value.record_outcome(observation.outcome)
        self.submissions.save_outcome(observation.outcome)
        return save(self.opportunities, previous, updated)


@dataclass(frozen=True, slots=True)
class VerifyPayment:
    opportunities: OpportunityRepository
    verifier: PaymentVerifier
    clock: Clock

    def execute(self, reference: Reference) -> Opportunity:
        previous = load(self.opportunities, reference)
        if previous.value.state == OpportunityState.PAID:
            return previous.value
        require_state(previous.value, OpportunityState.ACCEPTED)
        assert previous.value.submission is not None and previous.value.outcome is not None
        result = self.verifier.verify_payment(
            PaymentVerificationRequest(previous.value.submission, previous.value.outcome)
        )
        if (
            result.submission_reference != previous.value.submission.reference
            or not previous.value.submission.submitted_at <= result.observed_at <= self.clock.now()
        ):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "payment", "Payment observation mismatch"
            )
        if result.payment is None:
            return previous.value
        return save(self.opportunities, previous, previous.value.verify_payment(result.payment))
