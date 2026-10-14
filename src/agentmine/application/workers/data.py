"""Deterministic-first V1 data execution; optional budgeted semantic assistance."""

import logging
from dataclasses import dataclass
from decimal import Decimal

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import AIResponse, DeliverableDraft, WorkRequest
from agentmine.application.contracts.data import DataPlan, DataRecord, DataResult
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.ports.data import DataJournal
from agentmine.application.ports.services import LLMProvider
from agentmine.application.workers.data_artifacts import artifacts
from agentmine.application.workers.data_semantic import apply_semantics, semantic_inputs
from agentmine.application.workers.data_transform import transform, validate
from agentmine.domain.finance import Cost, CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostRecord


@dataclass(frozen=True, slots=True)
class DataWorker:
    budget: BudgetManager
    journal: DataJournal
    llm: LLMProvider | None = None

    def _record(self, plan: DataPlan, cost: CostRecord | None) -> None:
        if cost is None:
            return
        auth = plan.execution.authorization
        if (
            not auth.request.context.matches_operation(cost.context)
            or cost.cost.category != CostCategory.AI
            or cost.estimated_cost != auth.request.estimated_cost
            or not auth.request.context.occurred_at
            <= cost.context.occurred_at
            <= self.budget.clock.now()
        ):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "data", "Cost scope/time mismatch")
        auth.request.estimated_cost.require_same_currency(cost.actual_cost)
        self.budget.record(auth, cost.actual_cost, cost.context.occurred_at)

    def _assist(
        self, plan: DataPlan, records: tuple[DataRecord, ...]
    ) -> tuple[tuple[DataRecord, ...], CostRecord | None]:
        inputs = semantic_inputs(plan, records)
        if not inputs:
            return records, self._zero_cost(plan)
        response = self.journal.get_response(plan.execution.reference)
        if response is None:
            deadline = plan.execution.task.deadline
            if deadline is not None and deadline <= self.budget.clock.now():
                raise ApplicationError(ApplicationErrorCode.EXPIRED, "data", "Data plan expired")
            if self.llm is None:
                raise PortError(
                    PortErrorCode.UNAVAILABLE, "data", "Semantic provider not configured"
                )
            auth = plan.execution.authorization
            self.budget.require_authorized(auth, auth.request.estimated_cost)
            if not self.journal.claim_ai(plan):
                raise PortError(
                    PortErrorCode.OUTCOME_UNKNOWN, "data", "Reconcile semantic operation"
                )
            try:
                response = self.llm.perform_work(WorkRequest(plan.execution, inputs))
            except Exception:
                raise PortError(
                    PortErrorCode.OUTCOME_UNKNOWN, "data", "Semantic outcome unknown"
                ) from None
            self.journal.save_response(plan.execution.reference, response)
        self._validate_response(plan, response)
        self._record(plan, response.actual_cost)
        return apply_semantics(plan, records, inputs, response), response.actual_cost

    def _validate_response(self, plan: DataPlan, response: AIResponse[DeliverableDraft]) -> None:
        if (
            response.operation_reference
            != plan.execution.authorization.request.context.operation_reference
        ):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "data", "Model operation mismatch")

    def _zero_cost(self, plan: DataPlan) -> CostRecord:
        request = plan.execution.authorization.request
        return CostRecord(
            Cost(
                request.context.operation_reference,
                Money(Decimal(0), request.estimated_cost.currency),
                CostCategory.AI,
            ),
            request.context,
            request.estimated_cost,
        )

    def execute(self, plan: DataPlan) -> DataResult:
        self.journal.save_plan(plan)
        cached = self.journal.get_result(plan.execution.reference)
        if cached is not None:
            self._record(plan, cached.cost)
            return cached
        response = self.journal.get_response(plan.execution.reference)
        if response is not None:
            self._validate_response(plan, response)
            self._record(plan, response.actual_cost)
        deadline = plan.execution.task.deadline
        if response is None and deadline is not None and deadline <= self.budget.clock.now():
            raise ApplicationError(ApplicationErrorCode.EXPIRED, "data", "Data plan expired")
        if any(source.collected_at > self.budget.clock.now() for source in plan.sources):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "data", "Source timestamp is in future")
        if response is None:
            auth = plan.execution.authorization
            self.budget.require_authorized(auth, auth.request.estimated_cost)
        records, issues = transform(plan)
        issues += validate(plan, records, before_ai=bool(plan.semantic_columns))
        cost: CostRecord | None = self._zero_cost(plan)
        warnings = ["source_provenance_unverified", "infrastructure_cost_not_measured"]
        if plan.semantic_columns and not issues:
            records, cost = self._assist(plan, records)
            issues = validate(plan, records)
            if any(
                cell.semantic_evidence is not None for record in records for cell in record.cells
            ):
                warnings.append("semantic_values_unverified")
        if cost is None:
            warnings.append("actual_ai_cost_unknown")
        elif cost.variance is not None and cost.variance.amount > 0:
            warnings.append("cost_estimate_exceeded")
        result = DataResult(
            plan.execution.reference,
            records,
            tuple(dict.fromkeys(issues)),
            artifacts(plan, records, issues),
            cost,
            tuple(warnings),
        )
        # Persist result before recording: a failed ledger write can recover without AI calls.
        self.journal.save_result(result)
        self._record(plan, cost)
        logging.getLogger(__name__).info(
            "data_completed",
            extra={
                "record_count": len(records),
                "valid": result.valid,
                "issue_codes": sorted({issue.code.value for issue in issues}),
            },
        )
        return result
