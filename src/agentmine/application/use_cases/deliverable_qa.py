"""Ordered, evidence-bearing deliverable QA; never submit or grant human approval."""

import json
import logging
from dataclasses import dataclass

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.qa import QAInspection
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.qa import QAJournal
from agentmine.application.ports.repositories import ExecutionRepository, OpportunityRepository
from agentmine.application.ports.services import Clock, LLMProvider
from agentmine.application.qa.ai_review import needs_ai, review_ai
from agentmine.application.qa.checks import deterministic, domain_specific
from agentmine.application.use_cases.context import load, require_state
from agentmine.application.use_cases.execution import RunQA
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAOutcome, QAReport
from agentmine.domain.work import QAResult, QAStatus


@dataclass(frozen=True, slots=True)
class DeliverableQA:
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    journal: QAJournal
    clock: Clock
    budget: BudgetManager | None = None
    llm: LLMProvider | None = None

    def _apply(self, inspection: QAInspection, report: QAReport) -> None:
        if report.outcome == QAOutcome.REQUIRES_HUMAN_REVIEW:
            return  # Remains QA_PENDING, never implies passing QA or approval.
        status = QAStatus.PASSED if report.outcome == QAOutcome.PASS else QAStatus.FAILED
        findings = json.dumps(
            {
                "report": report.reference.value,
                "outcome": report.outcome.value,
                "checks": [
                    {
                        "stage": item.stage.value,
                        "code": item.code,
                        "outcome": item.outcome.value,
                        "explanation": item.explanation,
                        "evidence": [ref.value for ref in item.evidence],
                    }
                    for item in report.findings
                ],
            },
            sort_keys=True,
        )
        RunQA(self.opportunities, self.executions).execute(
            inspection.plan.execution.task.opportunity_reference,
            QAResult(report.deliverable, status, findings),
        )

    def execute(self, inspection: QAInspection) -> QAReport:
        self.journal.save_inspection(inspection)
        cached = self.journal.get_report(inspection.reference)
        if cached is not None:
            self._apply(inspection, cached)
            return cached
        opportunity = load(
            self.opportunities, inspection.plan.execution.task.opportunity_reference
        ).value
        require_state(opportunity, OpportunityState.QA_PENDING)
        if (
            opportunity.execution != inspection.plan.execution
            or opportunity.deliverable != inspection.deliverable
            or self.executions.get_deliverable(
                inspection.deliverable.reference, inspection.deliverable.version
            )
            != inspection.deliverable
        ):
            raise PortError(
                PortErrorCode.CONFLICT, "qa", "Current execution/deliverable version mismatch"
            )
        stored = self.executions.get_content(inspection.deliverable.content_reference)
        contents = (
            None
            if stored is None or stored.reference != inspection.deliverable.content_reference
            else stored.text
        )
        checks = deterministic(inspection, contents)
        if all(item.outcome == QAOutcome.PASS for item in checks):
            checks += domain_specific(inspection, self.clock.now())
        if all(item.outcome == QAOutcome.PASS for item in checks) and needs_ai(inspection):
            assert contents is not None
            checks += (
                review_ai(
                    inspection,
                    ReferencedText(inspection.deliverable.content_reference, contents),
                    self.journal,
                    self.clock,
                    self.budget,
                    self.llm,
                ),
            )
        report = QAReport(inspection.reference, inspection.deliverable, self.clock.now(), checks)
        self.journal.save_report(
            report
        )  # Recover transition conflicts without recomputing/repaying.
        self._apply(inspection, report)
        logging.getLogger(__name__).info(
            "deliverable_qa_completed",
            extra={
                "outcome": report.outcome.value,
                "check_codes": [item.code for item in report.findings],
            },
        )
        return report
