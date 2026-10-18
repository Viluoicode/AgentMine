"""Deterministic descriptive statistics with explicit denominators and currencies."""

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

from agentmine.domain.history import HistoricalObservation
from agentmine.domain.money import Money
from agentmine.domain.values import Reference
from agentmine.domain.work import OutcomeStatus, TaskType


@dataclass(frozen=True, slots=True)
class OutcomeCounts:
    observations: int
    attempts: int
    skipped: int
    accepted: int
    rejected: int
    paid: int
    unresolved_attempts: int

    @property
    def acceptance_rate(self) -> Decimal | None:
        resolved = self.accepted + self.rejected
        if resolved == 0:
            return None
        with localcontext(Context(prec=50)):
            return Decimal(self.accepted) / Decimal(resolved)


@dataclass(frozen=True, slots=True)
class SourceOutcomes:
    source: Reference
    counts: OutcomeCounts


@dataclass(frozen=True, slots=True)
class CostStatistics:
    currency: str
    predicted_samples: int
    actual_samples: int
    paired_samples: int
    average_predicted_cost: Money | None
    average_actual_cost: Money | None
    cost_prediction_error: Money | None
    mean_absolute_cost_error: Money | None


@dataclass(frozen=True, slots=True)
class HistoricalStatistics:
    overall: OutcomeCounts
    research: OutcomeCounts
    data: OutcomeCounts
    unknown_task_type: OutcomeCounts
    sources: tuple[SourceOutcomes, ...]
    costs: tuple[CostStatistics, ...]


def counts(items: tuple[HistoricalObservation, ...]) -> OutcomeCounts:
    attempts = sum(item.attempted for item in items)
    accepted = sum(item.attempted and item.outcome == OutcomeStatus.ACCEPTED for item in items)
    rejected = sum(item.attempted and item.outcome == OutcomeStatus.REJECTED for item in items)
    return OutcomeCounts(
        len(items),
        attempts,
        sum(item.skipped for item in items),
        accepted,
        rejected,
        sum(item.verified_reward is not None for item in items),
        attempts - accepted - rejected,
    )


def average(values: list[Money], currency: str) -> Money | None:
    if not values:
        return None
    with localcontext(Context(prec=50)):
        return Money(
            sum((item.amount for item in values), Decimal(0)) / Decimal(len(values)), currency
        )


def cost_statistics(items: tuple[HistoricalObservation, ...], currency: str) -> CostStatistics:
    cohort = tuple(
        item for item in items if item.attempted and item.reward.amount.currency == currency
    )
    predictions = [item.predicted_cost for item in cohort if item.predicted_cost is not None]
    resolved = tuple(
        item
        for item in cohort
        if item.outcome is not None
        and not item.outstanding_operations
        and item.actual_cost is not None
    )
    actuals = [item.actual_cost for item in resolved if item.actual_cost is not None]
    errors = [
        item.actual_cost - item.predicted_cost
        for item in resolved
        if item.actual_cost is not None and item.predicted_cost is not None
    ]
    absolute = [Money(abs(item.amount), currency) for item in errors]
    return CostStatistics(
        currency,
        len(predictions),
        len(actuals),
        len(errors),
        average(predictions, currency),
        average(actuals, currency),
        average(errors, currency),
        average(absolute, currency),
    )


def summarize(items: tuple[HistoricalObservation, ...]) -> HistoricalStatistics:
    return HistoricalStatistics(
        counts(items),
        counts(tuple(item for item in items if item.task_type == TaskType.RESEARCH)),
        counts(tuple(item for item in items if item.task_type == TaskType.DATA_PROCESSING)),
        counts(tuple(item for item in items if item.task_type is None)),
        tuple(
            SourceOutcomes(source, counts(tuple(item for item in items if item.source == source)))
            for source in sorted({item.source for item in items}, key=lambda ref: ref.value)
        ),
        tuple(
            cost_statistics(items, currency)
            for currency in sorted({item.reward.amount.currency for item in items})
        ),
    )
