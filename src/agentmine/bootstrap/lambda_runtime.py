"""Lambda composition from existing ports, independent of storage/provider selection."""

from collections.abc import Callable
from dataclasses import dataclass

from agentmine.application.ports.repositories import OpportunityRepository, SubmissionRepository
from agentmine.application.ports.services import (
    Clock,
    OpportunitySource,
    PaymentVerifier,
    SubmissionGateway,
)
from agentmine.application.use_cases import (
    DiscoverOpportunities,
    NormalizeOpportunity,
    TrackOutcome,
    VerifyPayment,
)
from agentmine.presentation.lambda_events import Workflow
from agentmine.presentation.lambda_handlers import (
    LambdaHandlers,
    RuntimeConfigurationError,
    UseCase,
)


@dataclass(frozen=True, slots=True)
class LambdaDependencies:
    opportunities: OpportunityRepository
    clock: Clock
    source: OpportunitySource | None = None
    submissions: SubmissionRepository | None = None
    gateway: SubmissionGateway | None = None
    verifier: PaymentVerifier | None = None


def create_lambda_handlers(factory: Callable[[Workflow], LambdaDependencies]) -> LambdaHandlers:
    """The deployment-owned factory selects adapters, never event-supplied config/imports."""

    def resolve(workflow: Workflow) -> UseCase:
        ports = factory(workflow)
        match workflow:
            case Workflow.NORMALIZE:
                return NormalizeOpportunity(ports.opportunities)
            case Workflow.DISCOVER if ports.source is not None:
                return DiscoverOpportunities(ports.source, ports.opportunities, ports.clock)
            case Workflow.TRACK_OUTCOME if (
                ports.submissions is not None and ports.gateway is not None
            ):
                return TrackOutcome(
                    ports.opportunities, ports.submissions, ports.gateway, ports.clock
                )
            case Workflow.VERIFY_PAYMENT if (
                ports.submissions is not None and ports.verifier is not None
            ):
                return VerifyPayment(
                    ports.opportunities, ports.verifier, ports.clock, ports.submissions
                )
            case _:
                raise RuntimeConfigurationError()

    return LambdaHandlers(resolve)
