"""Optional AI QA, after free checks, with budget and dispatch recovery guards."""

import json

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import QAAdvice, QARequest, ReferencedText
from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.contracts.qa import CoverageKind, QAInspection
from agentmine.application.errors import PortError
from agentmine.application.ports.qa import QAJournal
from agentmine.application.ports.services import Clock, LLMProvider
from agentmine.application.qa.checks import finding
from agentmine.domain.finance import CostCategory
from agentmine.domain.qa import QAFinding, QAOutcome, QAStage
from agentmine.domain.work import QAStatus


def needs_ai(inspection: QAInspection) -> bool:
    return any(item.kind == CoverageKind.SEMANTIC for item in inspection.requirements) or (
        isinstance(inspection.plan, DataPlan)
        and isinstance(inspection.result, DataResult)
        and any(
            cell.semantic_evidence is not None
            for row in inspection.result.records
            for cell in row.cells
        )
    )


def review_ai(
    inspection: QAInspection,
    content: ReferencedText,
    journal: QAJournal,
    clock: Clock,
    budget: BudgetManager | None,
    llm: LLMProvider | None,
) -> QAFinding:
    def unresolved(code: str, explanation: str) -> QAFinding:
        return finding(inspection, QAStage.AI, code, QAOutcome.REQUIRES_HUMAN_REVIEW, explanation)

    authorization = inspection.ai_authorization
    if authorization is None or budget is None or llm is None:
        return unresolved(
            "AI_REVIEW_UNAVAILABLE",
            "Semantic review required but provider/budget authorization is absent.",
        )
    response = journal.get_response(inspection.reference)
    if response is None:
        deadline = inspection.plan.execution.task.deadline
        if deadline is not None and deadline <= clock.now():
            return unresolved("QA_DEADLINE_EXPIRED", "No new paid review after task deadline.")
        try:
            budget.require_authorized(authorization, authorization.request.estimated_cost)
        except PortError:
            return unresolved(
                "AI_BUDGET_UNAVAILABLE", "Current persisted budget does not authorize AI QA."
            )
        if not journal.claim_ai(inspection):
            return unresolved(
                "AI_OUTCOME_UNKNOWN", "Prior AI dispatch has no response; reconcile before retry."
            )
        criteria = [
            item.criterion for item in inspection.requirements if item.kind == CoverageKind.SEMANTIC
        ]
        if isinstance(inspection.plan, DataPlan):
            criteria += [
                column.semantic_reason or "" for column in inspection.plan.semantic_columns
            ]
        request = QARequest(
            inspection.plan.execution,
            inspection.deliverable,
            content,
            json.dumps({"semantic_criteria": criteria}),
            authorization,
            deterministic_insufficient=True,
        )
        try:
            response = llm.review_deliverable(request)
        except Exception:
            return unresolved(
                "AI_OUTCOME_UNKNOWN",
                "Provider did not return a usable response; cost may be unknown.",
            )
        journal.save_response(inspection.reference, response)
    if response.operation_reference != authorization.request.context.operation_reference:
        return unresolved(
            "AI_RESPONSE_MISMATCH", "Response operation does not match QA authorization."
        )
    cost = response.actual_cost
    if cost is not None:
        if (
            cost.cost.category != CostCategory.AI
            or not authorization.request.context.matches_operation(cost.context)
            or cost.estimated_cost != authorization.request.estimated_cost
            or not authorization.request.context.occurred_at
            <= cost.context.occurred_at
            <= clock.now()
        ):
            return unresolved("AI_COST_MISMATCH", "Usage evidence cannot be correlated safely.")
        authorization.request.estimated_cost.require_same_currency(cost.actual_cost)
        budget.record(authorization, cost.actual_cost, cost.context.occurred_at)
    advice = response.result
    if (
        not isinstance(advice, QAAdvice)
        or advice.recommendation not in (QAStatus.PASSED, QAStatus.FAILED)
        or not isinstance(advice.findings, str)
        or not advice.findings.strip()
        or len(advice.findings) > 64_000
    ):
        return unresolved(
            "AI_SCHEMA_INVALID", "AI advice does not satisfy the QA response contract."
        )
    try:
        advice.findings.encode("utf-8")
    except UnicodeError:
        return unresolved("AI_SCHEMA_INVALID", "AI advice contains invalid text.")
    # Unknown usage must remain visible; journal retains the full response for reconciliation.
    suffix = " Actual cost unknown; reservation retained." if cost is None else " Usage recorded."
    outcome = (
        QAOutcome.PASS if advice.recommendation == QAStatus.PASSED else QAOutcome.NEEDS_REVISION
    )
    return finding(
        inspection,
        QAStage.AI,
        "AI_REVIEW_PASSED" if outcome == QAOutcome.PASS else "AI_REVISION_REQUIRED",
        outcome,
        advice.findings + suffix,
        response.evidence,
    )
