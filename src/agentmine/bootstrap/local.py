"""Explicit optional local composition; importing this module performs no I/O."""

from dataclasses import dataclass
from pathlib import Path

from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.evaluations import SQLiteEvaluationRepository
from agentmine.infrastructure.sqlite.executions import SQLiteExecutionRepository
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository


@dataclass(frozen=True, slots=True)
class LocalRepositories:
    opportunities: SQLiteOpportunityRepository
    evaluations: SQLiteEvaluationRepository
    executions: SQLiteExecutionRepository
    submissions: SQLiteSubmissionRepository
    ledger: SQLiteCostLedgerRepository


def open_local_repositories(path: Path) -> LocalRepositories:
    database = SQLiteDatabase(path)
    return LocalRepositories(
        SQLiteOpportunityRepository(database),
        SQLiteEvaluationRepository(database),
        SQLiteExecutionRepository(database),
        SQLiteSubmissionRepository(database),
        SQLiteCostLedgerRepository(database),
    )
