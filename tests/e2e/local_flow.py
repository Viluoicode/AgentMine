"""Offline test composition; no lifecycle shortcuts or pre-seeded completed aggregates."""

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fakes import (
    FakeClock,
    FakeGateway,
    FakeSource,
    FakeVerifier,
    economic_inputs,
    eligibility_request,
    scoring_policy,
    scoring_signals,
)

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.data import (
    DataColumn,
    DataFormat,
    DataPlan,
    DataResult,
    DataSource,
    TextCase,
    ValueKind,
)
from agentmine.application.contracts.opportunities import DiscoveryRequest, OpportunityObservation
from agentmine.application.contracts.qa import (
    ArtifactFormat,
    CoverageKind,
    QAInspection,
    QARequirement,
    RequiredArtifact,
    bundle_content,
)
from agentmine.application.contracts.records import BudgetCommit, OpportunitySave
from agentmine.application.contracts.research import (
    ResearchObservation,
    ResearchRequest,
    ResearchResult,
    ResearchStep,
    SourceEvidence,
    TaskPlan,
    VerificationStatus,
)
from agentmine.application.contracts.submission import OutcomeObservation
from agentmine.application.contracts.workflow import PlanTaskRequest, ScoreRequest
from agentmine.application.use_cases import (
    CheckEligibility,
    DiscoverOpportunities,
    EvaluateOpportunity,
    NormalizeOpportunity,
    PlanTask,
    ScoreOpportunity,
)
from agentmine.application.use_cases.context import refresh
from agentmine.application.workers.data import DataWorker
from agentmine.application.workers.research import ApprovedResearchTool, ResearchWorker
from agentmine.bootstrap.local import LocalRepositories, open_local_repositories
from agentmine.domain.budget import Budget, BudgetPolicy
from agentmine.domain.eligibility import EligibilityPolicy
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.finance import Cost, CostCategory, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import AuthorizationStatus, CostContext, CostRecord, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import (
    Deliverable,
    Execution,
    Outcome,
    OutcomeStatus,
    Submission,
    TaskType,
)
from agentmine.infrastructure.llm.mock import MockLLMProvider
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.research import SQLiteResearchJournal


