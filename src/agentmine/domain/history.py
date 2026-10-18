"""Auditable observations for learning later; production policy is not modified."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from agentmine.domain.errors import DomainError, ErrorCode
from agentmine.domain.finance import Reward
from agentmine.domain.metrics import EconomicMetrics
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.scoring import Recommendation, ScoringAssessment
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference, require_aware_timestamp, require_reference
from agentmine.domain.work import OutcomeStatus, TaskType


@dataclass(frozen=True, slots=True)
class HistoricalQuery:
    task_type: TaskType | None = None
    source: Reference | None = None
    as_of: datetime | None = None
    exclude_opportunity: Reference | None = None

    def __post_init__(self) -> None:
        if self.task_type is not None and not isinstance(self.task_type, TaskType):
            raise DomainError(ErrorCode.INVALID_VALUE, "task_type", "Supported task type required")
        if self.as_of is not None:
            require_aware_timestamp(self.as_of)
        for value in (self.source, self.exclude_opportunity):
            if value is not None:
                require_reference(value, "historical_filter")


@dataclass(frozen=True, slots=True)
class HistoricalObservation:
    reference: Reference
    sequence: int
    captured_at: datetime
    opportunity: Opportunity
    opportunity_revision: int
    source: Reference
    source_item: Reference
    source_observed_at: datetime
    task_type: TaskType | None
    classification_evidence: Reference | None
    forecast: ScoringAssessment | None
    forecast_reference: Reference | None
    forecast_at: datetime | None
    ledger_reference: Reference
    ledger_revision: int
    actual_costs: tuple[CostRecord, ...]
    outstanding_operations: tuple[Reference, ...]

    def __post_init__(self) -> None:
        for value in (self.reference, self.source, self.source_item, self.ledger_reference):
            require_reference(value, "history")
        for timestamp in (self.captured_at, self.source_observed_at):
            require_aware_timestamp(timestamp)
        if self.source_observed_at > self.captured_at:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "source_time", "Source observation is from the future"
            )
        if any(
            type(value) is not int or value < 1
            for value in (self.sequence, self.opportunity_revision, self.ledger_revision)
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "history_revision", "Positive sequence/revisions required"
            )
        if self.task_type is not None:
            if not isinstance(self.task_type, TaskType) or self.classification_evidence is None:
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "classification", "Known task type requires evidence"
                )
            require_reference(self.classification_evidence, "classification")
        elif self.classification_evidence is not None:
            raise DomainError(
                ErrorCode.INVALID_VALUE, "classification", "Unknown classification has no evidence"
            )
        if self.opportunity.task is not None and self.task_type != self.opportunity.task.task_type:
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH, "task_type", "Classification differs from planned task"
            )
        if self.forecast is None:
            if self.forecast_reference is not None or self.forecast_at is not None:
                raise DomainError(
                    ErrorCode.EVIDENCE_MISMATCH, "forecast", "Unknown forecast must stay unknown"
                )
        else:
            if self.forecast_reference is None or self.forecast_at is None:
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "forecast", "Forecast identity/time required"
                )
            require_reference(self.forecast_reference, "forecast")
            require_aware_timestamp(self.forecast_at)
            cutoff = (
                self.captured_at
                if self.opportunity.execution is None
                else self.opportunity.execution.started_at
            )
            if (
                self.forecast_at > cutoff
                or self.forecast.economics.potential_reward != self.opportunity.potential_reward
            ):
                raise DomainError(
                    ErrorCode.EVIDENCE_MISMATCH,
                    "forecast",
                    "Only pre-attempt forecasts for this reward are eligible",
                )
        if (
            self.opportunity.execution is not None
            and self.opportunity.execution.started_at > self.captured_at
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE,
                "execution_time",
                "Future execution cannot count as attempted",
            )
        EconomicMetrics(self.opportunity, self.actual_costs, self.outstanding_operations)
        if any(record.context.occurred_at > self.captured_at for record in self.actual_costs):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "cost_time", "Future costs cannot enter history"
            )
        if (
            self.opportunity.payment_timestamp is not None
            and self.opportunity.payment_timestamp > self.captured_at
        ):
            raise DomainError(
                ErrorCode.INVALID_VALUE, "payment_time", "Future payment cannot enter history"
            )

    def require_successor(self, prior: HistoricalObservation | None) -> None:
        if prior is None:
            if self.sequence != 1:
                raise DomainError(
                    ErrorCode.INVALID_VALUE, "sequence", "First observation starts at one"
                )
            return
        if (
            self.sequence != prior.sequence + 1
            or self.opportunity.reference != prior.opportunity.reference
            or self.source != prior.source
            or self.source_item != prior.source_item
            or self.ledger_reference != prior.ledger_reference
            or self.captured_at < prior.captured_at
            or (
                self.opportunity_revision == prior.opportunity_revision
                and self.opportunity != prior.opportunity
            )
            or (
                self.ledger_revision == prior.ledger_revision
                and (self.actual_costs, self.outstanding_operations)
                != (prior.actual_costs, prior.outstanding_operations)
            )
            or self.source_observed_at != prior.source_observed_at
            or any(record not in self.actual_costs for record in prior.actual_costs)
            or self.opportunity_revision < prior.opportunity_revision
            or self.ledger_revision < prior.ledger_revision
            or self.opportunity.history[: len(prior.opportunity.history)]
            != prior.opportunity.history
            or (prior.task_type is not None and self.task_type != prior.task_type)
            or (
                prior.attempted
                and (self.forecast, self.forecast_reference, self.forecast_at)
                != (prior.forecast, prior.forecast_reference, prior.forecast_at)
            )
        ):
            raise DomainError(
                ErrorCode.EVIDENCE_MISMATCH,
                "history",
                "Observation regressed or changed its provenance/prediction",
            )

    @property
    def reward(self) -> Reward:
        return self.opportunity.potential_reward

    @property
    def predicted_success_probability(self) -> Decimal | None:
        return (
            None
            if self.forecast is None
            else self.forecast.economics.inputs.predicted_success_probability.value
        )

    @property
    def predicted_cost(self) -> Money | None:
        return (
            None if self.forecast is None else self.forecast.economics.inputs.estimated_cost.total
        )

    @property
    def actual_cost(self) -> Money | None:
        return (
            None
            if not self.actual_costs
            else EconomicMetrics(
                self.opportunity, self.actual_costs, self.outstanding_operations
            ).total_actual_cost
        )

    @property
    def score(self) -> Decimal | None:
        return None if self.forecast is None else self.forecast.score

    @property
    def recommendation(self) -> Recommendation | None:
        return None if self.forecast is None else self.forecast.recommendation

    @property
    def attempted(self) -> bool:
        return self.opportunity.execution is not None

    @property
    def skipped(self) -> bool:
        return self.opportunity.state == OpportunityState.SKIPPED

    @property
    def outcome(self) -> OutcomeStatus | None:
        return None if self.opportunity.outcome is None else self.opportunity.outcome.status

    @property
    def verified_reward(self) -> Reward | None:
        return self.opportunity.verified_reward


def latest_observations(
    observations: tuple[HistoricalObservation, ...], query: HistoricalQuery
) -> tuple[HistoricalObservation, ...]:
    """Deduplicate before filtering; as-of never consumes later labels."""
    latest: dict[Reference, HistoricalObservation] = {}
    for item in observations:
        if query.as_of is not None and item.captured_at > query.as_of:
            continue
        key = item.opportunity.reference
        if key not in latest or latest[key].sequence < item.sequence:
            latest[key] = item
    return tuple(
        item
        for _, item in sorted(latest.items(), key=lambda pair: pair[0].value)
        if (query.task_type is None or item.task_type == query.task_type)
        and (query.source is None or item.source == query.source)
        and item.opportunity.reference != query.exclude_opportunity
    )
