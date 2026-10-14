"""Offline research worker contracts and recovery with injected fakes."""

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fakes import FakeClock, FakeLedger

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.ai import AIResponse, DeliverableDraft, WorkRequest
from agentmine.application.contracts.records import Versioned
from agentmine.application.contracts.research import (
    ResearchClaim,
    ResearchObservation,
    ResearchRequest,
    ResearchResult,
    ResearchStep,
    ResearchWarning,
    SourceEvidence,
    TaskPlan,
    VerificationStatus,
)
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.ports.workers import ResearchJournal, Worker
from agentmine.application.workers.research import ApprovedResearchTool, ResearchWorker
from agentmine.domain.budget import Budget, BudgetPolicy, OperatingMode
from agentmine.domain.errors import DomainError
from agentmine.domain.finance import Cost, CostCategory
from agentmine.domain.money import Money
from agentmine.domain.spending import CostContext, CostRecord, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import Execution, Task, TaskType
from agentmine.infrastructure.llm.mock import MockLLMProvider


def usd(value: str) -> Money:
    return Money(Decimal(value), "USD")


def unavailable() -> PortError:
    return PortError(PortErrorCode.UNAVAILABLE, "fake", "Injected failure")


@dataclass
class MemoryJournal:
    plans: dict[Reference, TaskPlan] = field(default_factory=dict)
    claims: dict[Reference, ResearchClaim] = field(default_factory=dict)
    observations: dict[Reference, ResearchObservation] = field(default_factory=dict)
    responses: dict[Reference, AIResponse[DeliverableDraft]] = field(default_factory=dict)

    def save_plan(self, plan: TaskPlan) -> None:
        key = plan.execution.reference
        if key in self.plans and self.plans[key] != plan:
            raise PortError(PortErrorCode.CONFLICT, "plan", "Plan changed")
        self.plans[key] = plan

    def claim(self, claim: ResearchClaim) -> bool:
        key = claim.operation_reference
        if key in self.claims:
            if self.claims[key] != claim:
                raise PortError(PortErrorCode.CONFLICT, "claim", "Claim changed")
            return False
        self.claims[key] = claim
        return True

    def get_observation(self, operation: Reference) -> ResearchObservation | None:
        return self.observations.get(operation)

    def save_observation(self, observation: ResearchObservation) -> None:
        key = observation.request.step.operation_reference
        if key in self.observations and self.observations[key] != observation:
            raise PortError(PortErrorCode.CONFLICT, "save", "Observation changed")
        self.observations[key] = observation

    def get_response(self, execution: Reference) -> AIResponse[DeliverableDraft] | None:
        return self.responses.get(execution)

    def save_response(self, execution: Reference, response: AIResponse[DeliverableDraft]) -> None:
        if execution in self.responses and self.responses[execution] != response:
            raise PortError(PortErrorCode.CONFLICT, "save", "Response changed")
        self.responses[execution] = response


@dataclass
class FakeResearch:
    clock: FakeClock
    ledger: FakeLedger
    calls: list[ResearchRequest] = field(default_factory=list)
    verified: bool = True
    actual: Money | None = field(default_factory=lambda: usd("0.1"))
    fail: bool = False
    fail_recording: bool = False
    wrong_locator: bool = False

    def collect(self, request: ResearchRequest) -> ResearchObservation:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("PRIVATE_PROVIDER_ERROR")
        source = SourceEvidence(
            request.step.operation_reference,
            request.step.tool,
            "unapproved" if self.wrong_locator else request.step.locator,
            "Recorded source",
            "The source reports 12 observations.",
            self.clock.now(),
            VerificationStatus.VERIFIED_CONTENT if self.verified else VerificationStatus.UNVERIFIED,
            "Fixture capture checked" if self.verified else "Origin could not be confirmed",
            Reference("capture-proof") if self.verified else None,
        )
        context = replace(request.authorization.request.context, occurred_at=self.clock.now())
        cost = (
            None
            if self.actual is None
            else CostRecord(
                Cost(context.operation_reference, self.actual, CostCategory.TOOL),
                context,
                request.step.estimated_cost,
            )
        )
        if self.fail_recording:
            self.ledger.fail_commit = True
        return ResearchObservation(request, source, cost)


