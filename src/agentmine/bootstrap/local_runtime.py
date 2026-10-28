"""Explicit real local runtime composition on one authoritative SQLite database."""

from pathlib import Path

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.data_history import (
    GetCompletedDataParent,
    GetRevisionForExecution,
    LocalDataHistory,
)
from agentmine.application.use_cases.data_revision import (
    ApproveDataRevision,
    GetDataRevision,
    PrepareDataRevision,
)
from agentmine.application.use_cases.deliverable_qa import DeliverableQA
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.application.use_cases.local_runtime import (
    ExportDataArtifacts,
    GetDataSpecification,
    GetOperatorOpportunity,
    GetWorkerRuntime,
    PrepareDataSpecification,
    RecoverDataExecution,
)
from agentmine.application.use_cases.operational_qa import (
    GetOperationalQAStatus,
    RunOperationalDataQA,
)
from agentmine.application.use_cases.planning import EvaluateOpportunity, PlanTask, ScoreOpportunity
from agentmine.application.use_cases.revision_execution import (
    ExecuteDataRevision,
    RecoverDataRevision,
)
from agentmine.application.use_cases.worker_execution import ExecuteWorkerTask
from agentmine.application.use_cases.worker_preflight import WorkerPreflight
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.values import Reference
from agentmine.infrastructure.local_artifact_export import LocalArtifactExporter
from agentmine.infrastructure.local_data_inputs import LocalDataInputReader
from agentmine.infrastructure.sqlite.approval import SQLiteApprovalRepository
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.data_revision import SQLiteRevisionRuntimeRepository
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.eligibility_review import SQLiteEligibilityReviewRepository
from agentmine.infrastructure.sqlite.evaluations import SQLiteEvaluationRepository
from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.operational_qa import SQLiteOperationalQARepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.qa import SQLiteQAJournal
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository
from agentmine.presentation.revision_cli import RevisionServices
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
    data_journal = SQLiteDataJournal(database)
    revision_repository = SQLiteRevisionRuntimeRepository(database)
    history = LocalDataHistory(runtime, revision_repository, opportunities)
    revision_get = GetDataRevision(revision_repository, operator, ledger_reference)
    revision_execute = ExecuteDataRevision(
        revision_repository, opportunities, evaluations, budget, data_journal, source, operator
    )
    execution = ExecuteWorkerTask(
        opportunities,
        evaluations,
        runtime,
        budget,
        data_journal,
        source,
        operator,
        reviews,
    )
    executions = SQLiteExecutionRepository(database)
    qa_journal = SQLiteQAJournal(database)
    qa_repository = SQLiteOperationalQARepository(database)
    validator = DeliverableQA(opportunities, executions, qa_journal, clock, lifecycle=qa_repository)
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
        GetDataSpecification(history),
        GetWorkerRuntime(history),
        execution,
        RecoverDataExecution(runtime, execution),
        ExportDataArtifacts(history, LocalArtifactExporter(export_directory), operator),
        RunOperationalDataQA(
            history,
            opportunities,
            executions,
            qa_repository,
            qa_journal,
            validator,
            WorkerPreflight(opportunities, evaluations, source, clock, operator, reviews),
            clock,
            operator,
            ledger_reference,
        ),
        GetOperationalQAStatus(history, qa_repository, qa_journal),
        RevisionServices(
            PrepareDataRevision(
                revision_repository,
                opportunities,
                source,
                clock,
                operator,
                ledger_reference,
                LocalDataInputReader(input_root),
            ),
            revision_get,
            ApproveDataRevision(
                revision_repository,
                opportunities,
                evaluations,
                source,
                clock,
                operator,
                ledger_reference,
            ),
            revision_execute,
            RecoverDataRevision(revision_execute),
            GetCompletedDataParent(revision_repository, operator, ledger_reference),
            GetRevisionForExecution(revision_repository, revision_get),
        ),
    )
