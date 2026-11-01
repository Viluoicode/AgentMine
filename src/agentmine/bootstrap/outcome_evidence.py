"""Production outcome verification is unavailable; no test verifier factory or flag."""

from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.outcome_evidence import OutcomeEvidenceWorkflow
from agentmine.infrastructure.outcome_verifier import UnavailableOutcomeVerifier
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.outcome_evidence import SQLiteOutcomeEvidenceRepository
from agentmine.presentation.submission_context_cli import SubmissionContextServices


def compose_outcome_evidence(
    database: SQLiteDatabase, contexts: SubmissionContextServices, clock: Clock
) -> OutcomeEvidenceWorkflow:
    assert contexts.handoff is not None
    return OutcomeEvidenceWorkflow(
        SQLiteOutcomeEvidenceRepository(database),
        contexts.handoff.get,
        contexts.record,
        UnavailableOutcomeVerifier(clock),
        clock,
    )