class CountingLLM(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "fail", False)
        object.__setattr__(self, "invent_source", False)
        object.__setattr__(self, "unknown_cost", False)

    calls: list[WorkRequest]
    fail: bool
    invent_source: bool
    unknown_cost: bool

    def perform_work(self, request: WorkRequest) -> AIResponse[DeliverableDraft]:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("PRIVATE_MODEL_ERROR")
        response = super().perform_work(request)
        if self.invent_source:
            response = replace(
                response, result=replace(response.result, evidence=(Reference("fake-source"),))
            )
        if self.unknown_cost:
            response = replace(response, actual_cost=None)
        return response


@dataclass
class ResearchWorld:
    worker: ResearchWorker
    plan: TaskPlan
    tool: FakeResearch
    llm: CountingLLM
    ledger: FakeLedger
    clock: FakeClock


def make_world(journal: ResearchJournal | None = None) -> ResearchWorld:
    clock = FakeClock(datetime(2026, 10, 14, tzinfo=UTC))
    ledger = FakeLedger(
        {
            Reference("ledger"): Versioned(
                Budget(BudgetPolicy(usd("100"), usd("100"), usd("10"), usd("10"))), 1
            )
        }
    )
    manager = BudgetManager(ledger, Reference("ledger"), clock)
    decision = manager.authorize(
        usd("1"),
        CostContext(
            Reference("ai"),
            OperationType.TASK_EXECUTION,
            clock.now(),
            Reference("task"),
            Reference("opp"),
        ),
    )
    assert decision.authorization is not None
    task = Task(
        Reference("task"),
        Reference("opp"),
        TaskType.RESEARCH,
        "Research observations",
        clock.now() + timedelta(days=1),
    )
    execution = Execution(
        Reference("execution"), task, OperatingMode.FULL, clock.now(), decision.authorization
    )
    step = ResearchStep(Reference("read-1"), Reference("approved"), "fixture:one", usd("0.2"))
    plan = TaskPlan(execution, ("What did the source report?",), (step,))
    tool = FakeResearch(clock, ledger)
    llm = CountingLLM()
    approved = ApprovedResearchTool(
        Reference("approved"), tool, frozenset({"fixture:one", "fixture:two"}), usd("0.1")
    )
    return ResearchWorld(
        ResearchWorker((approved,), llm, manager, journal or MemoryJournal()),
        plan,
        tool,
        llm,
        ledger,
        clock,
    )


@pytest.fixture
def world() -> ResearchWorld:
    return make_world()


def test_worker_port_provenance_artifacts_and_costs(world: ResearchWorld) -> None:
    worker: Worker[TaskPlan, ResearchResult] = world.worker
    result = worker.execute(world.plan)
    artifacts = {item.name: item for item in result.artifacts}
    assert set(artifacts) == {"report.md", "sources.json", "findings.json"}
    assert len(result.findings.facts) == 1
    assert result.findings.facts[0].quote == result.sources[0].text
    source = json.loads(artifacts["sources.json"].content)[0]
    assert source["sha256"] == result.sources[0].content_digest
    assert source["locator"] == "fixture:one"
    assert source["verification_reference"] == "capture-proof"
    assert "## Facts" in artifacts["report.md"].content
    assert "## Analysis" in artifacts["report.md"].content
    assert "## Uncertainties" in artifacts["report.md"].content
    assert len(result.costs) == 2
    assert result.costs[0].actual_cost == usd("0.1")
    assert result.costs[0].estimated_cost == usd("0.2")
    assert len(world.ledger.snapshots[Reference("ledger")].value.records) == 2
    assert worker.execute(world.plan) == result
    assert len(world.tool.calls) == len(world.llm.calls) == 1


