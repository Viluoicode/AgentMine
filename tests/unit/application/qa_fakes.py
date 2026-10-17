"""Reusable QA test setup using real worker outputs and public lifecycle actions."""

from dataclasses import dataclass, field
from decimal import Decimal

from fakes import FakeExecutions, FakeOpportunities, put

from agentmine.application.contracts.ai import AIResponse, QAAdvice, QARequest
from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.contracts.qa import (
    ArtifactFormat,
    CoverageKind,
    QAInspection,
    QARequirement,
    RequiredArtifact,
    bundle_content,
)
from agentmine.application.contracts.records import OpportunitySave
from agentmine.application.contracts.research import ResearchResult, TaskPlan
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.repositories import ExecutionRepository, OpportunityRepository
from agentmine.domain.finance import ExpectedValue, Reward
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.qa import QAReport
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable, Eligibility, EligibilityStatus
from agentmine.infrastructure.llm.mock import MockLLMProvider


@dataclass
class MemoryQAJournal:
    inspections: dict[Reference, QAInspection] = field(default_factory=dict)
    claims: dict[Reference, QAInspection] = field(default_factory=dict)
    responses: dict[Reference, AIResponse[QAAdvice]] = field(default_factory=dict)
    reports: dict[Reference, QAReport] = field(default_factory=dict)
    fail_report: bool = False

    def save_inspection(self, inspection: QAInspection) -> None:
        put(self.inspections, inspection.reference, inspection)

    def claim_ai(self, inspection: QAInspection) -> bool:
        assert inspection.ai_authorization is not None
        key = inspection.ai_authorization.request.context.operation_reference
        created = key not in self.claims
        put(self.claims, key, inspection)
        return created

    def get_response(self, reference: Reference) -> AIResponse[QAAdvice] | None:
        return self.responses.get(reference)

    def save_response(self, reference: Reference, response: AIResponse[QAAdvice]) -> None:
        put(self.responses, reference, response)

    def get_report(self, reference: Reference) -> QAReport | None:
        return self.reports.get(reference)

    def save_report(self, report: QAReport) -> None:
        if self.fail_report:
            raise PortError(PortErrorCode.UNAVAILABLE, "save_report", "Injected failure")
        put(self.reports, report.reference, report)


class QAProvider(MockLLMProvider):
    def __init__(self, *, passed: bool = True, fail: bool = False) -> None:
        super().__init__(
            {
                "qa": '{"recommendation": "'
                + ("passed" if passed else "failed")
                + '", "findings": "Reviewed explicit criteria"}'
            }
        )
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "fail", fail)

    calls: list[QARequest]
    fail: bool

    def review_deliverable(self, request: QARequest) -> AIResponse[QAAdvice]:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("Private provider failure")
        return super().review_deliverable(request)


def inspection_for(plan: DataPlan | TaskPlan, result: DataResult | ResearchResult) -> QAInspection:
    content = bundle_content(result)
    data = isinstance(plan, DataPlan)
    return QAInspection(
        Reference("inspection"),
        Deliverable(Reference("deliverable"), plan.execution.reference, 1, content.reference),
        plan,
        result,
        (
            RequiredArtifact(
                "data.csv" if data else "report.md",
                ArtifactFormat.CSV if data else ArtifactFormat.MARKDOWN,
            ),
        ),
        (
            QARequirement(
                Reference("requirement"),
                "data.csv" if data else "report.md",
                CoverageKind.COLUMN if data else CoverageKind.SECTION,
                "id" if data else "Uncertainties",
            ),
        ),
    )


def seed(
    inspection: QAInspection, opportunities: OpportunityRepository, executions: ExecutionRepository
) -> None:
    execution = inspection.plan.execution
    money = Money(Decimal("10"), "USD")
    op = Opportunity(execution.task.opportunity_reference, "QA fixture", Reward(money))
    op = (
        op.normalize()
        .check_eligibility()
        .assess_eligibility(Eligibility(EligibilityStatus.ELIGIBLE, "Checked"))
    )
    op = (
        op.evaluate(ExpectedValue(money, "Estimate"))
        .assign_score(Decimal(80))
        .plan(execution.task)
        .start(execution)
        .finish(inspection.deliverable)
    )
    opportunities.save(OpportunitySave(op, None))
    executions.save(execution)
    executions.save_deliverable(inspection.deliverable)
    executions.save_content(bundle_content(inspection.result))


def repositories(inspection: QAInspection) -> tuple[FakeOpportunities, FakeExecutions]:
    opportunities, executions = FakeOpportunities(), FakeExecutions()
    seed(inspection, opportunities, executions)
    return opportunities, executions
