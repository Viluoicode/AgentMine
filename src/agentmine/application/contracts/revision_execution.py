"""Operator proposal inputs; execution accepts only an allocated revision identity."""

from dataclasses import dataclass

from agentmine.application.contracts.data_revision import RevisionTrigger
from agentmine.application.contracts.local_runtime import PrepareDataRequest
from agentmine.domain.economics import EconomicInputs
from agentmine.domain.scoring import ScoringPolicy, ScoringSignals
from agentmine.domain.values import Reference, require_reference


@dataclass(frozen=True, slots=True)
class PrepareRevisionRequest:
    reference: Reference
    parent_execution: Reference
    trigger: RevisionTrigger
    trigger_reference: Reference
    work: PrepareDataRequest
    economics: EconomicInputs
    signals: ScoringSignals
    scoring_policy: ScoringPolicy
    reason: str
    forecast_evidence: tuple[Reference, ...]

    def __post_init__(self) -> None:
        for value in (self.reference, self.parent_execution, self.trigger_reference):
            require_reference(value, "revision")
        if not isinstance(self.forecast_evidence, tuple) or not self.forecast_evidence:
            raise ValueError("Explicit subjective forecast evidence required")
        for value in self.forecast_evidence:
            require_reference(value, "forecast")
