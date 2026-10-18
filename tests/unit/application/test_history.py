"""Explicit observations, denominators, data quality and no production feedback."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from history_fakes import MemoryHistory, make_world, progress
from test_outcome_payment import OutcomeGateway
from test_use_cases import World, usd

from agentmine.application.contracts.submission import PaymentStatus
from agentmine.application.errors import PortError
from agentmine.application.ports.history import HistoricalPerformance
from agentmine.application.use_cases.history import (
    CaptureHistoricalObservation,
    GetHistoricalStatistics,
)
from agentmine.application.use_cases.settlement import TrackOutcome, VerifyPayment
from agentmine.domain.errors import DomainError
from agentmine.domain.history import HistoricalObservation, HistoricalQuery
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import TaskType


def capture(
    world: World,
    history: MemoryHistory,
    name: str,
    source: str = "market-a",
    task_type: TaskType | None = None,
) -> HistoricalObservation:
    return CaptureHistoricalObservation(
        world.opportunities, world.evaluations, world.ledger, history, world.clock
    ).execute(
        Reference(name),
        world.reference,
        Reference("ledger"),
        Reference(source),
        task_type,
        None if task_type is None else Reference("classification-evidence"),
    )


def test_known_statistics_and_latest_samples() -> None:
    history = MemoryHistory()
    cases = [
        ("r-accepted", TaskType.RESEARCH, OpportunityState.ACCEPTED, "market-a"),
        ("r-rejected", TaskType.RESEARCH, OpportunityState.REJECTED, "market-b"),
        ("d-paid", TaskType.DATA_PROCESSING, OpportunityState.PAID, "market-a"),
        ("d-pending", TaskType.DATA_PROCESSING, OpportunityState.SUBMITTED, "market-b"),
    ]
    for name, kind, state, source in cases:
        world = make_world(name)
        progress(world, state, kind)
        initial = capture(world, history, name + ":one", source)
        assert initial.predicted_success_probability == Decimal("0.8")
        assert initial.predicted_cost == usd("20") and initial.actual_cost == usd("1")
        assert initial.score is not None and initial.recommendation is not None
        before_scoring = world.current().scoring_assessment
        assert capture(world, history, name + ":one", source) == initial
        capture(world, history, name + ":two", source)
        assert world.current().scoring_assessment == before_scoring
    skipped = make_world("skipped")
    progress(skipped, OpportunityState.SKIPPED)
    record = capture(skipped, history, "skip", task_type=TaskType.RESEARCH)
    assert record.skipped and not record.attempted and record.actual_cost is None
    reader: HistoricalPerformance = GetHistoricalStatistics(history)
    stats = reader.statistics(HistoricalQuery())
    assert stats.overall.observations == 5 and stats.overall.attempts == 4
    assert stats.research.attempts == 2 and stats.research.acceptance_rate == Decimal("0.5")
    assert stats.data.attempts == 2 and stats.data.acceptance_rate == Decimal(1)
    assert stats.data.unresolved_attempts == 1 and stats.research.skipped == 1
    costs = stats.costs[0]
    assert (costs.predicted_samples, costs.actual_samples, costs.paired_samples) == (4, 3, 3)
    assert costs.average_predicted_cost == usd("20") and costs.average_actual_cost == usd("1")
    assert costs.cost_prediction_error == usd("-19") and costs.mean_absolute_cost_error == usd("19")
    assert stats.sources[0].source == Reference("market-a")
    assert stats.sources[0].counts.acceptance_rate == Decimal(1)
    assert stats.sources[1].counts.acceptance_rate == Decimal(0)
    assert (
        reader.statistics(HistoricalQuery(task_type=TaskType.DATA_PROCESSING)).overall.attempts == 2
    )
    assert reader.statistics(HistoricalQuery(source=Reference("market-b"))).overall.attempts == 2


def test_as_of_observations_preserve_pending_and_unpaid_labels() -> None:
    world, history = make_world("one"), MemoryHistory()
    progress(world, OpportunityState.SUBMITTED)
    pending = capture(world, history, "pending")
    world.clock.instant += timedelta(seconds=1)
    TrackOutcome(
        world.opportunities, world.submissions, OutcomeGateway(world.clock), world.clock
    ).execute(world.reference)
    accepted = capture(world, history, "accepted")
    assert pending.outcome is None and accepted.verified_reward is None
    world.clock.instant += timedelta(seconds=1)
    world.verifier.status = PaymentStatus.VERIFIED
    VerifyPayment(world.opportunities, world.verifier, world.clock, world.submissions).execute(
        world.reference
    )
    paid = capture(world, history, "paid")
    assert paid.verified_reward is not None and paid.verified_reward.amount == usd("85")
    assert paid.reward.amount == usd("100")
    stats = GetHistoricalStatistics(history)
    assert stats.execute().overall.observations == 1
    assert (
        stats.execute(HistoricalQuery(as_of=pending.captured_at)).research.acceptance_rate is None
    )
    assert history.latest(HistoricalQuery(as_of=accepted.captured_at))[0].verified_reward is None
    assert (
        stats.execute(HistoricalQuery(exclude_opportunity=world.reference)).overall.observations
        == 0
    )


def test_missing_predictions_and_costs_stay_unknown() -> None:
    world, history = make_world("unknown"), MemoryHistory()
    world.provider.actual_cost = None
    progress(world, OpportunityState.ACCEPTED)
    world.evaluations.records.clear()
    record = capture(world, history, "missing")
    assert record.predicted_success_probability is None and record.predicted_cost is None
    assert record.score is None and record.recommendation is None and record.actual_cost is None
    assert record.outstanding_operations
    stats = GetHistoricalStatistics(history).execute()
    assert stats.costs[0].predicted_samples == stats.costs[0].actual_samples == 0
    assert stats.costs[0].cost_prediction_error is None


def test_unknown_task_type_is_not_guessed() -> None:
    world, history = make_world("skip"), MemoryHistory()
    progress(world, OpportunityState.SKIPPED)
    record = capture(world, history, "unknown-kind")
    assert record.task_type is None and record.classification_evidence is None
    report = GetHistoricalStatistics(history).execute()
    assert report.unknown_task_type.skipped == 1 and report.research.observations == 0


@pytest.mark.parametrize("change", ["source", "ledger", "sequence", "forecast", "costs"])
def test_history_cannot_rewrite_provenance_or_predictions(change: str) -> None:
    world, history = make_world("immutable"), MemoryHistory()
    progress(world, OpportunityState.ACCEPTED)
    record = capture(world, history, "first")
    next_item = replace(record, reference=Reference("next"), sequence=2)
    if change == "source":
        next_item = replace(next_item, source=Reference("another-market"))
    elif change == "ledger":
        next_item = replace(next_item, ledger_reference=Reference("another-ledger"))
    elif change == "sequence":
        next_item = replace(next_item, sequence=3)
    elif change == "forecast":
        next_item = replace(next_item, forecast=None, forecast_reference=None, forecast_at=None)
    else:
        next_item = replace(next_item, actual_costs=())
    with pytest.raises(DomainError):
        history.append(next_item, record.reference)
    with pytest.raises(PortError):
        history.append(replace(record, source=Reference("changed")), None)


def test_zero_cost_is_known_only_when_recorded() -> None:
    world, history = make_world("free"), MemoryHistory()
    world.provider.actual_cost = usd("0")
    progress(world, OpportunityState.ACCEPTED)
    record = capture(world, history, "free-record")
    assert record.actual_cost == usd("0")
    assert GetHistoricalStatistics(history).execute().costs[0].actual_samples == 1


def test_empty_dataset_has_unknown_rates_and_no_money() -> None:
    stats = GetHistoricalStatistics(MemoryHistory()).execute()
    assert stats.research.attempts == stats.data.attempts == 0
    assert stats.research.acceptance_rate is None and stats.data.acceptance_rate is None
    assert stats.costs == () and stats.sources == ()


def test_forecasts_created_after_execution_are_not_learned_as_predictions() -> None:
    world, history = make_world("late-forecast"), MemoryHistory()
    progress(world, OpportunityState.ACCEPTED)
    original = next(iter(world.evaluations.records.values()))
    world.evaluations.records.clear()
    future = replace(
        original,
        reference=Reference("after-attempt"),
        evaluated_at=world.clock.now() + timedelta(seconds=1),
    )
    world.evaluations.records[future.reference] = future
    world.clock.instant += timedelta(seconds=2)
    missing = capture(world, history, "missing-at-attempt")
    assert missing.forecast is None
    # Later backfills cannot rewrite predictions already observed at attempt time.
    world.evaluations.records[original.reference] = original
    refreshed = capture(world, history, "still-missing")
    assert refreshed.forecast is None


def test_changed_source_and_unclassified_task_evidence_fail_explicitly() -> None:
    world, history = make_world("source-binding"), MemoryHistory()
    progress(world, OpportunityState.SKIPPED)
    first = capture(world, history, "one")
    with pytest.raises(DomainError):
        capture(world, history, "different-source", source="renamed-market")
    with pytest.raises(PortError):
        capture(world, history, "one", source="changed-scope")
    with pytest.raises(DomainError):
        replace(first, task_type=TaskType.RESEARCH)


@pytest.mark.parametrize("field", ["forecast", "cost", "capture"])
def test_future_or_regressing_evidence_is_not_persisted(field: str) -> None:
    world, history = make_world("invalid"), MemoryHistory()
    progress(world, OpportunityState.ACCEPTED)
    first = capture(world, history, "first")
    with pytest.raises(DomainError):
        if field == "forecast":
            replace(first, forecast_at=world.clock.now() + timedelta(days=1))
        elif field == "cost":
            replace(
                first,
                actual_costs=(
                    replace(
                        first.actual_costs[0],
                        context=replace(
                            first.actual_costs[0].context,
                            occurred_at=world.clock.now() + timedelta(days=1),
                        ),
                    ),
                ),
            )
        else:
            replace(first, captured_at=world.clock.now() - timedelta(days=1))
    assert history.latest(HistoricalQuery()) == (first,)
