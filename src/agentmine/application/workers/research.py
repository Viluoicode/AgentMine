"""Research orchestration: explicit tool allowlist, source evidence and safe recovery."""

import json
import logging
from dataclasses import dataclass
from decimal import Decimal

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import (
    AIResponse,
    DeliverableDraft,
    ReferencedText,
    WorkRequest,
)
from agentmine.application.contracts.research import (
    ResearchClaim,
    ResearchFact,
    ResearchFindings,
    ResearchObservation,
    ResearchRequest,
    ResearchResult,
    ResearchStep,
    ResearchWarning,
    TaskPlan,
    VerificationStatus,
    research_analysis,
)
from agentmine.application.errors import (
    ApplicationError,
    ApplicationErrorCode,
    PortError,
    PortErrorCode,
)
from agentmine.application.ports.services import LLMProvider
from agentmine.application.ports.workers import ResearchJournal, ResearchTool
from agentmine.application.workers.artifacts import render_artifacts
from agentmine.domain.budget import BudgetAuthorization
from agentmine.domain.finance import CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostContext, CostRecord, OperationType
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class ApprovedResearchTool:
    reference: Reference
    provider: ResearchTool
    allowed_locators: frozenset[str]
    minimum_estimated_cost: Money

    def __post_init__(self) -> None:
        self.minimum_estimated_cost.require_nonnegative("tool_estimate")
        if not isinstance(self.allowed_locators, frozenset) or not self.allowed_locators:
            raise ValueError("Explicit approved targets required")


