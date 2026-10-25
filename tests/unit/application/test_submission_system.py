"""Modes, receipt metadata, conservative retries and explicit manual evidence."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest
from fakes import FakeGateway, FakeSubmissions
from test_use_cases import World, approved, plan, world

from agentmine.application.contracts.submission import (
    SubmissionAttemptStatus,
    SubmissionMode,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.use_cases.manual_submission import RecordManualSubmission
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import Submission

__all__ = ["world"]


@pytest.mark.parametrize("mode", list(SubmissionMode))
def test_all_modes_require_approval(world: World, mode: SubmissionMode) -> None:
    plan(world)
    with pytest.raises(ApplicationError):
        world.submit_task().execute(world.reference, Reference("send"), mode)
    assert world.gateway.submits == world.gateway.reconciles == 0
    assert not world.submissions.requests


@pytest.mark.parametrize("mode", [SubmissionMode.MANUAL, SubmissionMode.UNSUPPORTED])
def test_non_api_modes_never_call_gateway(world: World, mode: SubmissionMode) -> None:
    before = approved(world)
    submit = world.submit_task()
    result = submit.execute(world.reference, Reference("send"), mode)
    assert world.current() == before
    assert world.gateway.submits == world.gateway.reconciles == 0
    assert result.submission is None and result.submission_timestamp is None
    if mode == SubmissionMode.MANUAL:
        assert result.status == SubmissionAttemptStatus.HUMAN_ACTION_REQUIRED
        assert result.manual_package is not None
        assert result.manual_package.deliverable == before.deliverable
        assert result.manual_package.target == before.approval.target if before.approval else False
        assert result.manual_package.instructions
        assert "resend" in " ".join(result.manual_package.instructions)
    else:
        assert result.status == SubmissionAttemptStatus.UNSUPPORTED
        assert result.manual_package is None
    world.clock.instant += timedelta(seconds=5)
    assert submit.execute(world.reference, Reference("send"), mode) == result
    with pytest.raises(PortError):
        submit.execute(world.reference, Reference("send"), SubmissionMode.API)
    with pytest.raises(PortError):
        submit.execute(world.reference, Reference("different"), mode)


class MetadataGateway(FakeGateway):
    fail: bool = False
    invalid: bool = False

    def submit(self, request: SubmissionRequest) -> SubmissionResult:
        if self.fail:
            self.submits += 1
            raise RuntimeError("SECRET_PROVIDER_DETAIL")
        return self.enrich(super().submit(request))

    def reconcile(self, request: SubmissionRequest) -> SubmissionResult:
        return self.enrich(super().reconcile(request))

    def enrich(self, result: SubmissionResult) -> SubmissionResult:
        if self.invalid:
            return replace(result, observed_at=self.clock.now() + timedelta(days=1))
        return replace(
            result,
            external_submission_id="remote-123",
            marketplace_response='{"status":"received"}',
            external_url="https://example.test/submissions/123",
        )


@pytest.mark.parametrize("failure", ["", "timeout", "invalid"])
def test_api_retry_metadata_and_unknown_reconciliation(world: World, failure: str) -> None:
    approved(world)
    gateway = MetadataGateway(world.clock)
    gateway.fail, gateway.invalid = failure == "timeout", failure == "invalid"
    submit = replace(world.submit_task(), gateway=gateway)
    if failure:
        with pytest.raises(PortError) as error:
            submit.execute(world.reference, Reference("send"))
        assert "SECRET" not in str(error.value)
        assert world.current().state == OpportunityState.SUBMISSION_IN_FLIGHT
        assert world.submissions.attempts[-1].status == SubmissionAttemptStatus.UNKNOWN
        gateway.fail = gateway.invalid = False
        with pytest.raises(PortError):
            submit.execute(world.reference, Reference("different"))
    result = submit.execute(world.reference, Reference("send"))
    assert result.external_submission_id == "remote-123"
    assert result.marketplace_response == '{"status":"received"}'
    assert result.external_url == "https://example.test/submissions/123"
    assert result.submission_timestamp == world.clock.now()
    assert world.current().state == OpportunityState.SUBMITTED
    assert world.current().outcome is None and world.current().payment is None
    world.clock.instant += timedelta(seconds=10)
    assert submit.execute(world.reference, Reference("send")) == result
    assert gateway.submits == 1
    assert gateway.reconciles == (1 if failure else 0)


class FailingReceiptStore(FakeSubmissions):
    fail: bool = True

    def save(self, submission: Submission) -> None:
        if self.fail:
            raise PortError(PortErrorCode.UNAVAILABLE, "save", "Injected failure")
        super().save(submission)


@pytest.mark.parametrize("failure", ["receipt", "opportunity"])
def test_confirmation_recovery_never_dispatches_again(world: World, failure: str) -> None:
    approved(world)
    gateway = MetadataGateway(world.clock)
    store = FailingReceiptStore(opportunities=world.opportunities)
    store.fail = failure == "receipt"
    submit = replace(world.submit_task(), gateway=gateway, submissions=store)
    original_submit = gateway.submit

    def fail_after_dispatch(request: SubmissionRequest) -> SubmissionResult:
        result = original_submit(request)
        world.opportunities.fail_save = failure == "opportunity"
        return result

    with patch.object(gateway, "submit", fail_after_dispatch), pytest.raises(PortError):
        submit.execute(world.reference, Reference("send"))
    assert any(attempt.status == SubmissionAttemptStatus.CONFIRMED for attempt in store.attempts)
    world.opportunities.fail_save = store.fail = False
    result = submit.execute(world.reference, Reference("send"))
    assert result.external_submission_id == "remote-123"
    assert gateway.submits == 1 and gateway.reconciles == 0
    assert world.current().state == OpportunityState.SUBMITTED


def test_known_failure_is_retained_without_retry(world: World) -> None:
    approved(world)

    class RejectedGateway(MetadataGateway):
        def submit(self, request: SubmissionRequest) -> SubmissionResult:
            self.submits += 1
            return SubmissionResult(
                request.reference,
                SubmissionAttemptStatus.FAILED,
                self.clock.now(),
                None,
                "Provider refused request",
                marketplace_response='{"error":"invalid attachment"}',
            )

    gateway = RejectedGateway(world.clock)
    submit = replace(world.submit_task(), gateway=gateway)
    result = submit.execute(world.reference, Reference("send"))
    assert submit.execute(world.reference, Reference("send")) == result
    assert gateway.submits == 1 and gateway.reconciles == 0
    assert world.current().state == OpportunityState.SUBMISSION_IN_FLIGHT


@pytest.mark.parametrize("recover", [False, True])
def test_manual_receipt_and_recovery(world: World, recover: bool) -> None:
    approved(world)
    package = world.submit_task().execute(
        world.reference, Reference("manual"), SubmissionMode.MANUAL
    )
    recorder = RecordManualSubmission(
        world.opportunities, world.submissions, world.clock, Reference("operator")
    )
    sent_at = world.clock.now()
    args = (
        world.reference,
        Reference("manual"),
        sent_at,
        Reference("receipt-proof"),
        "manual-123",
        "Received by marketplace",
        "https://example.test/manual/123",
    )
    if recover:
        world.opportunities.fail_save = True
        with pytest.raises(PortError):
            recorder.execute(*args)
        world.opportunities.fail_save = False
        # SubmitTask must prefer the retained confirmation over the earlier package.
        result = world.submit_task().execute(
            world.reference, Reference("manual"), SubmissionMode.MANUAL
        )
    else:
        result = recorder.execute(*args)
    world.clock.instant += timedelta(seconds=10)
    assert recorder.execute(*args) == result
    assert result.recorded_by == Reference("operator")
    assert result.submission_timestamp == sent_at
    assert package.submission is None
    assert world.current().state == OpportunityState.SUBMITTED
    assert world.current().outcome is None and world.current().payment is None
    assert world.gateway.submits == world.gateway.reconciles == 0
    with pytest.raises(PortError):
        recorder.execute(
            world.reference,
            Reference("manual"),
            sent_at,
            Reference("other-proof"),
            "changed",
            "Different response",
        )


@pytest.mark.parametrize("mode", [SubmissionMode.API, SubmissionMode.UNSUPPORTED])
def test_manual_receipt_cannot_confirm_other_modes(world: World, mode: SubmissionMode) -> None:
    approved(world)
    world.submit_task().execute(world.reference, Reference("send"), mode)
    with pytest.raises(PortError):
        RecordManualSubmission(
            world.opportunities, world.submissions, world.clock, Reference("operator")
        ).execute(
            world.reference,
            Reference("send"),
            world.clock.now(),
            Reference("proof"),
            "id",
            "Received",
        )


@pytest.mark.parametrize("delta", [-1, 1])
def test_manual_receipt_time_is_bounded(world: World, delta: int) -> None:
    approved(world)
    world.submit_task().execute(world.reference, Reference("manual"), SubmissionMode.MANUAL)
    with pytest.raises(PortError):
        RecordManualSubmission(
            world.opportunities, world.submissions, world.clock, Reference("operator")
        ).execute(
            world.reference,
            Reference("manual"),
            world.clock.now() + timedelta(days=delta),
            Reference("proof"),
            None,
            "Receipt",
        )
    assert world.current().state == OpportunityState.APPROVED_FOR_SUBMISSION


def test_manual_and_unsupported_work_without_api_adapter(world: World) -> None:
    approved(world)
    result = replace(world.submit_task(), gateway=None).execute(
        world.reference, Reference("manual"), SubmissionMode.MANUAL
    )
    assert result.manual_package is not None


def test_api_requires_configured_gateway(world: World) -> None:
    approved(world)
    with pytest.raises(PortError):
        replace(world.submit_task(), gateway=None).execute(world.reference, Reference("send"))
    assert not world.submissions.requests
