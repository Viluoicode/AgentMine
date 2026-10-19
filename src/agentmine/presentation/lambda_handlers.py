"""Thin two-argument Lambda callables with explicit per-invocation resolution."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict
from uuid import uuid4

from agentmine.application.contracts.opportunities import DiscoveryRequest
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.use_cases import (
    DiscoverOpportunities,
    NormalizeOpportunity,
    TrackOutcome,
    VerifyPayment,
)
from agentmine.domain.errors import DomainError
from agentmine.domain.values import Reference
from agentmine.presentation.lambda_events import (
    InvalidEvent,
    Workflow,
    parse_event,
    safe_identifier,
)

type UseCase = DiscoverOpportunities | NormalizeOpportunity | TrackOutcome | VerifyPayment
type ResultData = dict[str, str | int | None | list[str]]


class InvocationResult(TypedDict):
    ok: bool
    workflow: str
    correlation_id: str
    request_id: str
    data: ResultData


class RuntimeConfigurationError(Exception):
    """Missing deployment dependency; never includes configuration values."""


class InvocationFailure(Exception):
    """Sanitized exception: raising makes asynchronous Lambda failures visible."""

    def __init__(
        self,
        code: str,
        workflow: Workflow,
        correlation_id: str,
        request_id: str,
        *,
        retryable: bool = False,
        reconciliation_required: bool = False,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.reconciliation_required = reconciliation_required
        super().__init__(
            json.dumps(
                {
                    "ok": False,
                    "code": code,
                    "workflow": workflow.value,
                    "correlation_id": correlation_id,
                    "request_id": request_id,
                    "retryable": retryable,
                    "reconciliation_required": reconciliation_required,
                },
                sort_keys=True,
            )
        )


def failure(
    error: Exception, workflow: Workflow, correlation: str, request_id: str
) -> InvocationFailure:
    code, retryable, reconcile = "internal_error", False, False
    if isinstance(error, InvalidEvent):
        code = "invalid_event"
    elif isinstance(error, RuntimeConfigurationError):
        code = "runtime_not_configured"
    elif isinstance(error, (ApplicationError, DomainError)):
        code = error.code.value
    elif isinstance(error, PortError):
        code = error.code.value
        retryable = error.code in (PortErrorCode.UNAVAILABLE, PortErrorCode.CONFLICT)
        reconcile = error.code == PortErrorCode.OUTCOME_UNKNOWN
    return InvocationFailure(
        code,
        workflow,
        correlation,
        request_id,
        retryable=retryable,
        reconciliation_required=reconcile,
    )


def invoke(
    workflow: Workflow, event: object, context: object, resolve: Callable[[Workflow], UseCase]
) -> InvocationResult:
    request_id = safe_identifier(getattr(context, "aws_request_id", None)) or str(uuid4())
    correlation = request_id
    logger = logging.getLogger(__name__)
    try:
        parsed = parse_event(event, workflow)  # Reject input before resolving any dependencies.
        correlation = parsed.correlation_id or request_id
        logger.info(
            json.dumps(
                {
                    "event": "invocation_started",
                    "workflow": workflow.value,
                    "correlation_id": correlation,
                    "request_id": request_id,
                }
            )
        )
        use_case = resolve(workflow)
        data: ResultData
        if workflow == Workflow.DISCOVER:
            if not isinstance(use_case, DiscoverOpportunities) or not isinstance(
                parsed.request, DiscoveryRequest
            ):
                raise RuntimeConfigurationError()
            batch = use_case.execute(parsed.request)
            data = {
                "opportunity_ids": [
                    item.opportunity.reference.value for item in batch.observations
                ],
                "count": len(batch.observations),
                "continuation": None if batch.continuation is None else batch.continuation.value,
            }
        else:
            expected = {
                Workflow.NORMALIZE: NormalizeOpportunity,
                Workflow.TRACK_OUTCOME: TrackOutcome,
                Workflow.VERIFY_PAYMENT: VerifyPayment,
            }
            if not isinstance(use_case, expected[workflow]) or not isinstance(
                parsed.request, Reference
            ):
                raise RuntimeConfigurationError()
            assert not isinstance(use_case, DiscoverOpportunities)
            opportunity = use_case.execute(parsed.request)
            data = {"opportunity_id": opportunity.reference.value, "state": opportunity.state.value}
        logger.info(
            json.dumps(
                {
                    "event": "invocation_succeeded",
                    "workflow": workflow.value,
                    "correlation_id": correlation,
                    "request_id": request_id,
                }
            )
        )
        return {
            "ok": True,
            "workflow": workflow.value,
            "correlation_id": correlation,
            "request_id": request_id,
            "data": data,
        }
    except Exception as error:
        mapped = failure(error, workflow, correlation, request_id)
        logger.error(str(mapped))  # Never log event bodies, exception messages or traceback locals.
        raise mapped from None


@dataclass(frozen=True, slots=True)
class LambdaHandlers:
    """Immutable callables; resolution is invoked each time, never cached globally."""

    resolve: Callable[[Workflow], UseCase]

    def discover(self, event: object, context: object) -> InvocationResult:
        return invoke(Workflow.DISCOVER, event, context, self.resolve)

    def normalize(self, event: object, context: object) -> InvocationResult:
        return invoke(Workflow.NORMALIZE, event, context, self.resolve)

    def track_outcome(self, event: object, context: object) -> InvocationResult:
        return invoke(Workflow.TRACK_OUTCOME, event, context, self.resolve)

    def verify_payment(self, event: object, context: object) -> InvocationResult:
        return invoke(Workflow.VERIFY_PAYMENT, event, context, self.resolve)
