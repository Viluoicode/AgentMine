"""Approved submission, observed outcome and verified payment orchestration."""

from dataclasses import dataclass

from agentmine.application.contracts.submission import (
    ManualSubmissionPackage,
    PaymentVerificationRequest,
    SubmissionAttemptStatus,
    SubmissionDispatch,
    SubmissionMode,
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
from agentmine.application.use_cases.submission_result import retain_result
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class SubmitTask:
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    submissions: SubmissionRepository
    gateway: SubmissionGateway | None
    source: OpportunitySource
    clock: Clock

    def execute(
        self,
        reference: Reference,
        submission_reference: Reference,
        mode: SubmissionMode = SubmissionMode.API,
    ) -> SubmissionResult:
        previous = load(self.opportunities, reference)
        opportunity = previous.value
        if opportunity.approval is not None and opportunity.approval.target.value.startswith(
            "submission-context:"
        ):
            raise PortError(
                PortErrorCode.UNSUPPORTED,
                "submit",
                "Offline context consent has no handoff or dispatch capability",
            )
        original = self.submissions.get_request(submission_reference)
        if original is not None and original.mode != mode:
            raise PortError(PortErrorCode.CONFLICT, "submit", "Submission mode changed")
        if opportunity.submission is not None:
            if opportunity.submission.reference != submission_reference:
                raise PortError(
                    PortErrorCode.CONFLICT, "submit", "Already submitted with another identity"
                )
            for attempt in self.submissions.attempts_for(submission_reference):
                if attempt.submission == opportunity.submission:
                    return attempt
            return SubmissionResult(
                submission_reference,
                SubmissionAttemptStatus.CONFIRMED,
                self.clock.now(),
                opportunity.submission,
                "Legacy confirmed receipt; metadata unavailable",
            )
        if opportunity.state != OpportunityState.SUBMISSION_IN_FLIGHT:
            require_state(opportunity, OpportunityState.APPROVED_FOR_SUBMISSION)
        elif original is None or mode != SubmissionMode.API:
            raise PortError(
                PortErrorCode.CONFLICT, "submit", "Matching in-flight API intent required"
            )
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
            mode,
        )
        if original is not None and original != request:
            raise PortError(PortErrorCode.CONFLICT, "submit", "Submission intent changed")
        attempts = self.submissions.attempts_for(submission_reference)
        ordered = sorted(
            attempts, key=lambda item: item.status != SubmissionAttemptStatus.CONFIRMED
        )
        for attempt in ordered:
            if (
                attempt.status
                in (
                    SubmissionAttemptStatus.CONFIRMED,
                    SubmissionAttemptStatus.FAILED,
                    SubmissionAttemptStatus.UNSUPPORTED,
                )
                or attempt.manual_package is not None
            ):
                return retain_result(
                    self.opportunities, self.submissions, self.clock, previous, request, attempt
                )
        confirmed = self.submissions.get(submission_reference)
        if confirmed is not None:
            result = SubmissionResult(
                submission_reference,
                SubmissionAttemptStatus.CONFIRMED,
                self.clock.now(),
                confirmed,
                "Recovered legacy confirmed receipt",
            )
        else:
            if mode == SubmissionMode.API and self.gateway is None:
                raise PortError(
                    PortErrorCode.UNSUPPORTED, "submit", "API gateway is not configured"
                )
            if original is None and mode != SubmissionMode.UNSUPPORTED:
                refresh(self.opportunities, self.source, self.clock, reference)
            if mode == SubmissionMode.API:
                claimed = (
                    self.submissions.claim_dispatch(SubmissionDispatch(request, previous))
                    if original is None
                    else False
                )
                # Reload the transaction's revision for receipt recovery. Permission
                # comes from the atomic claim, never from this separate read.
                previous = load(self.opportunities, reference)
                if claimed:
                    require_state(previous.value, OpportunityState.SUBMISSION_IN_FLIGHT)
            else:
                claimed = self.submissions.claim_request(request)
            if mode == SubmissionMode.UNSUPPORTED:
                result = SubmissionResult(
                    submission_reference,
                    SubmissionAttemptStatus.UNSUPPORTED,
                    self.clock.now(),
                    None,
                    "No supported submission mechanism; no external action",
                )
            elif mode == SubmissionMode.MANUAL:
                package = ManualSubmissionPackage(
                    request.reference,
                    request.target,
                    request.deliverable,
                    request.content,
                    (
                        "Check the approved destination and opportunity deadline/open status.",
                        "Check for a receipt first. Never resend an uncertain submission.",
                        "Send the exact approved content through the supported manual interface.",
                        "Retain send time, external ID, response and URL when available.",
                        "Record the receipt. Acceptance and payment require separate evidence.",
                    ),
                )
                result = SubmissionResult(
                    submission_reference,
                    SubmissionAttemptStatus.HUMAN_ACTION_REQUIRED,
                    self.clock.now(),
                    None,
                    "Operator submission required; package creation is not submission",
                    manual_package=package,
                )
            else:
                assert self.gateway is not None
                try:
                    result = (
                        self.gateway.submit(request) if claimed else self.gateway.reconcile(request)
                    )
                    if result.manual_package is not None:
                        raise PortError(
                            PortErrorCode.INVALID_RESPONSE,
                            "submit",
                            "API gateway cannot switch to manual mode",
                        )
                    return retain_result(
                        self.opportunities, self.submissions, self.clock, previous, request, result
                    )
                except Exception as error:
                    self.submissions.record_attempt(
                        SubmissionResult(
                            submission_reference,
                            SubmissionAttemptStatus.UNKNOWN,
                            self.clock.now(),
                            None,
                            "Dispatch or persistence unresolved; reconcile without resending",
                        )
                    )
                    if isinstance(error, PortError):
                        raise
                    raise PortError(
                        PortErrorCode.OUTCOME_UNKNOWN,
                        "submit",
                        "Submission unresolved; reconcile intent",
                    ) from None
        return retain_result(
            self.opportunities, self.submissions, self.clock, previous, request, result
        )


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
        retained = self.submissions.get_outcome(previous.value.submission.reference)
        if retained is not None:
            return save(self.opportunities, previous, previous.value.record_outcome(retained))
        history = self.submissions.outcome_history(previous.value.submission.reference)
        observation = next((item for item in history if item.outcome is not None), None)
        if observation is None:
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
        updated = (
            None
            if observation.outcome is None
            else previous.value.record_outcome(observation.outcome)
        )
        self.submissions.record_outcome_observation(observation)
        if observation.outcome is None or updated is None:
            return previous.value
        self.submissions.save_outcome(observation.outcome)
        return save(self.opportunities, previous, updated)


@dataclass(frozen=True, slots=True)
class VerifyPayment:
    opportunities: OpportunityRepository
    verifier: PaymentVerifier
    clock: Clock
    submissions: SubmissionRepository

    def execute(self, reference: Reference) -> Opportunity:
        previous = load(self.opportunities, reference)
        if previous.value.state == OpportunityState.PAID:
            return previous.value
        require_state(previous.value, OpportunityState.ACCEPTED)
        assert previous.value.submission is not None and previous.value.outcome is not None
        history = self.submissions.payment_history(previous.value.submission.reference)
        result = next((item for item in history if item.payment is not None), None)
        if result is None:
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
        updated = (
            None
            if result.payment is None
            else previous.value.verify_payment(result.payment, result.verification)
        )
        self.submissions.record_payment_observation(result)
        if updated is None:
            return previous.value
        return save(self.opportunities, previous, updated)
