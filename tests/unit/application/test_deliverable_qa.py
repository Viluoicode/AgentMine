"""Ordered QA and recovery without network or paid providers."""

from dataclasses import replace
from datetime import timedelta

import pytest
from data_fakes import make_data_world
from qa_fakes import MemoryQAJournal, QAProvider, inspection_for, repositories
from test_research_worker import make_world

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.qa import ArtifactFormat, CoverageKind, RequiredArtifact
from agentmine.application.errors import PortError
from agentmine.application.qa.checks import deterministic, domain_specific
from agentmine.application.use_cases.deliverable_qa import DeliverableQA
from agentmine.application.workers.artifacts import render_artifacts
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAOutcome, QAStage
from agentmine.domain.spending import CostContext, OperationType
from agentmine.domain.values import Reference


@pytest.mark.parametrize("research", [False, True])
def test_pass_stops_at_human_review(research: bool) -> None:
    if research:
        research_world = make_world()
        inspection = inspection_for(
            research_world.plan, research_world.worker.execute(research_world.plan)
        )
        clock = research_world.clock
    else:
        data_world = make_data_world()
        inspection = inspection_for(data_world.plan, data_world.worker.execute(data_world.plan))
        clock = data_world.clock
    ops, executions = repositories(inspection)
    journal, llm = MemoryQAJournal(), QAProvider()
    qa = DeliverableQA(ops, executions, journal, clock, llm=llm)
    report = qa.execute(inspection)
    assert report.outcome == QAOutcome.PASS
    assert {item.stage for item in report.findings} == {
        QAStage.DETERMINISTIC,
        QAStage.DOMAIN_SPECIFIC,
    }
    assert all(item.explanation and item.evidence for item in report.findings)
    assert ops.snapshots[Reference("opp")].value.state == OpportunityState.READY_FOR_HUMAN_REVIEW
    assert ops.snapshots[Reference("opp")].value.approval is None
    assert qa.execute(inspection) == report
    assert llm.calls == []


@pytest.mark.parametrize("kind", ["missing", "format", "column", "content"])
def test_free_failure_prevents_ai(kind: str) -> None:
    world = make_data_world()
    inspection = inspection_for(world.plan, world.worker.execute(world.plan))
    if kind == "missing":
        inspection = replace(
            inspection, formats=(RequiredArtifact("absent.csv", ArtifactFormat.CSV),)
        )
    elif kind == "format":
        inspection = replace(
            inspection, formats=(RequiredArtifact("data.csv", ArtifactFormat.JSON),)
        )
    elif kind == "column":
        inspection = replace(
            inspection, requirements=(replace(inspection.requirements[0], criterion="absent"),)
        )
    ops, executions = repositories(inspection)
    if kind == "content":
        executions.contents.clear()
    llm = QAProvider()
    report = DeliverableQA(ops, executions, MemoryQAJournal(), world.clock, llm=llm).execute(
        inspection
    )
    assert report.outcome == (QAOutcome.FAIL if kind == "content" else QAOutcome.NEEDS_REVISION)
    assert all(item.stage == QAStage.DETERMINISTIC for item in report.findings)
    assert ops.snapshots[Reference("opp")].value.state == OpportunityState.IN_PROGRESS
    assert not llm.calls


