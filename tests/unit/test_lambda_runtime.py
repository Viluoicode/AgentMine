"""Thin runtime boundaries exercised with real application use cases and offline ports."""

import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from history_fakes import make_world, progress

from agentmine.application.contracts.submission import PaymentStatus
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.bootstrap.lambda_runtime import LambdaDependencies, create_lambda_handlers
from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.opportunity import OpportunityState
from agentmine.presentation.lambda_events import Workflow
from agentmine.presentation.lambda_handlers import InvocationFailure, LambdaHandlers


@dataclass(frozen=True)
class Context:
    aws_request_id: str = "aws-request-1"


def test_discover_normalize_and_duplicate_delivery(caplog: pytest.LogCaptureFixture) -> None:
    world = make_world("op")
    calls: list[Workflow] = []

    def resolve(workflow: Workflow) -> LambdaDependencies:
        calls.append(workflow)
        return LambdaDependencies(world.opportunities, world.clock, world.source)

    handlers = create_lambda_handlers(resolve)
    event = {"schema_version": 1, "correlation_id": "job-123", "limit": 1}
    caplog.set_level(logging.INFO)
    for _ in range(2):
        result = handlers.discover(event, Context())
        assert result["data"] == {"opportunity_ids": ["op"], "count": 1, "continuation": None}
        assert result["correlation_id"] == "job-123" and result["request_id"] == "aws-request-1"
        json.dumps(result)
    assert world.opportunities.snapshots[world.reference].revision == 1
    normalize = {"schema_version": 1, "opportunity_id": "op"}
    for _ in range(2):
        assert handlers.normalize(normalize, Context())["data"]["state"] == "normalized"
    assert world.opportunities.snapshots[world.reference].revision == 2
    assert calls == [Workflow.DISCOVER, Workflow.DISCOVER, Workflow.NORMALIZE, Workflow.NORMALIZE]
    entries = [
        json.loads(record.message)
        for record in caplog.records
        if record.name.endswith("lambda_handlers")
    ]
    assert len(entries) == 8
    assert all(entry["request_id"] == "aws-request-1" for entry in entries)
    assert not world.provider.calls and world.gateway.submits == 0


def test_eventbridge_envelope_and_continuation() -> None:
    from agentmine.application.contracts.opportunities import OpportunityBatch
    from agentmine.domain.values import Reference

    world = make_world("op")
    # Source returns an opaque cursor; handler exposes it without looping/fetching more pages.
    from unittest.mock import patch

    event = {
        "source": "agentmine",
        "detail-type": "agentmine.discover",
        "id": "bridge-id",
        "detail": {"schema_version": 1, "limit": 1, "continuation": "cursor-1"},
    }
    handlers = create_lambda_handlers(
        lambda _: LambdaDependencies(world.opportunities, world.clock, world.source)
    )
    with patch.object(
        type(world.source),
        "discover",
        return_value=OpportunityBatch(world.source.observations, Reference("cursor-2")),
    ) as discover:
        result = handlers.discover(event, Context())
        assert result["correlation_id"] == "bridge-id"
        assert result["data"]["continuation"] == "cursor-2"
        assert discover.call_count == 1
        request = discover.call_args.args[0]
        assert request.continuation == Reference("cursor-1")


def test_outcome_and_payment_keep_business_invariants_and_retry_evidence() -> None:
    world = make_world("op")
    progress(world, OpportunityState.SUBMITTED)
    handlers = create_lambda_handlers(
        lambda _: LambdaDependencies(
            world.opportunities,
            world.clock,
            submissions=world.submissions,
            gateway=world.gateway,
            verifier=world.verifier,
        )
    )
    event = {"schema_version": 1, "opportunity_id": "op"}
    assert handlers.track_outcome(event, Context())["data"]["state"] == "accepted"
    assert world.current().verified_revenue.amount == 0
    assert handlers.verify_payment(event, Context())["data"]["state"] == "accepted"
    world.verifier.status = PaymentStatus.VERIFIED
    assert handlers.verify_payment(event, Context())["data"]["state"] == "paid"
    assert handlers.verify_payment(event, Context())["data"]["state"] == "paid"
    assert world.verifier.calls == 2
    assert world.current().verified_revenue.amount == 85


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "raw-json",
        {},
        {"schema_version": True},
        {"schema_version": 2},
        {"schema_version": 1, "limit": True},
        {"schema_version": 1, "limit": 0},
        {"schema_version": 1, "limit": 101},
        {"schema_version": 1, "continuation": 1},
        {"schema_version": 1, "correlation_id": "unsafe\nlog"},
        {"schema_version": 1, "credentials": "PRIVATE"},
        {"schema_version": 1, "table": "attacker-selected"},
        {"source": "wrong", "detail-type": "agentmine.discover", "detail": {"schema_version": 1}},
        {
            "source": "agentmine",
            "detail-type": "agentmine.normalize",
            "detail": {"schema_version": 1},
        },
        {"source": "agentmine", "detail-type": "agentmine.discover", "detail": []},
    ],
)
def test_invalid_event_is_rejected_before_dependency_resolution(event: object) -> None:
    def forbidden(_: Workflow) -> LambdaDependencies:
        pytest.fail("Invalid event must not construct clients or access persistence")

    with pytest.raises(InvocationFailure) as error:
        create_lambda_handlers(forbidden).discover(event, Context())
    assert error.value.code == "invalid_event"


