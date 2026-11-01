"""Provisional-only shared-workspace composition; no verification/provider factory."""

from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.payment_evidence import (
    GetPaymentEvidence,
    RecordPaymentEvidence,
)
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.payment_evidence import SQLitePaymentEvidenceRepository
from agentmine.presentation.payment_evidence_cli import PaymentEvidenceServices
from agentmine.presentation.submission_context_cli import SubmissionContextServices


def compose_payment_evidence(
    database: SQLiteDatabase, contexts: SubmissionContextServices, clock: Clock
) -> PaymentEvidenceServices:
    assert contexts.handoff is not None
    repository = SQLitePaymentEvidenceRepository(database)
    get = GetPaymentEvidence(repository, contexts.get.operator, contexts.get.ledger_reference)
    return PaymentEvidenceServices(
        RecordPaymentEvidence(repository, get, contexts.handoff.get, contexts.record, clock), get
    )