@pytest.mark.parametrize("passed", [True, False])
@pytest.mark.parametrize("failure", ["", "report", "transition", "timeout", "no_auth", "expired"])
def test_optional_ai_and_recovery(passed: bool, failure: str) -> None:
    world = make_data_world()
    inspection = inspection_for(world.plan, world.worker.execute(world.plan))
    manager = BudgetManager(world.ledger, Reference("ledger"), world.clock)
    decision = manager.authorize(
        world.plan.execution.authorization.request.estimated_cost,
        CostContext(
            Reference("qa-op"),
            OperationType.QA,
            world.clock.now(),
            world.plan.execution.task.reference,
            Reference("opp"),
        ),
    )
    inspection = replace(
        inspection,
        requirements=(
            replace(
                inspection.requirements[0], kind=CoverageKind.SEMANTIC, criterion="Check meaning"
            ),
        ),
        ai_authorization=None if failure == "no_auth" else decision.authorization,
    )
    ops, executions = repositories(inspection)
    journal, llm = MemoryQAJournal(), QAProvider(passed=passed, fail=failure == "timeout")
    qa = DeliverableQA(ops, executions, journal, world.clock, manager, llm)
    if failure == "expired":
        world.clock.instant += timedelta(days=2)
    if failure in ("report", "transition"):
        journal.fail_report = failure == "report"
        ops.fail_save = failure == "transition"
        with pytest.raises(PortError):
            qa.execute(inspection)
        journal.fail_report = ops.fail_save = False
    report = qa.execute(inspection)
    expected = QAOutcome.PASS if passed else QAOutcome.NEEDS_REVISION
    if failure in ("timeout", "no_auth", "expired"):
        expected = QAOutcome.REQUIRES_HUMAN_REVIEW
        assert ops.snapshots[Reference("opp")].value.state == OpportunityState.QA_PENDING
    assert report.outcome == expected
    assert qa.execute(inspection) == report
    assert len(llm.calls) == (0 if failure in ("no_auth", "expired") else 1)
    assert journal.reports[inspection.reference] == report


@pytest.mark.parametrize("tamper", ["claim", "artifact", "source"])
def test_research_evidence_rejects_unsupported_content(tamper: str) -> None:
    world = make_world()
    result = world.worker.execute(world.plan)
    if tamper == "claim":
        findings = replace(
            result.findings, facts=(replace(result.findings.facts[0], quote="Invented fact"),)
        )
        result = replace(
            result,
            findings=findings,
            artifacts=render_artifacts(world.plan, findings, result.sources, result.warnings),
        )
    elif tamper == "artifact":
        result = replace(
            result,
            artifacts=(
                replace(result.artifacts[0], content="# Invented report"),
                *result.artifacts[1:],
            ),
        )
    else:
        result = replace(result, sources=(replace(result.sources[0], locator="fabricated"),))
    inspection = inspection_for(world.plan, result)
    checks = domain_specific(inspection, world.clock.now())
    assert any(item.outcome == QAOutcome.FAIL for item in checks)


@pytest.mark.parametrize("tamper", ["value", "provenance", "artifact"])
def test_data_consistency(tamper: str) -> None:
    world = make_data_world()
    result = world.worker.execute(world.plan)
    row = result.records[0]
    if tamper == "value":
        row = replace(row, cells=(replace(row.cells[0], value="999"), *row.cells[1:]))
    elif tamper == "provenance":
        row = replace(row, locator="fabricated")
    else:
        result = replace(
            result,
            artifacts=(replace(result.artifacts[0], content="id\n999\n"), *result.artifacts[1:]),
        )
    result = replace(result, records=(row, *result.records[1:]))
    inspection = inspection_for(world.plan, result)
    assert any(
        item.outcome == QAOutcome.FAIL for item in domain_specific(inspection, world.clock.now())
    )


def test_wrong_deliverable_version_fails_explicitly() -> None:
    world = make_data_world()
    inspection = inspection_for(world.plan, world.worker.execute(world.plan))
    ops, executions = repositories(inspection)
    changed = replace(inspection, deliverable=replace(inspection.deliverable, version=2))
    with pytest.raises(PortError):
        DeliverableQA(ops, executions, MemoryQAJournal(), world.clock).execute(changed)


def test_no_criteria_is_invalid() -> None:
    from agentmine.domain.errors import DomainError

    world = make_data_world()
    inspection = inspection_for(world.plan, world.worker.execute(world.plan))
    with pytest.raises(DomainError):
        replace(inspection, requirements=())
    assert deterministic(inspection, "wrong")[0].code == "CONTENT_MISMATCH"