def usd(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


def fixture(name: str) -> str:
    return (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")


@dataclass
class FixtureResearchTool:
    clock: FakeClock
    calls: int = 0

    def collect(self, request: ResearchRequest) -> ResearchObservation:
        self.calls += 1
        assert request.step.locator == "fixture:research.txt"
        context = request.authorization.request.context
        return ResearchObservation(
            request,
            SourceEvidence(
                request.step.operation_reference,
                request.step.tool,
                request.step.locator,
                "Synthetic local evidence",
                fixture("research.txt"),
                self.clock.now(),
                VerificationStatus.VERIFIED_CONTENT,
                "Read exact committed fixture bytes; not verified real-world research",
                Reference("fixture:research.txt"),
            ),
            CostRecord(
                Cost(context.operation_reference, usd("0"), CostCategory.TOOL),
                context,
                request.step.estimated_cost,
            ),
        )


class FixtureGateway(FakeGateway):
    def track_outcome(self, submission: Submission) -> OutcomeObservation:
        return OutcomeObservation(
            submission.reference,
            self.clock.now(),
            Outcome(
                submission.reference,
                OutcomeStatus.ACCEPTED,
                Reference("fixture:acceptance"),
                Reward(
                    usd(str(json.loads(fixture("marketplace.json"))["accepted_reward"])),
                    RewardStage.ACCEPTED,
                    Reference("fixture:acceptance"),
                    submission.reference,
                ),
            ),
        )


@dataclass
class LocalFlow:
    path: Path
    task_type: TaskType
    clock: FakeClock = field(default_factory=lambda: FakeClock(datetime(2026, 10, 18, tzinfo=UTC)))
    reference: Reference = field(default_factory=lambda: Reference("fixture:opportunity"))
    llm: MockLLMProvider = field(default_factory=MockLLMProvider)
    repos: LocalRepositories = field(init=False)
    source: FakeSource = field(init=False)
    gateway: FixtureGateway = field(init=False)
    verifier: FakeVerifier = field(init=False)
    tool: FixtureResearchTool = field(init=False)
    states: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.repos = open_local_repositories(self.path)
        data = json.loads(fixture("marketplace.json"))
        observation = OpportunityObservation(
            Opportunity(self.reference, data["title"], Reward(usd(data["potential_reward"]))),
            Reference("fixture:listing"),
            data["requirements"],
            self.clock.now(),
            True,
            self.clock.now() + timedelta(days=3),
        )
        self.source = FakeSource(self.clock, (observation,), deadline=observation.deadline)
        self.gateway = FixtureGateway(self.clock)
        self.verifier = FakeVerifier(self.clock, usd(data["verified_reward"]))
        self.tool = FixtureResearchTool(self.clock)
        self.repos.ledger.commit(
            BudgetCommit(
                Reference("ledger"),
                Budget(BudgetPolicy(usd("100"), usd("100"), usd("10"), usd("10"))),
                None,
                None,
            )
        )

    def current(self) -> Opportunity:
        value = self.repos.opportunities.get(self.reference)
        assert value is not None
        return value.value

    def checkpoint(self, state: OpportunityState) -> None:
        before = self.current()
        assert before.state == state
        self.repos = open_local_repositories(self.path)
        assert self.current() == before
        self.states.append(state.value)

    def save(self, opportunity: Opportunity) -> None:
        old = self.repos.opportunities.get(self.reference)
        assert old is not None
        self.repos.opportunities.save(OpportunitySave(opportunity, old.revision))

    def manager(self) -> BudgetManager:
        return BudgetManager(self.repos.ledger, Reference("ledger"), self.clock)

    def context(self) -> CostContext:
        return CostContext(
            Reference("execution-cost"),
            OperationType.TASK_EXECUTION,
            self.clock.now(),
            Reference("task"),
            self.reference,
        )

    def discover_to_score(self) -> None:
        DiscoverOpportunities(self.source, self.repos.opportunities, self.clock).execute(
            DiscoveryRequest(1)
        )
        self.checkpoint(OpportunityState.DISCOVERED)
        NormalizeOpportunity(self.repos.opportunities).execute(self.reference)
        self.checkpoint(OpportunityState.NORMALIZED)
        request = eligibility_request(self.reference)
        request = replace(request, facts=replace(request.facts, task_type=self.task_type))
        CheckEligibility(
            self.repos.opportunities,
            self.source,
            self.clock,
            EligibilityEngine(EligibilityPolicy(timedelta(hours=1))),
        ).execute(request)
        self.checkpoint(OpportunityState.ELIGIBLE)
        EvaluateOpportunity(self.repos.opportunities, self.source, self.clock).execute(
            self.reference, economic_inputs()
        )
        self.checkpoint(OpportunityState.EVALUATED)
        ScoreOpportunity(
            self.repos.opportunities,
            self.repos.evaluations,
            self.source,
            self.clock,
            scoring_policy(),
        ).execute(ScoreRequest(self.reference, Reference("evaluation"), scoring_signals(), ()))
        self.checkpoint(OpportunityState.SCORED)
        assert self.current().verified_revenue == usd("0")

    def plan(self) -> None:
        PlanTask(self.repos.opportunities, self.source, self.clock).execute(
            PlanTaskRequest(
                self.reference, Reference("task"), self.task_type, "Process fixture evidence"
            )
        )
        self.checkpoint(OpportunityState.PLANNED)

    def execute_worker(self) -> QAInspection:
        """Explicit test composition of existing worker/lifecycle boundaries."""
        refresh(self.repos.opportunities, self.source, self.clock, self.reference)
        opportunity = self.current()
        assert opportunity.task is not None
        estimate = usd("1" if self.task_type == TaskType.RESEARCH else "0")
        decision = self.manager().authorize(estimate, self.context())
        assert decision.status == AuthorizationStatus.AUTHORIZED
        assert decision.authorization is not None
        execution = Execution(
            Reference("execution"),
            opportunity.task,
            decision.mode,
            self.clock.now(),
            decision.authorization,
        )
        self.repos.executions.save(execution)
        self.save(opportunity.start(execution))
        self.checkpoint(OpportunityState.IN_PROGRESS)
        database = SQLiteDatabase(self.path)
        plan: TaskPlan | DataPlan
        result: ResearchResult | DataResult
        if self.task_type == TaskType.RESEARCH:
            plan = TaskPlan(
                execution,
                ("What observations are present?",),
                (
                    ResearchStep(
                        Reference("source-read"),
                        Reference("fixture-reader"),
                        "fixture:research.txt",
                        usd("0"),
                    ),
                ),
            )
            worker = ResearchWorker(
                (
                    ApprovedResearchTool(
                        Reference("fixture-reader"),
                        self.tool,
                        frozenset({"fixture:research.txt"}),
                        usd("0"),
                    ),
                ),
                self.llm,
                self.manager(),
                SQLiteResearchJournal(database),
            )
            result = worker.execute(plan)
            assert (
                replace(worker, journal=SQLiteResearchJournal(SQLiteDatabase(self.path))).execute(
                    plan
                )
                == result
            )
            assert self.tool.calls == 1
            assert result.findings.facts[0].quote == fixture("research.txt")
            artifact, format, kind, criterion = (
                "report.md",
                ArtifactFormat.MARKDOWN,
                CoverageKind.SECTION,
                "Uncertainties",
            )
        else:
            plan = DataPlan(
                execution,
                (
                    DataSource(
                        Reference("dataset"),
                        "fixture:data.json",
                        self.clock.now(),
                        DataFormat.JSON,
                        fixture("data.json"),
                    ),
                ),
                (
                    DataColumn("id", ("id",), ValueKind.INTEGER),
                    DataColumn("name", ("name",), case=TextCase.LOWER),
                    DataColumn("samples", ("samples",), ValueKind.INTEGER, minimum=Decimal(0)),
                ),
                unique_by=("id",),
                min_records=2,
                max_records=2,
            )
            data_worker = DataWorker(self.manager(), SQLiteDataJournal(database), self.llm)
            result = data_worker.execute(plan)
            assert (
                replace(data_worker, journal=SQLiteDataJournal(SQLiteDatabase(self.path))).execute(
                    plan
                )
                == result
            )
            assert len(result.records) == 2
            artifact, format, kind, criterion = (
                "data.csv",
                ArtifactFormat.CSV,
                CoverageKind.COLUMN,
                "id",
            )
        content = bundle_content(result)
        deliverable = Deliverable(
            Reference("deliverable"), execution.reference, 1, content.reference
        )
        self.repos.executions.save_content(content)
        self.repos.executions.save_deliverable(deliverable)
        self.save(self.current().finish(deliverable))
        self.checkpoint(OpportunityState.QA_PENDING)
        return QAInspection(
            Reference("inspection"),
            deliverable,
            plan,
            result,
            (RequiredArtifact(artifact, format),),
            (QARequirement(Reference("requirement"), artifact, kind, criterion),),
        )
