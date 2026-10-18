"""Acceptance, independent settlement and realized economics with offline ports."""

from dataclasses import replace
from datetime import timedelta

import pytest
from fakes import FakeGateway, FakeSubmissions
from test_use_cases import World, approved, usd, world

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.submission import (
    OutcomeObservation,
    PaymentStatus,
    PaymentVerificationRequest,
    PaymentVerificationResult,
)
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.use_cases.metrics import GetEconomicMetrics
from agentmine.application.use_cases.settlement import TrackOutcome, VerifyPayment
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import CostCategory, Reward, RewardStage
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import Outcome, OutcomeStatus, Submission

__all__ = ["world"]


class OutcomeGateway(FakeGateway):
    polls: int = 0

    def track_outcome(self, submission: Submission) -> OutcomeObservation:
        self.polls += 1
        if self.outcome_status is None:
            return OutcomeObservation(submission.reference, self.clock.now(), None)
        accepted = self.outcome_status == OutcomeStatus.ACCEPTED
        outcome = Outcome(
            submission.reference,
            self.outcome_status,
            Reference("marketplace-evidence"),
            Reward(
                usd("90"), RewardStage.ACCEPTED, Reference("acceptance-proof"), submission.reference
            )
            if accepted
            else None,
            None if accepted else "Required source citations were missing",
        )
        return OutcomeObservation(submission.reference, self.clock.now(), outcome)


def submitted(world: World) -> OutcomeGateway:
    approved(world)
    world.submit_task().execute(world.reference, Reference("submission"))
    return OutcomeGateway(world.clock)


def accept(world: World) -> OutcomeGateway:
    gateway = submitted(world)
    TrackOutcome(world.opportunities, world.submissions, gateway, world.clock).execute(
        world.reference
    )
    return gateway


def verifier(world: World) -> VerifyPayment:
    return VerifyPayment(world.opportunities, world.verifier, world.clock, world.submissions)


def test_accepted_is_not_paid_and_potential_is_not_verified_revenue(world: World) -> None:
    gateway = submitted(world)
    metrics = GetEconomicMetrics(world.opportunities, world.ledger)
    before = metrics.execute(world.reference, Reference("ledger"))
    assert before.opportunity.state == OpportunityState.SUBMITTED
    assert before.opportunity.potential_reward.amount == usd("100")
    assert before.verified_revenue == usd("0") and before.net_verified_value == usd("-1")
    accepted = TrackOutcome(world.opportunities, world.submissions, gateway, world.clock).execute(
        world.reference
    )
    assert accepted.state == OpportunityState.ACCEPTED
    assert accepted.accepted_reward is not None and accepted.accepted_reward.amount == usd("90")
    assert (
        accepted.verified_reward is None
        and accepted.payment_reference is None
        and accepted.payment_timestamp is None
    )
    assert accepted.verified_revenue == usd("0")
    for status in (PaymentStatus.PENDING, PaymentStatus.UNVERIFIABLE):
        world.verifier.status = status
        world.clock.instant += timedelta(seconds=1)
        assert verifier(world).execute(world.reference) == accepted
    assert len(world.submissions.payment_history(Reference("submission"))) == 2
    assert metrics.execute(world.reference, Reference("ledger")).verified_revenue == usd("0")
    world.verifier.status = PaymentStatus.VERIFIED
    paid = verifier(world).execute(world.reference)
    after = metrics.execute(world.reference, Reference("ledger"))
    assert paid.state == OpportunityState.PAID and paid.currency == "USD"
    assert paid.verified_reward is not None and paid.verified_reward.amount == usd("85")
    assert paid.payment_reference == Reference("payment-reference:submission")
    assert paid.payment_timestamp == world.clock.now()
    assert after.verified_revenue == usd("85") and after.net_verified_value == usd("84")
    assert paid.expected_value == before.opportunity.expected_value
    calls = world.verifier.calls
    assert verifier(world).execute(world.reference) == paid
    assert world.verifier.calls == calls


def test_rejection_preserves_reason_and_actual_loss(world: World) -> None:
    gateway = submitted(world)
    gateway.outcome_status = OutcomeStatus.REJECTED
    tracker = TrackOutcome(world.opportunities, world.submissions, gateway, world.clock)
    rejected = tracker.execute(world.reference)
    assert rejected.state == OpportunityState.REJECTED and rejected.outcome is not None
    assert rejected.outcome.rejection_reason == "Required source citations were missing"
    assert world.submissions.get_outcome(Reference("submission")) == rejected.outcome
    assert tracker.execute(world.reference) == rejected and gateway.polls == 1
    result = GetEconomicMetrics(world.opportunities, world.ledger).execute(
        world.reference, Reference("ledger")
    )
    assert result.verified_revenue == usd("0") and result.net_verified_value == usd("-1")
    with pytest.raises(ApplicationError) as error:
        verifier(world).execute(world.reference)
    assert "accepted" in str(error.value).lower()
    assert world.verifier.calls == 0


