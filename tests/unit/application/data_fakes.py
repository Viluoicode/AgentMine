"""Test-only data providers and persistence fault injection."""

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fakes import FakeClock, FakeLedger

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import (
    AIResponse,
    DeliverableDraft,
    EvaluationAdvice,
    EvaluationRequest,
    QAAdvice,
    QARequest,
    WorkRequest,
)
from agentmine.application.contracts.data import (
    DataColumn,
    DataFormat,
    DataPlan,
    DataResult,
    DataSource,
    TextCase,
    ValueKind,
)
from agentmine.application.contracts.records import Versioned
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.ports.data import DataJournal
from agentmine.application.workers.data import DataWorker
from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.finance import Cost, CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostContext, CostRecord, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import Execution, Task, TaskType


def usd(value: str) -> Money:
    return Money(Decimal(value), "USD")


def conflict() -> PortError:
    return PortError(PortErrorCode.CONFLICT, "data_test", "Injected conflict")


@dataclass
class MemoryDataJournal:
    plans: dict[Reference, DataPlan] = field(default_factory=dict)
    claims: dict[Reference, DataPlan] = field(default_factory=dict)
    responses: dict[Reference, AIResponse[DeliverableDraft]] = field(default_factory=dict)
    results: dict[Reference, DataResult] = field(default_factory=dict)
    fail_result: bool = False
    fail_response: bool = False

    def save_plan(self, plan: DataPlan) -> None:
        key = plan.execution.reference
        if key in self.plans and self.plans[key] != plan:
            raise conflict()
        self.plans[key] = plan

    def claim_ai(self, plan: DataPlan) -> bool:
        key = plan.execution.authorization.request.context.operation_reference
        if key in self.claims:
            if self.claims[key] != plan:
                raise conflict()
            return False
        self.claims[key] = plan
        return True

    def get_response(self, execution: Reference) -> AIResponse[DeliverableDraft] | None:
        return self.responses.get(execution)

    def save_response(self, execution: Reference, response: AIResponse[DeliverableDraft]) -> None:
        if self.fail_response or (
            execution in self.responses and self.responses[execution] != response
        ):
            raise conflict()
        self.responses[execution] = response

    def get_result(self, execution: Reference) -> DataResult | None:
        return self.results.get(execution)

    def save_result(self, result: DataResult) -> None:
        key = result.execution_reference
        if self.fail_result or (key in self.results and self.results[key] != result):
            raise conflict()
        self.results[key] = result


@dataclass
class FakeDataLLM:
    calls: list[WorkRequest] = field(default_factory=list)
    payload: str = field(
        default_factory=lambda: json.dumps(
            {
                "plan": ["Classify"],
                "rows": [
                    {"row_id": "row-1", "category": "research"},
                    {"row_id": "row-2", "category": "data"},
                ],
                "evidence": [],
            }
        )
    )
    actual: Money | None = field(default_factory=lambda: usd("0.25"))
    fail: bool = False
    break_ledger: FakeLedger | None = None

    def perform_work(self, request: WorkRequest) -> AIResponse[DeliverableDraft]:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("PRIVATE_FAILURE_DETAIL")
        auth = request.execution.authorization.request
        cost = (
            None
            if self.actual is None
            else CostRecord(
                Cost(auth.context.operation_reference, self.actual, CostCategory.AI),
                auth.context,
                auth.estimated_cost,
            )
        )
        if self.break_ledger is not None:
            self.break_ledger.fail_commit = True
        return AIResponse(
            auth.context.operation_reference,
            DeliverableDraft(self.payload, ()),
            cost,
            Reference("model-evidence"),
        )

    def evaluate_opportunity(self, request: EvaluationRequest) -> AIResponse[EvaluationAdvice]:
        raise AssertionError("Not used")

    def review_deliverable(self, request: QARequest) -> AIResponse[QAAdvice]:
        raise AssertionError("Not used")


@dataclass
class DataWorld:
    worker: DataWorker
    plan: DataPlan
    llm: FakeDataLLM
    ledger: FakeLedger
    clock: FakeClock


def make_data_world(
    *, semantic: bool = False, scout: bool = False, journal: DataJournal | None = None
) -> DataWorld:
    clock = FakeClock(datetime(2026, 10, 14, tzinfo=UTC))
    mode = OperatingMode.SCOUT_ONLY if scout else OperatingMode.FULL
    budget = Budget(BudgetPolicy(usd("100"), usd("100"), usd("10"), usd("10")), mode)
    ledger = FakeLedger({Reference("ledger"): Versioned(budget, 1)})
    manager = BudgetManager(ledger, Reference("ledger"), clock)
    decision = manager.authorize(
        usd("1" if semantic else "0"),
        CostContext(
            Reference("data-op"),
            OperationType.TASK_EXECUTION,
            clock.now(),
            Reference("data-task"),
            Reference("opp"),
        ),
    )
    assert decision.authorization is not None
    execution = Execution(
        Reference("data-execution"),
        Task(
            Reference("data-task"),
            Reference("opp"),
            TaskType.DATA_PROCESSING,
            "Process supplied records",
            clock.now() + timedelta(days=1),
        ),
        decision.mode,
        clock.now(),
        decision.authorization,
    )
    source = DataSource(
        Reference("input"),
        "fixture:input",
        clock.now(),
        DataFormat.JSON,
        json.dumps(
            [
                {"id": "001", "profile": {"name": " Ada "}, "count": "2"},
                {"id": "2", "profile": {"name": " Bob "}, "count": "3"},
            ]
        ),
    )
    columns: tuple[DataColumn, ...] = (
        DataColumn("id", ("id",), ValueKind.INTEGER),
        DataColumn("name", ("profile", "name"), case=TextCase.LOWER),
        DataColumn("count", ("count",), ValueKind.INTEGER, minimum=Decimal(0), maximum=Decimal(10)),
    )
    if semantic:
        columns += (
            DataColumn(
                "category",
                ("profile", "name"),
                allowed_values=("research", "data"),
                semantic_reason="Interpret the description into its topic category",
            ),
        )
    plan = DataPlan(execution, (source,), columns, unique_by=("id",))
    llm = FakeDataLLM()
    return DataWorld(
        DataWorker(manager, journal or MemoryDataJournal(), llm), plan, llm, ledger, clock
    )


def with_content(plan: DataPlan, content: str, format: DataFormat = DataFormat.JSON) -> DataPlan:
    return replace(plan, sources=(replace(plan.sources[0], content=content, format=format),))
