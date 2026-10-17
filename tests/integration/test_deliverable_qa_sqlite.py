"""Real SQLite QA journal and interchangeable repository ports, offline."""

from dataclasses import replace
from pathlib import Path

import pytest
from data_fakes import make_data_world
from qa_fakes import inspection_for, seed

from agentmine.application.errors import PortError
from agentmine.application.use_cases.deliverable_qa import DeliverableQA
from agentmine.bootstrap.local import open_local_repositories
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAOutcome
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.qa import SQLiteQAJournal


def test_sqlite_report_reopen_and_idempotency(tmp_path: Path) -> None:
    path = tmp_path / "qa.db"
    world = make_data_world()
    inspection = inspection_for(world.plan, world.worker.execute(world.plan))
    repos = open_local_repositories(path)
    journal = SQLiteQAJournal(SQLiteDatabase(path))
    seed(inspection, repos.opportunities, repos.executions)
    qa = DeliverableQA(repos.opportunities, repos.executions, journal, world.clock)
    report = qa.execute(inspection)
    reopened = SQLiteQAJournal(SQLiteDatabase(path))
    assert reopened.get_report(inspection.reference) == report
    assert report.outcome == QAOutcome.PASS
    assert qa.execute(inspection) == report
    stored = repos.opportunities.get(Reference("opp"))
    assert stored is not None
    assert stored.value.state == OpportunityState.READY_FOR_HUMAN_REVIEW
    assert stored.value.approval is None
    with pytest.raises(PortError):
        reopened.save_inspection(replace(inspection, min_verified_sources=2))


def test_sqlite_ai_claim_and_response_reopen(tmp_path: Path) -> None:
    from qa_fakes import QAProvider

    from agentmine.application.budget_manager import BudgetManager
    from agentmine.application.contracts.qa import CoverageKind
    from agentmine.domain.spending import CostContext, OperationType

    world = make_data_world()
    inspection = inspection_for(world.plan, world.worker.execute(world.plan))
    manager = BudgetManager(world.ledger, Reference("ledger"), world.clock)
    decision = manager.authorize(
        world.plan.execution.authorization.request.estimated_cost,
        CostContext(
            Reference("qa"),
            OperationType.QA,
            world.clock.now(),
            world.plan.execution.task.reference,
            Reference("opp"),
        ),
    )
    inspection = replace(
        inspection,
        requirements=(replace(inspection.requirements[0], kind=CoverageKind.SEMANTIC),),
        ai_authorization=decision.authorization,
    )
    path = tmp_path / "qa.db"
    repos = open_local_repositories(path)
    journal = SQLiteQAJournal(SQLiteDatabase(path))
    seed(inspection, repos.opportunities, repos.executions)
    llm = QAProvider()
    report = DeliverableQA(
        repos.opportunities, repos.executions, journal, world.clock, manager, llm
    ).execute(inspection)
    reopened = SQLiteQAJournal(SQLiteDatabase(path))
    assert reopened.get_response(inspection.reference) == journal.get_response(inspection.reference)
    assert reopened.get_report(inspection.reference) == report
    assert not reopened.claim_ai(inspection)
    with pytest.raises(PortError):
        reopened.claim_ai(replace(inspection, reference=Reference("different-inspection")))
