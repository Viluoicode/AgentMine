"""Historical test factory and memory implementation, without external calls."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fakes import (
    FakeClock,
    FakeEvaluations,
    FakeExecutions,
    FakeGateway,
    FakeLedger,
    FakeOpportunities,
    FakeProvider,
    FakeSource,
    FakeSubmissions,
    FakeVerifier,
)
from test_outcome_payment import OutcomeGateway
from test_use_cases import World, plan, scored, usd, work_request

from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.contracts.records import OpportunitySave, Versioned
from agentmine.application.contracts.submission import PaymentStatus
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.settlement import TrackOutcome, VerifyPayment
from agentmine.domain.budget import Budget, BudgetPolicy
from agentmine.domain.finance import Reward
from agentmine.domain.history import HistoricalObservation, HistoricalQuery, latest_observations
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import HumanApproval, OutcomeStatus, QAResult, QAStatus, TaskType


@dataclass
class MemoryHistory:
    items: dict[Reference, HistoricalObservation] = field(default_factory=dict)

    def get(self, reference: Reference) -> HistoricalObservation | None:
        return self.items.get(reference)

    def for_opportunity(self, reference: Reference) -> tuple[HistoricalObservation, ...]:
        return tuple(
            sorted(
                (item for item in self.items.values() if item.opportunity.reference == reference),
                key=lambda item: item.sequence,
            )
        )

    def append(
        self, observation: HistoricalObservation, expected_previous: Reference | None
    ) -> None:
        existing = self.get(observation.reference)
        if existing is not None:
            if existing != observation:
                raise PortError(PortErrorCode.CONFLICT, "history", "Observation ID conflict")
            return
        prior = self.for_opportunity(observation.opportunity.reference)
        previous = prior[-1] if prior else None
        if (None if previous is None else previous.reference) != expected_previous:
            raise PortError(PortErrorCode.CONFLICT, "history", "Sequence changed")
        observation.require_successor(previous)
        self.items[observation.reference] = observation

    def latest(self, query: HistoricalQuery) -> tuple[HistoricalObservation, ...]:
        return latest_observations(tuple(self.items.values()), query)


def make_world(identifier: str) -> World:
    clock = FakeClock(datetime(2026, 10, 18, tzinfo=UTC))
    opportunity = Opportunity(Reference(identifier), "Research/Data work", Reward(usd("100")))
    observation = OpportunityObservation(
        opportunity,
        Reference("listing:" + identifier),
        "Approved requirements",
        clock.now(),
        True,
        clock.now() + timedelta(days=1),
    )
    return World(
        clock,
        FakeSource(clock, (observation,), deadline=observation.deadline),
        FakeOpportunities(),
        FakeEvaluations(),
        FakeExecutions(),
        FakeLedger(
            {
                Reference("ledger"): Versioned(
                    Budget(BudgetPolicy(usd("100"), usd("100"), usd("10"), usd("10"))), 1
                )
            }
        ),
        FakeProvider(actual_cost=usd("1")),
        FakeSubmissions(),
        FakeGateway(clock),
        FakeVerifier(clock, usd("85")),
        opportunity.reference,
    )


def progress(
    world: World, state: OpportunityState, task_type: TaskType = TaskType.RESEARCH
) -> None:
    if state == OpportunityState.SKIPPED:
        scored(world)
        current = world.opportunities.snapshots[world.reference]
        world.opportunities.save(
            OpportunitySave(current.value.skip("Economic decision: watch only"), current.revision)
        )
        return
    plan(world, task_type)
    world.execute_task().execute(work_request(world))
    if state == OpportunityState.QA_PENDING:
        return
    current = world.opportunities.snapshots[world.reference]
    deliverable = current.value.deliverable
    assert deliverable is not None
    approved = current.value.review_qa(QAResult(deliverable, QAStatus.PASSED, "Checked")).approve(
        HumanApproval(
            deliverable, Reference("destination"), Reference("operator"), world.clock.now()
        )
    )
    world.opportunities.save(OpportunitySave(approved, current.revision))
    world.submit_task().execute(world.reference, Reference("submission:" + world.reference.value))
    if state == OpportunityState.SUBMITTED:
        return
    gateway = OutcomeGateway(world.clock)
    gateway.outcome_status = (
        OutcomeStatus.REJECTED if state == OpportunityState.REJECTED else OutcomeStatus.ACCEPTED
    )
    TrackOutcome(world.opportunities, world.submissions, gateway, world.clock).execute(
        world.reference
    )
    if state == OpportunityState.PAID:
        world.verifier.status = PaymentStatus.VERIFIED
        VerifyPayment(world.opportunities, world.verifier, world.clock, world.submissions).execute(
            world.reference
        )
