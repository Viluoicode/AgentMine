"""Durable outcome/reward evidence, legacy handling and concurrent payment attribution."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from test_outcome_payment import accept, submitted
from test_use_cases import World, usd, world

from agentmine.application.contracts.submission import (
    PaymentStatus,
    PaymentVerificationRequest,
    PaymentVerificationResult,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.settlement import TrackOutcome, VerifyPayment
from agentmine.bootstrap.local import open_local_repositories
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import OutcomeStatus
from agentmine.infrastructure.sqlite.codec import SnapshotCodec
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository

__all__ = ["world"]


def test_history_reopens_and_recovers_paid_without_repoll(world: World, tmp_path: Path) -> None:
    accept(world)
    path = tmp_path / "mine.db"
    repo = SQLiteSubmissionRepository(SQLiteDatabase(path))
    payment = VerifyPayment(world.opportunities, world.verifier, world.clock, repo)
    for status in (PaymentStatus.PENDING, PaymentStatus.UNVERIFIABLE):
        world.verifier.status = status
        payment.execute(world.reference)
    world.verifier.status = PaymentStatus.VERIFIED
    world.opportunities.fail_save = True
    with pytest.raises(PortError):
        payment.execute(world.reference)
    calls = world.verifier.calls
    world.opportunities.fail_save = False
    reopened = SQLiteSubmissionRepository(SQLiteDatabase(path))
    paid = VerifyPayment(world.opportunities, world.verifier, world.clock, reopened).execute(
        world.reference
    )
    assert world.verifier.calls == calls
    assert len(reopened.payment_history(Reference("submission"))) == 3
    assert paid.verified_revenue == usd("85") and paid.payment_reference is not None
    codec = SnapshotCodec()
    assert codec.loads(codec.dumps(paid), Opportunity) == paid
    # Exercise durable opportunity storage and aggregate verified revenue, not just codec.
    local = open_local_repositories(path)
    from agentmine.application.contracts.records import OpportunitySave

    local.opportunities.save(OpportunitySave(paid, None))
    stored = open_local_repositories(path).opportunities.get(paid.reference)
    assert stored is not None and stored.value == paid
    assert local.opportunities.verified_revenue("USD") == usd("85")


def test_rejection_reason_survives_sqlite(world: World, tmp_path: Path) -> None:
    gateway = submitted(world)
    gateway.outcome_status = OutcomeStatus.REJECTED
    path = tmp_path / "mine.db"
    repo = SQLiteSubmissionRepository(SQLiteDatabase(path))
    rejected = TrackOutcome(world.opportunities, repo, gateway, world.clock).execute(
        world.reference
    )
    reopened = SQLiteSubmissionRepository(SQLiteDatabase(path))
    assert reopened.get_outcome(Reference("submission")) == rejected.outcome
    retained = reopened.outcome_history(Reference("submission"))[0].outcome
    assert retained is not None
    assert retained.rejection_reason == "Required source citations were missing"
    assert rejected.verified_revenue == usd("0")


def verified_result(world: World) -> PaymentVerificationResult:
    world.verifier.status = PaymentStatus.VERIFIED
    current = world.current()
    assert current.submission is not None and current.outcome is not None
    return world.verifier.verify_payment(
        PaymentVerificationRequest(current.submission, current.outcome)
    )


def test_one_independent_payment_cannot_credit_two_submissions(
    world: World, tmp_path: Path
) -> None:
    accept(world)
    first = verified_result(world)
    assert first.payment is not None and first.verification is not None
    second_payment = replace(first.payment, submission_reference=Reference("another-submission"))
    second = replace(
        first,
        submission_reference=Reference("another-submission"),
        payment=second_payment,
        verification=replace(first.verification, reward=second_payment),
    )
    path = tmp_path / "mine.db"
    SQLiteDatabase(path)

    def record(result: PaymentVerificationResult) -> bool:
        try:
            SQLiteSubmissionRepository(SQLiteDatabase(path)).record_payment_observation(result)
            return True
        except PortError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(record, (first, second))) == [False, True]


def test_conflicting_verified_amounts_fail(world: World, tmp_path: Path) -> None:
    accept(world)
    result = verified_result(world)
    assert result.payment is not None and result.verification is not None
    repo = SQLiteSubmissionRepository(SQLiteDatabase(tmp_path / "mine.db"))
    repo.record_payment_observation(result)
    repo.record_payment_observation(result)
    changed_payment = replace(result.payment, amount=usd("999"))
    with pytest.raises(PortError):
        repo.record_payment_observation(
            replace(
                result,
                payment=changed_payment,
                verification=replace(result.verification, reward=changed_payment),
            )
        )
    assert repo.payment_history(Reference("submission")) == (result,)


def test_conflicting_final_outcomes_fail(world: World, tmp_path: Path) -> None:
    gateway = submitted(world)
    current = world.current()
    assert current.submission is not None
    accepted = gateway.track_outcome(current.submission)
    gateway.outcome_status = OutcomeStatus.REJECTED
    rejected = gateway.track_outcome(current.submission)
    repo = SQLiteSubmissionRepository(SQLiteDatabase(tmp_path / "mine.db"))
    repo.record_outcome_observation(accepted)
    with pytest.raises(PortError):
        repo.record_outcome_observation(rejected)
    assert repo.outcome_history(current.submission.reference) == (accepted,)


def test_legacy_accepted_loads_but_paid_requires_reverification(world: World) -> None:
    accept(world)
    accepted = world.current()
    codec = SnapshotCodec()
    payload = json.loads(codec.dumps(accepted))
    del payload["value"]["fields"]["payment_verification"]
    outcome = payload["value"]["fields"]["outcome"]["fields"]
    del outcome["rejection_reason"]
    restored = codec.loads(json.dumps(payload), Opportunity)
    assert restored.state == OpportunityState.ACCEPTED and restored.verified_revenue == usd("0")
    result = verified_result(world)
    assert result.payment is not None
    paid = accepted.verify_payment(result.payment, result.verification)
    payload = json.loads(codec.dumps(paid))
    del payload["value"]["fields"]["payment_verification"]
    with pytest.raises(PortError) as error:
        codec.loads(json.dumps(payload), Opportunity)
    assert error.value.code == PortErrorCode.UNSUPPORTED