@pytest.mark.parametrize("identifier", [None, 1, "", " ", "x" * 2049])
def test_opportunity_identifier_required(identifier: object) -> None:
    def forbidden(_: Workflow) -> LambdaDependencies:
        pytest.fail("No resolution expected")

    with pytest.raises(InvocationFailure) as error:
        create_lambda_handlers(forbidden).normalize(
            {"schema_version": 1, "opportunity_id": identifier}, Context()
        )
    assert error.value.code == "invalid_event"


@pytest.mark.parametrize(
    ("raised", "code", "retry", "reconcile"),
    [
        (PortError(PortErrorCode.UNAVAILABLE, "SECRET", "PRIVATE"), "unavailable", True, False),
        (PortError(PortErrorCode.CONFLICT, "SECRET", "PRIVATE"), "conflict", True, False),
        (
            PortError(PortErrorCode.OUTCOME_UNKNOWN, "SECRET", "PRIVATE"),
            "outcome_unknown",
            False,
            True,
        ),
        (
            ApplicationError(ApplicationErrorCode.INVALID_STATE, "SECRET", "PRIVATE"),
            "invalid_state",
            False,
            False,
        ),
        (
            DomainError(ErrorCode.INVALID_TRANSITION, "SECRET", "PRIVATE"),
            "invalid_transition",
            False,
            False,
        ),
        (RuntimeError("PRIVATE"), "internal_error", False, False),
    ],
)
def test_failures_are_sanitized_and_raised_for_async_invocation(
    raised: Exception, code: str, retry: bool, reconcile: bool, caplog: pytest.LogCaptureFixture
) -> None:
    def unavailable(_: Workflow) -> LambdaDependencies:
        raise raised

    with pytest.raises(InvocationFailure) as error:
        create_lambda_handlers(unavailable).discover({"schema_version": 1}, Context())
    assert error.value.code == code and error.value.retryable == retry
    assert error.value.reconciliation_required == reconcile
    assert "PRIVATE" not in str(error.value) + caplog.text
    assert "SECRET" not in str(error.value) + caplog.text
    assert error.value.__suppress_context__
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.parametrize("workflow", ["discover", "track_outcome", "verify_payment"])
def test_unconfigured_external_adapter_fails_closed(workflow: str) -> None:
    world = make_world("op")
    handlers = create_lambda_handlers(
        lambda _: LambdaDependencies(world.opportunities, world.clock)
    )
    event: dict[str, object] = {"schema_version": 1}
    if workflow != "discover":
        event["opportunity_id"] = "op"
    with pytest.raises(InvocationFailure) as error:
        getattr(handlers, workflow)(event, Context())
    assert error.value.code == "runtime_not_configured"


def test_use_case_error_does_not_become_success_or_expose_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = make_world("op")
    handlers = create_lambda_handlers(
        lambda _: LambdaDependencies(world.opportunities, world.clock)
    )
    with pytest.raises(InvocationFailure) as error:
        handlers.normalize({"schema_version": 1, "opportunity_id": "PRIVATE"}, Context())
    assert error.value.code == "not_found"
    assert "PRIVATE" not in caplog.text + str(error.value)


def test_missing_context_generates_safe_correlation_and_bad_binding_fails() -> None:
    world = make_world("op")
    from agentmine.application.use_cases import NormalizeOpportunity

    handlers = LambdaHandlers(lambda _: NormalizeOpportunity(world.opportunities))
    with pytest.raises(InvocationFailure) as error:
        handlers.discover({"schema_version": 1}, SimpleNamespace(aws_request_id="unsafe\nPRIVATE"))
    assert error.value.code == "runtime_not_configured"
    payload = json.loads(str(error.value))
    assert len(payload["request_id"]) == 36 and "PRIVATE" not in str(error.value)
