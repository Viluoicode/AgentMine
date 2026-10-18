"""Payment proof invariants and observed-economics accounting."""

from dataclasses import replace
from datetime import datetime

import pytest

from agentmine.domain.errors import DomainError
from agentmine.domain.finance import RewardStage
from agentmine.domain.metrics import EconomicMetrics
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import Outcome, OutcomeStatus


def test_verified_reward_requires_more_than_a_stage_label(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    accepted, paid = lifecycle[OpportunityState.ACCEPTED], lifecycle[OpportunityState.PAID]
    assert paid.payment is not None and paid.payment_verification is not None
    with pytest.raises(DomainError):
        accepted.verify_payment(paid.payment)
    assert accepted.verified_reward is None and accepted.verified_revenue.amount == 0
    assert accepted.verify_payment(paid.payment, paid.payment_verification) == paid


@pytest.mark.parametrize("field", ["reward", "timestamp", "record"])
def test_invalid_proof_is_rejected(
    lifecycle: dict[OpportunityState, Opportunity], field: str
) -> None:
    accepted, paid = lifecycle[OpportunityState.ACCEPTED], lifecycle[OpportunityState.PAID]
    proof = paid.payment_verification
    assert proof is not None and accepted.accepted_reward is not None
    with pytest.raises(DomainError):
        if field == "reward":
            replace(proof, reward=accepted.accepted_reward)
        elif field == "timestamp":
            replace(proof, payment_timestamp=datetime(2026, 10, 18))
        else:
            replace(proof, verification_record=Reference("unrelated-proof"))


@pytest.mark.parametrize(
    "state", [OpportunityState.SUBMITTED, OpportunityState.ACCEPTED, OpportunityState.REJECTED]
)
def test_unpaid_metrics_have_no_verified_revenue(
    lifecycle: dict[OpportunityState, Opportunity], state: OpportunityState
) -> None:
    op = lifecycle[state]
    metrics = EconomicMetrics(op, (), ())
    assert metrics.verified_revenue.amount == 0
    assert op.potential_reward.stage == RewardStage.POTENTIAL
    assert op.payment_reference is None and op.payment_timestamp is None


def test_rejection_reason_is_not_an_acceptance_field() -> None:
    with pytest.raises(DomainError):
        Outcome(
            Reference("submission"),
            OutcomeStatus.ACCEPTED,
            Reference("evidence"),
            rejection_reason="Missing sources",
        )
    with pytest.raises(DomainError):
        Outcome(
            Reference("submission"),
            OutcomeStatus.REJECTED,
            Reference("evidence"),
            rejection_reason="  ",
        )
    missing = Outcome(Reference("submission"), OutcomeStatus.REJECTED, Reference("evidence"))
    assert missing.rejection_reason is None