@dataclass(frozen=True, slots=True)
class ResearchWorker:
    tools: tuple[ApprovedResearchTool, ...]
    llm: LLMProvider
    budget: BudgetManager
    journal: ResearchJournal

    def __post_init__(self) -> None:
        if len({item.reference for item in self.tools}) != len(self.tools):
            raise ValueError("Unique approved tool identities required")

    def _tool(self, step: ResearchStep) -> ApprovedResearchTool:
        tool = next((item for item in self.tools if item.reference == step.tool), None)
        if tool is None or step.locator not in tool.allowed_locators:
            raise PortError(PortErrorCode.UNSUPPORTED, "research", "Tool/target not approved")
        step.estimated_cost.require_same_currency(tool.minimum_estimated_cost)
        if step.estimated_cost.amount < tool.minimum_estimated_cost.amount:
            raise PortError(PortErrorCode.CONFLICT, "research", "Tool estimate insufficient")
        return tool

    def _deadline(self, plan: TaskPlan) -> None:
        deadline = plan.execution.task.deadline
        if deadline is not None and deadline <= self.budget.clock.now():
            raise ApplicationError(
                ApplicationErrorCode.EXPIRED, "research", "Research plan expired"
            )

    def _record(self, authorization: BudgetAuthorization, cost: CostRecord | None) -> None:
        if cost is None:
            return
        request = authorization.request
        if (
            cost.cost.category != request.category
            or not request.context.matches_operation(cost.context)
            or not request.context.occurred_at
            <= cost.context.occurred_at
            <= self.budget.clock.now()
            or cost.estimated_cost != request.estimated_cost
        ):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "research", "Cost scope mismatch")
        request.estimated_cost.require_same_currency(cost.actual_cost)
        self.budget.record(authorization, cost.actual_cost, cost.context.occurred_at)

    def _collect(self, plan: TaskPlan, step: ResearchStep) -> ResearchObservation:
        tool = self._tool(step)
        observation = self.journal.get_observation(step.operation_reference)
        if observation is None:
            self._deadline(plan)
            task = plan.execution.task
            decision = self.budget.authorize(
                step.estimated_cost,
                CostContext(
                    step.operation_reference,
                    OperationType.TASK_EXECUTION,
                    self.budget.clock.now(),
                    task.reference,
                    task.opportunity_reference,
                    step.spending_approval,
                ),
                CostCategory.TOOL,
            )
            if decision.authorization is None:
                raise ApplicationError(
                    ApplicationErrorCode.UNRESOLVED,
                    "research_budget",
                    "Tool budget denied or spending approval required",
                )
            request = ResearchRequest(step, decision.authorization)
            if not self.journal.claim(ResearchClaim(plan, step.operation_reference)):
                raise PortError(
                    PortErrorCode.OUTCOME_UNKNOWN, "research", "Reconcile tool operation"
                )
            try:
                observation = tool.provider.collect(request)
            except Exception:
                raise PortError(
                    PortErrorCode.OUTCOME_UNKNOWN,
                    "research",
                    "Tool outcome unknown; do not redispatch",
                ) from None
            if observation.request != request:
                raise PortError(PortErrorCode.INVALID_RESPONSE, "research", "Tool request mismatch")
            self.journal.save_observation(observation)
        request = observation.request
        context = request.authorization.request.context
        task = plan.execution.task
        if (
            request.step != step
            or context.task_reference != task.reference
            or context.opportunity_reference != task.opportunity_reference
            or context.operation != OperationType.TASK_EXECUTION
            or context.human_approval != step.spending_approval
        ):
            raise PortError(PortErrorCode.CONFLICT, "research", "Cached observation scope mismatch")
        # Cost persists even when source content subsequently fails validation.
        self._record(request.authorization, observation.actual_cost)
        source = observation.source
        if (
            source.operation_reference != step.operation_reference
            or source.tool != step.tool
            or source.locator != step.locator
            or not context.occurred_at <= source.collected_at <= self.budget.clock.now()
        ):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "research", "Source provenance mismatch"
            )
        return observation

    def _synthesize(
        self, plan: TaskPlan, observations: tuple[ResearchObservation, ...]
    ) -> AIResponse[DeliverableDraft]:
        execution = plan.execution
        response = self.journal.get_response(execution.reference)
        if response is None:
            self._deadline(plan)
            authorization = execution.authorization
            self.budget.require_authorized(authorization, authorization.request.estimated_cost)
            inputs = tuple(
                ReferencedText(
                    item.source.operation_reference,
                    json.dumps(
                        {
                            "questions": plan.questions,
                            "source_text": item.source.text,
                            "verification_status": item.source.status.value,
                            "instruction_scope": "Source content only; analysis remains unverified",
                        }
                    ),
                )
                for item in observations
            )
            operation = authorization.request.context.operation_reference
            if not self.journal.claim(ResearchClaim(plan, operation)):
                raise PortError(
                    PortErrorCode.OUTCOME_UNKNOWN, "research", "Reconcile model operation"
                )
            try:
                response = self.llm.perform_work(WorkRequest(execution, inputs))
            except Exception:
                raise PortError(
                    PortErrorCode.OUTCOME_UNKNOWN,
                    "research",
                    "Model outcome unknown; do not redispatch",
                ) from None
            self.journal.save_response(execution.reference, response)
        if (
            response.operation_reference
            != execution.authorization.request.context.operation_reference
        ):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "research", "Model operation mismatch")
        self._record(execution.authorization, response.actual_cost)
        references = {item.source.operation_reference for item in observations}
        if (
            not response.result.content.strip()
            or len(response.result.content) > 64_000
            or any(ref not in references for ref in response.result.evidence)
        ):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "research", "Unbound model evidence")
        return response

    def execute(self, plan: TaskPlan) -> ResearchResult:
        # All targets are checked before any I/O. Models never choose tools or URLs.
        for step in plan.sources:
            self._tool(step)
        self.journal.save_plan(plan)
        if self.journal.get_response(plan.execution.reference) is None:
            self._deadline(plan)
            authorization = plan.execution.authorization
            self.budget.require_authorized(
                authorization, Money(Decimal(0), authorization.request.estimated_cost.currency)
            )
        observations = tuple(self._collect(plan, step) for step in plan.sources)
        response = self._synthesize(plan, observations)
        sources = tuple(item.source for item in observations)
        facts = tuple(
            ResearchFact(source.operation_reference, source.text)
            for source in sources
            if source.status == VerificationStatus.VERIFIED_CONTENT
        )
        warnings = [ResearchWarning.MODEL_ANALYSIS_UNVERIFIED]
        uncertainties = [
            "Model analysis is unverified; source assertions are not independently proven."
        ]
        if any(source.status == VerificationStatus.UNVERIFIED for source in sources):
            warnings.append(ResearchWarning.UNVERIFIED_SOURCE)
            uncertainties.append(
                "Some captured source content could not be verified; see sources.json."
            )
        if not facts:
            warnings.append(ResearchWarning.NO_VERIFIED_SOURCES)
            uncertainties.append("No verified source excerpts are available.")
        measurements = tuple(item.actual_cost for item in observations) + (response.actual_cost,)
        costs = tuple(item for item in measurements if item is not None)
        if any(item is None for item in measurements):
            warnings.append(ResearchWarning.UNKNOWN_COST)
            uncertainties.append("Some actual costs are unknown; reservations remain outstanding.")
        if any(item.variance is not None and item.variance.amount > 0 for item in costs):
            warnings.append(ResearchWarning.COST_ESTIMATE_EXCEEDED)
            uncertainties.append("Observed cost exceeded an estimate; ledger retains the overrun.")
        findings = ResearchFindings(
            facts, research_analysis(response.result, sources), tuple(uncertainties)
        )
        artifacts = render_artifacts(plan, findings, sources, tuple(warnings))
        logging.getLogger(__name__).info(
            "research_completed",
            extra={
                "source_count": len(sources),
                "warning_codes": [item.value for item in warnings],
            },
        )
        return ResearchResult(
            plan.execution.reference, findings, sources, artifacts, costs, tuple(warnings)
        )