@pytest.mark.parametrize("failure", ["budget", "ledger", "unknown_cost", "schema"])
def test_ai_usage_and_budget_failures(failure: str) -> None:
    from data_fakes import usd

    from agentmine.application.contracts.ai import AIResponse, QAAdvice, QARequest
    from agentmine.domain.finance import Cost, CostCategory
    from agentmine.domain.spending import CostRecord
    from agentmine.domain.work import QAStatus

    world = make_data_world()
    inspection = inspection_for(world.plan, world.worker.execute(world.plan))
    manager = BudgetManager(world.ledger, Reference("ledger"), world.clock)
    decision = manager.authorize(
        usd("1"),
        CostContext(
            Reference("qa-paid"),
            OperationType.QA,
            world.clock.now(),
            world.plan.execution.task.reference,
            Reference("opp"),
        ),
    )
    assert decision.authorization is not None
    inspection = replace(
        inspection,
        requirements=(replace(inspection.requirements[0], kind=CoverageKind.SEMANTIC),),
        ai_authorization=decision.authorization,
    )

    class Provider(QAProvider):
        def review_deliverable(self, request: QARequest) -> AIResponse[QAAdvice]:
            response = super().review_deliverable(request)
            spending = request.authorization.request
            measured = CostRecord(
                Cost(spending.context.operation_reference, usd("1.5"), CostCategory.AI),
                spending.context,
                spending.estimated_cost,
            )
            if failure == "ledger":
                world.ledger.fail_commit = True
            return replace(
                response,
                actual_cost=None if failure == "unknown_cost" else measured,
                result=QAAdvice(QAStatus.PASSED, "" if failure == "schema" else "Reviewed"),
            )

    journal, llm = MemoryQAJournal(), Provider()
    ops, executions = repositories(inspection)
    qa = DeliverableQA(ops, executions, journal, world.clock, manager, llm)
    if failure == "budget":
        # A released/consumed authorization is never reusable for a new paid dispatch.
        manager.record(decision.authorization, usd("0"), world.clock.now())
    if failure == "ledger":
        with pytest.raises(PortError):
            qa.execute(inspection)
        world.ledger.fail_commit = False
    report = qa.execute(inspection)
    assert report.outcome == (
        QAOutcome.REQUIRES_HUMAN_REVIEW if failure in ("budget", "schema") else QAOutcome.PASS
    )
    assert len(llm.calls) == (0 if failure == "budget" else 1)
    records = world.ledger.snapshots[Reference("ledger")].value.records
    if failure in ("ledger", "schema"):
        assert records[-1].actual_cost == usd("1.5")
    if failure == "unknown_cost":
        assert (
            decision.authorization in world.ledger.snapshots[Reference("ledger")].value.outstanding
        )
        assert "unknown" in report.findings[-1].explanation


def test_human_review_can_be_resolved_with_new_inspection() -> None:
    world = make_data_world()
    inspection = inspection_for(world.plan, world.worker.execute(world.plan))
    pending = replace(
        inspection, requirements=(replace(inspection.requirements[0], kind=CoverageKind.SEMANTIC),)
    )
    ops, executions = repositories(inspection)
    journal = MemoryQAJournal()
    qa = DeliverableQA(ops, executions, journal, world.clock)
    assert qa.execute(pending).outcome == QAOutcome.REQUIRES_HUMAN_REVIEW
    # Trusted caller resolves the missing semantic criterion into a deterministic one.
    resolved = replace(inspection, reference=Reference("resolved-inspection"))
    assert qa.execute(resolved).outcome == QAOutcome.PASS
    assert len(journal.reports) == 2


def test_insufficient_verified_sources_needs_human_not_ai() -> None:
    world = make_world()
    inspection = replace(
        inspection_for(world.plan, world.worker.execute(world.plan)), min_verified_sources=2
    )
    ops, executions = repositories(inspection)
    llm = QAProvider()
    report = DeliverableQA(ops, executions, MemoryQAJournal(), world.clock, llm=llm).execute(
        inspection
    )
    assert report.outcome == QAOutcome.REQUIRES_HUMAN_REVIEW
    assert any(item.code == "EVIDENCE_UNVERIFIED" for item in report.findings)
    assert not llm.calls
