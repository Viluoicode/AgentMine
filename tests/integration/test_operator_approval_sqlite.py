"""Immutable decisions survive reopen and conflicting concurrent operator choices."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from test_operator_approval import ready
from test_use_cases import World, world

from agentmine.application.errors import PortError
from agentmine.application.use_cases.operator import DecideOperatorReview, PrepareOperatorReview
from agentmine.domain.approval import ApprovalDecision, OperatorDecision
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.approval import SQLiteApprovalRepository
from agentmine.infrastructure.sqlite.codec import SnapshotCodec
from agentmine.infrastructure.sqlite.database import SQLiteDatabase

__all__ = ["world"]


@pytest.mark.parametrize("choice", list(OperatorDecision))
def test_review_decision_roundtrip(world: World, tmp_path: Path, choice: OperatorDecision) -> None:
    scope = ready(world)
    path = tmp_path / "approvals.db"
    approvals = SQLiteApprovalRepository(SQLiteDatabase(path))
    review = PrepareOperatorReview(
        world.opportunities, world.executions, world.ledger, approvals, world.clock
    ).execute(Reference("review"), world.reference, Reference("ledger"), scope)
    command = DecideOperatorReview(
        world.opportunities,
        world.executions,
        world.ledger,
        approvals,
        world.source,
        world.clock,
        Reference("operator"),
    )
    decision = command.execute(review.reference, choice, "Reviewed locally")
    reopened = SQLiteApprovalRepository(SQLiteDatabase(path))
    assert reopened.get_review(review.reference) == review
    assert reopened.get_decision(review.reference) == decision
    assert command.execute(review.reference, choice, "Reviewed locally") == decision
    reopened.save_decision(decision)
    with pytest.raises(PortError):
        reopened.save_decision(replace(decision, actor=Reference("different-actor")))
    with pytest.raises(PortError):
        reopened.save_review(replace(review, risks=("Changed review",)))
    codec = SnapshotCodec()
    assert codec.loads(codec.dumps(world.current()), type(world.current())) == world.current()
    if choice == OperatorDecision.REQUEST_REVISION:
        assert world.current().state == OpportunityState.IN_PROGRESS


def test_atomic_first_decision_wins(world: World, tmp_path: Path) -> None:
    scope = ready(world)
    path = tmp_path / "approvals.db"
    approvals = SQLiteApprovalRepository(SQLiteDatabase(path))
    review = PrepareOperatorReview(
        world.opportunities, world.executions, world.ledger, approvals, world.clock
    ).execute(Reference("review"), world.reference, Reference("ledger"), scope)

    def decide(choice: OperatorDecision) -> bool:
        repo = SQLiteApprovalRepository(SQLiteDatabase(path))
        try:
            repo.save_decision(
                ApprovalDecision(review.reference, Reference("operator"), world.clock.now(), choice)
            )
        except PortError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, (OperatorDecision.APPROVE, OperatorDecision.REJECT)))
    assert sorted(outcomes) == [False, True]
    assert approvals.get_decision(review.reference) is not None