def test_unverified_evidence_never_becomes_fact(world: ResearchWorld) -> None:
    world.tool.verified = False
    result = world.worker.execute(world.plan)
    assert not result.findings.facts
    assert ResearchWarning.UNVERIFIED_SOURCE in result.warnings
    assert ResearchWarning.NO_VERIFIED_SOURCES in result.warnings
    assert result.sources[0].verification_reference is None


@pytest.mark.parametrize("unknown", ["tool", "llm"])
def test_unknown_cost_not_zero(unknown: str, world: ResearchWorld) -> None:
    if unknown == "tool":
        world.tool.actual = None
    else:
        object.__setattr__(world.llm, "unknown_cost", True)
    result = world.worker.execute(world.plan)
    assert ResearchWarning.UNKNOWN_COST in result.warnings
    assert len(world.ledger.snapshots[Reference("ledger")].value.outstanding) == 1


def test_model_cannot_invent_sources(world: ResearchWorld) -> None:
    object.__setattr__(world.llm, "invent_source", True)
    with pytest.raises(PortError) as error:
        world.worker.execute(world.plan)
    assert error.value.code == PortErrorCode.INVALID_RESPONSE
    assert len(world.ledger.snapshots[Reference("ledger")].value.records) == 2


@pytest.mark.parametrize("change", ["tool", "locator", "estimate"])
def test_approval_enforced_before_any_io(change: str, world: ResearchWorld) -> None:
    step = world.plan.sources[0]
    if change == "tool":
        step = replace(step, tool=Reference("unapproved"))
    elif change == "locator":
        step = replace(step, locator="https://unapproved.invalid/")
    else:
        step = replace(step, estimated_cost=usd("0"))
    with pytest.raises(PortError):
        world.worker.execute(replace(world.plan, sources=(step,)))
    assert not world.tool.calls and not world.llm.calls


def test_expired_plan_no_dispatch(world: ResearchWorld) -> None:
    world.clock.instant += timedelta(days=1)
    with pytest.raises(ApplicationError):
        world.worker.execute(world.plan)
    assert not world.tool.calls


def test_budget_denial_no_dispatch(world: ResearchWorld) -> None:
    snapshot = world.ledger.snapshots[Reference("ledger")]
    world.ledger.snapshots[Reference("ledger")] = Versioned(
        snapshot.value.with_requested_mode(OperatingMode.SCOUT_ONLY), snapshot.revision + 1
    )
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    assert not world.tool.calls and not world.llm.calls


def test_tool_budget_denial_no_dispatch(world: ResearchWorld) -> None:
    step = replace(world.plan.sources[0], estimated_cost=usd("20"))
    with pytest.raises(ApplicationError):
        world.worker.execute(replace(world.plan, sources=(step,)))
    assert not world.tool.calls


def test_cost_overrun_retained(world: ResearchWorld) -> None:
    world.tool.actual = usd("0.3")
    assert ResearchWarning.COST_ESTIMATE_EXCEEDED in world.worker.execute(world.plan).warnings


def test_recover_recording_failure_without_redispatch(world: ResearchWorld) -> None:
    world.tool.fail_recording = True
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    world.ledger.fail_commit = False
    result = world.worker.execute(world.plan)
    assert len(result.costs) == 2
    assert len(world.tool.calls) == 1


@pytest.mark.parametrize("target", ["tool", "llm"])
def test_unknown_external_outcome_never_retried(target: str, world: ResearchWorld) -> None:
    if target == "tool":
        world.tool.fail = True
    else:
        object.__setattr__(world.llm, "fail", True)
    for _ in range(2):
        with pytest.raises(PortError) as error:
            world.worker.execute(world.plan)
        assert error.value.code == PortErrorCode.OUTCOME_UNKNOWN
        assert "PRIVATE" not in str(error.value)
    assert len(world.tool.calls) == 1
    assert len(world.llm.calls) == (0 if target == "tool" else 1)


def test_conflicting_plan_rejected(world: ResearchWorld) -> None:
    world.worker.execute(world.plan)
    with pytest.raises(PortError):
        world.worker.execute(replace(world.plan, questions=("Changed objective",)))
    assert len(world.tool.calls) == 1


