"""Worker capabilities and recovery ownership; no vendor APIs."""

from typing import Protocol

from agentmine.application.contracts.ai import AIResponse, DeliverableDraft
from agentmine.application.contracts.research import (
    ResearchClaim,
    ResearchObservation,
    ResearchRequest,
    ResearchResult,
    TaskPlan,
)
from agentmine.domain.values import Reference


class Worker(Protocol):
    def execute(self, plan: TaskPlan) -> ResearchResult: ...


class ResearchTool(Protocol):
    """One authorized read; preserve provenance, measured cost and explicit verification.

    No writes, automatic retries, redirects to unapproved targets, or generated sources.
    Translate failures to safe PortError; unknown billing is never zero.
    """

    def collect(self, request: ResearchRequest) -> ResearchObservation: ...


class ResearchJournal(Protocol):
    """Immutable plan/results and atomic one-owner claims, durable in production.

    Equal saves are idempotent; conflicting identities fail. A claim without a
    result is ambiguous and must never be dispatched again automatically.
    """

    def save_plan(self, plan: TaskPlan) -> None: ...
    def claim(self, claim: ResearchClaim) -> bool: ...
    def get_observation(self, operation: Reference) -> ResearchObservation | None: ...
    def save_observation(self, observation: ResearchObservation) -> None: ...
    def get_response(self, execution: Reference) -> AIResponse[DeliverableDraft] | None: ...
    def save_response(
        self, execution: Reference, response: AIResponse[DeliverableDraft]
    ) -> None: ...
