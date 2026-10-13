"""Persistence capabilities required by application workflows, not database APIs."""

from typing import Protocol

from agentmine.application.contracts.ai import AIResponse, DeliverableDraft, ReferencedText
from agentmine.application.contracts.opportunities import OpportunityObservation
from agentmine.application.contracts.records import (
    BudgetCommit,
    EvaluationRecord,
    OpportunitySave,
    Versioned,
)
from agentmine.application.contracts.submission import SubmissionRequest, SubmissionResult
from agentmine.application.contracts.workflow import ExecuteTaskRequest
from agentmine.domain.budget import Budget
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable, Execution, Outcome, QAResult, Submission


class OpportunityRepository(Protocol):
    """Preserve the complete aggregate; conditional saves reject stale revisions."""

    def get(self, reference: Reference) -> Versioned[Opportunity] | None: ...

    def save(self, request: OpportunitySave) -> Versioned[Opportunity]: ...

    def save_observation(self, observation: OpportunityObservation) -> None: ...

    def get_observation(self, reference: Reference) -> OpportunityObservation | None: ...


class EvaluationRepository(Protocol):
    """Immutable assessment history; same identity/content retries are idempotent."""

    def save(self, evaluation: EvaluationRecord) -> None: ...

    def get(self, reference: Reference) -> EvaluationRecord | None: ...

    def for_opportunity(self, reference: Reference) -> tuple[EvaluationRecord, ...]: ...


class ExecutionRepository(Protocol):
    """Execution evidence and immutable deliverable versions/QA history."""

    def save(self, execution: Execution) -> None: ...

    def get(self, reference: Reference) -> Execution | None: ...

    def save_deliverable(self, deliverable: Deliverable) -> None: ...

    def get_deliverable(self, reference: Reference, version: int) -> Deliverable | None: ...

    def save_qa(self, result: QAResult) -> None: ...

    def get_qa(self, deliverable_reference: Reference, version: int) -> QAResult | None: ...

    def save_content(self, content: ReferencedText) -> None: ...

    def get_content(self, reference: Reference) -> ReferencedText | None: ...

    def save_work_request(self, request: ExecuteTaskRequest) -> None: ...

    def get_work_request(self, execution_reference: Reference) -> ExecuteTaskRequest | None: ...

    def save_work_response(
        self, execution_reference: Reference, response: AIResponse[DeliverableDraft]
    ) -> None: ...

    def get_work_response(
        self, execution_reference: Reference
    ) -> AIResponse[DeliverableDraft] | None: ...


class SubmissionRepository(Protocol):
    """Intent/attempt journal, confirmed receipts and outcomes; no submission I/O."""

    def save_request(self, request: SubmissionRequest) -> None: ...

    def claim_request(self, request: SubmissionRequest) -> bool:
        """Atomically create intent and grant dispatch once; identical retries return False."""
        ...

    def get_request(self, reference: Reference) -> SubmissionRequest | None: ...

    def record_attempt(self, result: SubmissionResult) -> None: ...

    def attempts_for(self, reference: Reference) -> tuple[SubmissionResult, ...]: ...

    def save(self, submission: Submission) -> None: ...

    def get(self, reference: Reference) -> Submission | None: ...

    def save_outcome(self, outcome: Outcome) -> None: ...

    def get_outcome(self, submission_reference: Reference) -> Outcome | None: ...


class CostLedgerRepository(Protocol):
    """Atomic conditional budget/audit writes; never authorize spending itself."""

    def get(self, ledger_reference: Reference) -> Versioned[Budget] | None: ...

    def commit(self, request: BudgetCommit) -> Versioned[Budget]: ...