def test_wrong_source_provenance_rejected_after_cost_recorded(world: ResearchWorld) -> None:
    world.tool.wrong_locator = True
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    assert len(world.ledger.snapshots[Reference("ledger")].value.records) == 1
    assert not world.llm.calls


def test_plan_rejects_unsupported_task_and_duplicate_steps(world: ResearchWorld) -> None:
    execution = replace(
        world.plan.execution,
        task=replace(world.plan.execution.task, task_type=TaskType.DATA_PROCESSING),
    )
    with pytest.raises(DomainError):
        replace(world.plan, execution=execution)
    with pytest.raises(DomainError):
        replace(world.plan, sources=world.plan.sources * 2)
    with pytest.raises(DomainError):
        replace(world.plan, questions=())


def test_multiple_sources_keep_separate_provenance(world: ResearchWorld) -> None:
    second = replace(
        world.plan.sources[0], operation_reference=Reference("read-2"), locator="fixture:two"
    )
    result = world.worker.execute(replace(world.plan, sources=(*world.plan.sources, second)))
    assert len(result.sources) == len(result.findings.facts) == 2
    assert {source.locator for source in result.sources} == {"fixture:one", "fixture:two"}
    assert len(result.costs) == 3


def test_recovery_from_cached_llm_response_after_cost_failure(world: ResearchWorld) -> None:
    journal = world.worker.journal
    original = world.llm.perform_work

    def respond_then_break_ledger(request: WorkRequest) -> AIResponse[DeliverableDraft]:
        result = original(request)
        world.ledger.fail_commit = True
        return result

    object.__setattr__(world.llm, "perform_work", respond_then_break_ledger)
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    assert journal.get_response(world.plan.execution.reference) is not None
    world.ledger.fail_commit = False
    result = world.worker.execute(world.plan)
    assert len(result.costs) == 2
    assert len(world.tool.calls) == len(world.llm.calls) == 1


def test_unverified_capture_requires_no_verification_claim(world: ResearchWorld) -> None:
    world.tool.verified = False
    result = world.worker.execute(world.plan)
    source = result.sources[0]
    with pytest.raises(DomainError):
        replace(source, status=VerificationStatus.VERIFIED_CONTENT)


def test_completed_result_replay_after_deadline_is_read_only(world: ResearchWorld) -> None:
    result = world.worker.execute(world.plan)
    revision = world.ledger.snapshots[Reference("ledger")].revision
    world.clock.instant += timedelta(days=2)
    assert world.worker.execute(world.plan) == result
    assert world.ledger.snapshots[Reference("ledger")].revision == revision
    assert len(world.tool.calls) == len(world.llm.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        "plain text",
        "{}",
        '{"plan":[],"content":"x","evidence":[]}',
        '{"plan":["x"],"content":"x","content":"y","evidence":[]}',
        '{"plan":["x"],"content":"x","evidence":["source-9"]}',
    ],
)
def test_worker_revalidates_model_schema(payload: str, world: ResearchWorld) -> None:
    original = world.llm.perform_work

    def malformed(request: WorkRequest) -> AIResponse[DeliverableDraft]:
        response = original(request)
        return replace(response, result=DeliverableDraft(payload, ()))

    object.__setattr__(world.llm, "perform_work", malformed)
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    assert len(world.ledger.snapshots[Reference("ledger")].value.records) == 2


def test_model_analysis_stays_separate_from_source_facts(world: ResearchWorld) -> None:
    object.__setattr__(
        world.llm,
        "responses",
        {
            "research": json.dumps(
                {
                    "plan": ["Summarize"],
                    "content": "My interpretation, not independently verified.",
                    "evidence": ["source-0"],
                }
            )
        },
    )
    result = world.worker.execute(world.plan)
    assert result.findings.analysis == "My interpretation, not independently verified."
    assert result.findings.facts[0].quote == "The source reports 12 observations."
    assert result.findings.facts[0].quote != result.findings.analysis
