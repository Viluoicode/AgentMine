"""Ordered, evidence-bearing deliverable QA; never submit or grant human approval."""

import logging
from dataclasses import dataclass

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.operational_qa import QAApplicationBinding, QACompletion
from agentmine.application.contracts.qa import QAInspection, lifecycle_qa_result
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.operational_qa import OperationalQARepository
from agentmine.application.ports.qa import QAJournal
from agentmine.application.ports.repositories import ExecutionRepository, OpportunityRepository
from agentmine.application.ports.services import Clock, LLMProvider
from agentmine.application.qa.ai_review import needs_ai, review_ai
from agentmine.application.qa.checks import deterministic, domain_specific
from agentmine.application.use_cases.context import load, require_state
from agentmine.application.use_cases.execution import RunQA
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.qa import QAOutcome, QAReport


@dataclass(frozen=True, slots=True)
class DeliverableQA:
    opportunities: OpportunityRepository
    executions: ExecutionRepository
    journal: QAJournal
    clock: Clock
    budget: BudgetManager | None = None
    llm: LLMProvider | None = None
    lifecycle: OperationalQARepository | None = None

    def _apply(
        self, inspection: QAInspection, report: QAReport, binding: QAApplicationBinding | None
    ) -> None:
        if binding is not None:
            if self.lifecycle is None:
                raise PortError(
                    PortErrorCode.UNSUPPORTED, "qa", "Conditional QA completion not configured"
                )
            self.lifecycle.complete(QACompletion(binding, inspection, report))
            return
        result = lifecycle_qa_result(report)
        if result is not None:
            RunQA(self.opportunities, self.executions).execute(
                inspection.plan.execution.task.opportunity_reference, result
            )

    def execute(
        self, inspection: QAInspection, *, binding: QAApplicationBinding | None = None
    ) -> QAReport:
        if binding is not None:
            if self.lifecycle is None:
                raise PortError(
                    PortErrorCode.UNSUPPORTED, "qa", "Conditional QA completion not configured"
                )
            self.lifecycle.claim(binding, inspection)
        self.journal.save_inspection(inspection)
        cached = self.journal.get_report(inspection.reference)
        if cached is not None:
            self._apply(inspection, cached, binding)
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
        self._apply(inspection, report, binding)
        logging.getLogger(__name__).info(
            "deliverable_qa_completed",
            extra={
                "outcome": report.outcome.value,
                "check_codes": [item.code for item in report.findings],
            },
        )
        return report
