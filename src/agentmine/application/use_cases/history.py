"""Explicit history capture and reporting; no hooks into production scoring."""

import logging
from dataclasses import dataclass

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.history import HistoricalRepository
from agentmine.application.ports.repositories import (
    CostLedgerRepository,
    EvaluationRepository,
    OpportunityRepository,
)
from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.context import load
from agentmine.domain.history import HistoricalObservation, HistoricalQuery
from agentmine.domain.history_statistics import HistoricalStatistics, summarize
from agentmine.domain.values import Reference
from agentmine.domain.work import TaskType


@dataclass(frozen=True, slots=True)
class CaptureHistoricalObservation:
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    ledger: CostLedgerRepository
    history: HistoricalRepository
    clock: Clock

    def execute(
        self,
        reference: Reference,
        opportunity_reference: Reference,
        ledger_reference: Reference,
        source: Reference,
        task_type: TaskType | None = None,
        classification_evidence: Reference | None = None,
    ) -> HistoricalObservation:
        existing = self.history.get(reference)
        if existing is not None:
            if (
                existing.opportunity.reference != opportunity_reference
                or existing.ledger_reference != ledger_reference
                or existing.source != source
                or (task_type is not None and existing.task_type != task_type)
                or (
                    classification_evidence is not None
                    and existing.classification_evidence != classification_evidence
                )
            ):
                raise PortError(
                    PortErrorCode.CONFLICT, "history", "Capture identity reused for different scope"
                )
            return existing
        opportunity = load(self.opportunities, opportunity_reference)
        origin = self.opportunities.get_observation(opportunity_reference)
        budget = self.ledger.get(ledger_reference)
        if (
            origin is None
            or origin.opportunity.reference != opportunity_reference
            or budget is None
        ):
            raise PortError(
                PortErrorCode.UNAVAILABLE,
                "history",
                "Authoritative source observation and ledger required",
            )
        prior_items = self.history.for_opportunity(opportunity_reference)
        prior = max(prior_items, key=lambda item: item.sequence) if prior_items else None
        value = opportunity.value
        if value.task is not None:
            if task_type is not None and task_type != value.task.task_type:
                raise PortError(
                    PortErrorCode.CONFLICT, "history", "Task classification differs from plan"
                )
            if (
                classification_evidence is not None
                and classification_evidence != value.task.reference
            ):
                raise PortError(
                    PortErrorCode.CONFLICT, "history", "Planned task is the classification evidence"
                )
            task_type = value.task.task_type
            classification_evidence = value.task.reference
        elif prior is not None and task_type is None:
            task_type, classification_evidence = prior.task_type, prior.classification_evidence
        now = self.clock.now()
        cutoff = now if value.execution is None else value.execution.started_at
        eligible = tuple(
            item
            for item in self.evaluations.for_opportunity(opportunity_reference)
            if item.evaluated_at <= cutoff and item.scoring_assessment == value.scoring_assessment
        )
        forecast = (
            max(eligible, key=lambda item: (item.evaluated_at, item.reference.value))
            if eligible
            else None
        )
        if forecast is not None and forecast.opportunity_reference != opportunity_reference:
            raise PortError(
                PortErrorCode.INVALID_RESPONSE,
                "history",
                "Evaluation belongs to another opportunity",
            )
        forecast_value = None if forecast is None else forecast.scoring_assessment
        forecast_reference = None if forecast is None else forecast.reference
        forecast_at = None if forecast is None else forecast.evaluated_at
        if prior is not None and prior.attempted:
            # Never backfill/rewrite a prediction after observing an attempt's result.
            forecast_value, forecast_reference, forecast_at = (
                prior.forecast,
                prior.forecast_reference,
                prior.forecast_at,
            )
        observation = HistoricalObservation(
            reference,
            1 if prior is None else prior.sequence + 1,
            now,
            value,
            opportunity.revision,
            source,
            origin.source_reference,
            origin.observed_at,
            task_type,
            classification_evidence,
            forecast_value,
            forecast_reference,
            forecast_at,
            ledger_reference,
            budget.revision,
            tuple(
                record
                for record in budget.value.records
                if record.context.opportunity_reference == opportunity_reference
            ),
            tuple(
                auth.request.context.operation_reference
                for auth in budget.value.outstanding
                if auth.request.context.opportunity_reference == opportunity_reference
            ),
        )
        observation.require_successor(prior)
        self.history.append(observation, None if prior is None else prior.reference)
        logging.getLogger(__name__).info(
            "historical_observation_captured",
            extra={
                "opportunity_reference": opportunity_reference.value,
                "sequence": observation.sequence,
            },
        )
        return observation


@dataclass(frozen=True, slots=True)
class GetHistoricalStatistics:
    history: HistoricalRepository

    def statistics(self, query: HistoricalQuery) -> HistoricalStatistics:
        return summarize(self.history.latest(query))

    def execute(self, query: HistoricalQuery | None = None) -> HistoricalStatistics:
        return self.statistics(HistoricalQuery() if query is None else query)
