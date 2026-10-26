"""Explicit real local runtime composition on one authoritative SQLite database."""

from pathlib import Path

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.application.use_cases.local_runtime import (
    ExportDataArtifacts,
    GetDataSpecification,
    GetOperatorOpportunity,
    GetWorkerRuntime,
    PrepareDataSpecification,
    RecoverDataExecution,
)
from agentmine.application.use_cases.planning import EvaluateOpportunity, PlanTask, ScoreOpportunity
from agentmine.application.use_cases.worker_execution import ExecuteWorkerTask
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.values import Reference
from agentmine.infrastructure.local_artifact_export import LocalArtifactExporter
from agentmine.infrastructure.local_data_inputs import LocalDataInputReader
from agentmine.infrastructure.sqlite.approval import SQLiteApprovalRepository
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.eligibility_review import SQLiteEligibilityReviewRepository
from agentmine.infrastructure.sqlite.evaluations import SQLiteEvaluationRepository
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository
from agentmine.presentation.runtime_cli import RuntimeServices


def compose_local_runtime(
    database: SQLiteDatabase,
    ledger_reference: Reference,
    operator: Reference,
    clock: Clock,
    source: OpportunitySource,
    input_root: Path | None,
    export_directory: Path | None,
) -> RuntimeServices:
    opportunities = SQLiteOpportunityRepository(database)
    evaluations = SQLiteEvaluationRepository(database)
    runtime = SQLiteWorkerRuntimeRepository(database)
    reviews = SQLiteEligibilityReviewRepository(database)
    budget = BudgetManager(
        SQLiteCostLedgerRepository(database),
        ledger_reference,
        clock,
        SQLiteApprovalRepository(database),
    )
    execution = ExecuteWorkerTask(
        opportunities,
        evaluations,
        runtime,
        budget,
        SQLiteDataJournal(database),
        source,
        operator,
        reviews,
    )
    return RuntimeServices(
        GetOperatorOpportunity(opportunities),
        lambda policy: CheckEligibility(opportunities, source, clock, EligibilityEngine(policy)),
        EvaluateOpportunity(opportunities, source, clock),
        lambda policy: ScoreOpportunity(opportunities, evaluations, source, clock, policy),
        PlanTask(opportunities, source, clock),
        PrepareDataSpecification(
            opportunities,
            evaluations,
            runtime,
            LocalDataInputReader(input_root),
            source,
            clock,
            operator,
            ledger_reference,
            reviews,
        ),
        GetDataSpecification(runtime),
        GetWorkerRuntime(runtime),
        execution,
        RecoverDataExecution(runtime, execution),
        ExportDataArtifacts(runtime, LocalArtifactExporter(export_directory), operator),
    )