def test_pending_outcome_observations_are_retained(world: World) -> None:
    gateway = submitted(world)
    gateway.outcome_status = None
    tracker = TrackOutcome(world.opportunities, world.submissions, gateway, world.clock)
    tracker.execute(world.reference)
    world.clock.instant += timedelta(seconds=1)
    tracker.execute(world.reference)
    assert len(world.submissions.outcome_history(Reference("submission"))) == 2
    assert world.current().state == OpportunityState.SUBMITTED


@pytest.mark.parametrize("phase", ["outcome", "payment"])
def test_recover_after_aggregate_write_failure_without_repoll(world: World, phase: str) -> None:
    gateway = submitted(world)
    tracker = TrackOutcome(world.opportunities, world.submissions, gateway, world.clock)
    if phase == "payment":
        tracker.execute(world.reference)
        world.verifier.status = PaymentStatus.VERIFIED
    world.opportunities.fail_save = True
    with pytest.raises(PortError):
        (tracker if phase == "outcome" else verifier(world)).execute(world.reference)
    world.opportunities.fail_save = False
    result = (tracker if phase == "outcome" else verifier(world)).execute(world.reference)
    assert result.state == (
        OpportunityState.ACCEPTED if phase == "outcome" else OpportunityState.PAID
    )
    assert gateway.polls == 1
    assert world.verifier.calls == (0 if phase == "outcome" else 1)


def test_outcome_observation_recovers_failure_to_save_final_outcome(world: World) -> None:
    gateway = submitted(world)

    class Store(FakeSubmissions):
        fail: bool = True

        def save_outcome(self, outcome: Outcome) -> None:
            if self.fail:
                raise PortError(PortErrorCode.UNAVAILABLE, "outcome", "Injected failure")
            super().save_outcome(outcome)

    store = Store()
    tracker = TrackOutcome(world.opportunities, store, gateway, world.clock)
    with pytest.raises(PortError):
        tracker.execute(world.reference)
    store.fail = False
    assert tracker.execute(world.reference).state == OpportunityState.ACCEPTED
    assert gateway.polls == 1


@pytest.mark.parametrize("tamper", ["future", "before_submission", "currency", "submission"])
def test_invalid_payment_evidence_does_not_create_revenue(world: World, tamper: str) -> None:
    accept(world)
    world.verifier.status = PaymentStatus.VERIFIED

    class TamperedVerifier:
        def verify_payment(self, request: PaymentVerificationRequest) -> PaymentVerificationResult:
            valid = world.verifier.verify_payment(request)
            assert valid.payment is not None and valid.verification is not None
            payment, evidence = valid.payment, valid.verification
            if tamper == "future":
                return replace(valid, observed_at=world.clock.now() + timedelta(days=1))
            if tamper == "before_submission":
                evidence = replace(
                    evidence, payment_timestamp=world.clock.now() - timedelta(days=1)
                )
            else:
                payment = replace(
                    payment,
                    amount=usd("85")
                    if tamper == "submission"
                    else type(payment.amount)(payment.amount.amount, "EUR"),
                    submission_reference=Reference("other")
                    if tamper == "submission"
                    else payment.submission_reference,
                )
                evidence = replace(evidence, reward=payment)
            return replace(valid, payment=payment, verification=evidence)

    with pytest.raises((DomainError, PortError)):
        VerifyPayment(
            world.opportunities, TamperedVerifier(), world.clock, world.submissions
        ).execute(world.reference)
    assert (
        world.current().state == OpportunityState.ACCEPTED
        and world.current().verified_revenue == usd("0")
    )
    assert not world.submissions.payment_observations


def test_verified_label_without_independent_evidence_is_rejected(world: World) -> None:
    accept(world)
    world.verifier.status = PaymentStatus.VERIFIED
    current = world.current()
    assert current.submission is not None and current.outcome is not None
    response = world.verifier.verify_payment(
        PaymentVerificationRequest(current.submission, current.outcome)
    )
    with pytest.raises(DomainError):
        replace(response, verification=None)
    assert response.payment is not None
    with pytest.raises(DomainError):
        world.current().verify_payment(response.payment)
    assert world.current().verified_revenue == usd("0")


def test_metrics_refresh_after_late_actual_costs(world: World) -> None:
    accept(world)
    world.verifier.status = PaymentStatus.VERIFIED
    verifier(world).execute(world.reference)
    metrics = GetEconomicMetrics(world.opportunities, world.ledger)
    manager = BudgetManager(world.ledger, Reference("ledger"), world.clock)
    for category, amount in (
        (CostCategory.TOOL, "2"),
        (CostCategory.INFRASTRUCTURE, "3"),
        (CostCategory.TRANSACTION, "4"),
    ):
        context = CostContext(
            Reference("late-" + category.value),
            OperationType.OUTCOME_TRACKING,
            world.clock.now(),
            Reference("task"),
            world.reference,
        )
        decision = manager.authorize(usd(amount), context, category)
        assert decision.authorization is not None
        manager.record(decision.authorization, usd(amount), world.clock.now())
    result = metrics.execute(world.reference, Reference("ledger"))
    assert result.cost(CostCategory.AI) == usd("1")
    assert result.total_actual_cost == usd("10") and result.net_verified_value == usd("75")
    assert result.verified_revenue == usd("85")
