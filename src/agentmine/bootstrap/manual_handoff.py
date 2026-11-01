"""Shared-workspace offline composition with default-denied channel permissions."""

from agentmine.application.ports.manual_handoff import ManualChannelPermission
from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.manual_handoff import (
    ConfirmManualHandoff,
    GetManualHandoff,
    InspectManualReadiness,
    PrepareManualHandoff,
    RecordManualHandoffReceipt,
)
from agentmine.infrastructure.manual_permission import UnverifiedManualChannel
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.manual_handoff import SQLiteManualHandoffRepository
from agentmine.presentation.manual_handoff_cli import ManualHandoffServices
from agentmine.presentation.runtime_cli import RuntimeServices
from agentmine.presentation.submission_context_cli import SubmissionContextServices


def compose_manual_handoff(
    database: SQLiteDatabase,
    runtime: RuntimeServices,
    contexts: SubmissionContextServices,
    clock: Clock,
    permission: ManualChannelPermission | None,
) -> ManualHandoffServices:
    repository = SQLiteManualHandoffRepository(database)
    readiness = InspectManualReadiness(
        contexts.get,
        contexts.consent,
        runtime.qa.opportunities,
        SQLiteCostLedgerRepository(database),
        UnverifiedManualChannel(clock) if permission is None else permission,
        runtime.qa.preflight,
        runtime.status.runtime,
        runtime.qa.executions,
        runtime.qa.repository,
        runtime.qa.journal,
        clock,
    )
    get = GetManualHandoff(repository, contexts.get)
    return ManualHandoffServices(
        readiness,
        PrepareManualHandoff(repository, get, readiness),
        ConfirmManualHandoff(repository, get, readiness),
        get,
        RecordManualHandoffReceipt(repository, get, contexts.record, clock),
    )
