from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import ExpectedValue, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import (
    Eligibility,
    EligibilityStatus,
    Outcome,
    OutcomeStatus,
    QAResult,
    QAStatus,
)


def test_all_required_states_have_real_lifecycle_snapshots(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    assert set(lifecycle) == set(OpportunityState)
    paid = lifecycle[OpportunityState.PAID]
    assert paid.history == (
        OpportunityState.DISCOVERED,
        OpportunityState.NORMALIZED,
        OpportunityState.ELIGIBILITY_CHECK,
        OpportunityState.ELIGIBLE,
        OpportunityState.EVALUATED,
        OpportunityState.SCORED,
        OpportunityState.PLANNED,
        OpportunityState.IN_PROGRESS,
        OpportunityState.QA_PENDING,
        OpportunityState.READY_FOR_HUMAN_REVIEW,
        OpportunityState.APPROVED_FOR_SUBMISSION,
        OpportunityState.SUBMITTED,
        OpportunityState.ACCEPTED,
        OpportunityState.PAID,
    )
    assert lifecycle[OpportunityState.DISCOVERED].history == (OpportunityState.DISCOVERED,)


@pytest.mark.parametrize(
    "state", [state for state in OpportunityState if state != OpportunityState.DISCOVERED]
)
def test_cannot_reset_lifecycle_to_normalized(
    state: OpportunityState,
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    before = lifecycle[state]
    with pytest.raises(DomainError) as error:
        before.normalize()
    assert error.value.code == ErrorCode.INVALID_TRANSITION
    assert before.state == state


@pytest.mark.parametrize(
    "state",
    [
        OpportunityState.INELIGIBLE,
        OpportunityState.SKIPPED,
        OpportunityState.REJECTED,
        OpportunityState.PAID,
    ],
)
def test_terminal_states_have_no_successors(state: OpportunityState) -> None:
    assert state.successors == frozenset()


def test_no_arbitrary_state_assignment_or_constructor_override(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    discovered = lifecycle[OpportunityState.DISCOVERED]
    with pytest.raises(FrozenInstanceError):
        discovered.state = OpportunityState.PAID  # type: ignore[misc]
    with pytest.raises((ValueError, TypeError)):
        replace(discovered, state=OpportunityState.PAID)
    with pytest.raises((ValueError, TypeError)):
        replace(discovered, payment=lifecycle[OpportunityState.PAID].payment)
    with pytest.raises((ValueError, TypeError)):
        replace(discovered, score=Decimal(-1))


def test_discovered_cannot_jump_to_evaluation_or_payment(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    discovered = lifecycle[OpportunityState.DISCOVERED]
    with pytest.raises(DomainError) as error:
        discovered.evaluate(ExpectedValue(Money(Decimal(1), "USD"), "Estimate"))
    assert error.value.code == ErrorCode.INVALID_TRANSITION
    with pytest.raises(DomainError):
        discovered.verify_payment(lifecycle[OpportunityState.PAID].potential_reward)


@pytest.mark.parametrize(
    "status", [EligibilityStatus.UNKNOWN, EligibilityStatus.REQUIRES_HUMAN_REVIEW]
)
def test_unresolved_eligibility_is_retained_without_advancing(
    status: EligibilityStatus,
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    checking = lifecycle[OpportunityState.ELIGIBILITY_CHECK]
    assessment = Eligibility(status, "Missing evidence or human decision")
    updated = checking.assess_eligibility(assessment)
    assert updated.eligibility == assessment
    assert updated.state == OpportunityState.ELIGIBILITY_CHECK
    with pytest.raises(DomainError):
        updated.evaluate(ExpectedValue(Money(Decimal(1), "USD"), "Estimate"))
    assert checking.state == OpportunityState.ELIGIBILITY_CHECK


def test_estimates_must_match_currency_and_scores_are_finite_nonnegative(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    with pytest.raises(DomainError) as error:
        lifecycle[OpportunityState.ELIGIBLE].evaluate(
            ExpectedValue(Money(Decimal(1), "EUR"), "Estimate")
        )
    assert error.value.code == ErrorCode.CURRENCY_MISMATCH
    evaluated = lifecycle[OpportunityState.EVALUATED]
    for score in (Decimal(-1), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(DomainError):
            evaluated.assign_score(score)
    assert evaluated.assign_score(Decimal(0)).state == OpportunityState.SCORED


def test_skip_requires_a_reason_and_cannot_hide_an_inflight_submission(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    with pytest.raises(DomainError):
        lifecycle[OpportunityState.SCORED].skip(" ")
    with pytest.raises(DomainError) as error:
        lifecycle[OpportunityState.SUBMITTED].skip("Changed mind")
    assert error.value.code == ErrorCode.INVALID_TRANSITION


def test_task_execution_and_deliverable_cannot_cross_opportunities(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    planned = lifecycle[OpportunityState.PLANNED]
    task = planned.task
    execution = lifecycle[OpportunityState.IN_PROGRESS].execution
    deliverable = lifecycle[OpportunityState.QA_PENDING].deliverable
    assert task is not None and execution is not None and deliverable is not None
    with pytest.raises(DomainError):
        lifecycle[OpportunityState.SCORED].plan(
            replace(task, opportunity_reference=Reference("other"))
        )
    with pytest.raises(DomainError):
        planned.start(replace(execution, task=replace(task, reference=Reference("other-task"))))
    with pytest.raises(DomainError):
        lifecycle[OpportunityState.IN_PROGRESS].finish(
            replace(deliverable, execution_reference=Reference("other"))
        )


def test_failed_qa_requires_rework_and_fresh_passing_qa(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    pending = lifecycle[OpportunityState.QA_PENDING]
    deliverable = pending.deliverable
    approval = lifecycle[OpportunityState.APPROVED_FOR_SUBMISSION].approval
    assert deliverable is not None and approval is not None
    failed = pending.review_qa(QAResult(deliverable, QAStatus.FAILED, "Missing source"))
    assert failed.state == OpportunityState.IN_PROGRESS
    assert failed.deliverable is None and failed.approval is None
    with pytest.raises(DomainError):
        failed.approve(approval)
    revised = replace(deliverable, version=2, content_reference=Reference("revised-content"))
    ready = failed.finish(revised).review_qa(QAResult(revised, QAStatus.PASSED, "Fixed"))
    with pytest.raises(DomainError):
        ready.approve(approval)
    approved = ready.approve(replace(approval, deliverable=revised))
    assert approved.state == OpportunityState.APPROVED_FOR_SUBMISSION


def test_qa_and_submission_require_current_evidence(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    ready = lifecycle[OpportunityState.READY_FOR_HUMAN_REVIEW]
    submission = lifecycle[OpportunityState.SUBMITTED].submission
    assert submission is not None
    with pytest.raises(DomainError):
        lifecycle[OpportunityState.QA_PENDING].review_qa(
            replace(submission.qa, deliverable=replace(submission.deliverable, version=2))
        )
    with pytest.raises(DomainError):
        ready.submit(submission)
    approved = lifecycle[OpportunityState.APPROVED_FOR_SUBMISSION]
    changed = replace(
        submission,
        reference=Reference("new-submission"),
        qa=replace(submission.qa, findings="Changed QA evidence"),
    )
    with pytest.raises(DomainError):
        approved.submit(changed)


@pytest.mark.parametrize(
    "state", [state for state in OpportunityState if state != OpportunityState.PAID]
)
def test_only_paid_contributes_verified_revenue(
    state: OpportunityState,
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    assert lifecycle[state].verified_revenue == Money(Decimal(0), "USD")


def test_financial_stages_have_independent_amounts(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    paid = lifecycle[OpportunityState.PAID]
    assert paid.expected_value is not None and paid.outcome is not None
    assert paid.outcome.accepted_reward is not None
    assert paid.potential_reward.amount.amount == 100
    assert paid.expected_value.amount.amount == 60
    assert paid.outcome.accepted_reward.amount.amount == 90
    assert paid.verified_revenue.amount == 85


def test_payment_requires_verified_stage_matching_submission_and_currency(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    accepted = lifecycle[OpportunityState.ACCEPTED]
    payment = lifecycle[OpportunityState.PAID].payment
    outcome = accepted.outcome
    assert payment is not None and outcome is not None and outcome.accepted_reward is not None
    with pytest.raises(DomainError):
        accepted.verify_payment(outcome.accepted_reward)
    with pytest.raises(DomainError):
        accepted.verify_payment(replace(payment, submission_reference=Reference("other")))
    with pytest.raises(DomainError):
        accepted.verify_payment(replace(payment, amount=Money(Decimal(1), "EUR")))
    with pytest.raises(DomainError) as error:
        lifecycle[OpportunityState.SUBMITTED].verify_payment(payment)
    assert error.value.code == ErrorCode.INVALID_TRANSITION
    with pytest.raises(DomainError):
        lifecycle[OpportunityState.REJECTED].verify_payment(payment)


def test_outcome_requires_matching_submission_and_reward_currency(
    lifecycle: dict[OpportunityState, Opportunity],
) -> None:
    submitted = lifecycle[OpportunityState.SUBMITTED]
    outcome = lifecycle[OpportunityState.ACCEPTED].outcome
    assert outcome is not None and outcome.accepted_reward is not None
    with pytest.raises(DomainError):
        submitted.record_outcome(
            Outcome(Reference("other"), OutcomeStatus.ACCEPTED, Reference("evidence"))
        )
    with pytest.raises(DomainError):
        submitted.record_outcome(
            replace(
                outcome,
                accepted_reward=replace(outcome.accepted_reward, amount=Money(Decimal(1), "EUR")),
            )
        )


def test_opportunity_requires_title_and_potential_reward() -> None:
    amount = Money(Decimal(1), "USD")
    with pytest.raises(DomainError):
        Opportunity(Reference("opportunity"), " ", Reward(amount))
    with pytest.raises(DomainError):
        Opportunity(
            Reference("opportunity"),
            "Work",
            Reward(amount, RewardStage.ACCEPTED, Reference("evidence"), Reference("submission")),
        )
