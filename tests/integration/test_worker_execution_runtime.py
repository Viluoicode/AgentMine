"""B2 acceptance: real deterministic worker and SQLite; only source observations are fake."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fakes import (
    FakeClock,
    FakeSource,
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
)
from agentmine.application.contracts.execution_evidence import DataExecutionEvidence
from agentmine.application.contracts.opportunities import (
    DiscoveryRequest,
    OpportunityObservation,
    RefreshOpportunityRequest,
)
from agentmine.application.contracts.records import BudgetCommit, OpportunitySave
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    InputEvidence,
    WorkerRunStart,
    WorkSpecification,
)
from agentmine.application.contracts.worker_execution import (
    ExecuteWorkerRequest,
    WorkerExecutionReason,
    WorkerExecutionStatus,
)
from agentmine.application.contracts.workflow import PlanTaskRequest, ScoreRequest
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.application.use_cases.eligibility_review import (
    PrepareEligibilityReview,
    ResolveEligibilityReview,
)
from agentmine.application.use_cases.planning import (
    DiscoverOpportunities,
    EvaluateOpportunity,
    NormalizeOpportunity,
    PlanTask,
    ScoreOpportunity,
)
from agentmine.application.use_cases.worker_execution import ExecuteWorkerTask
from agentmine.application.workers.data import DataWorker
from agentmine.domain.budget import AuthorizationDecision, Budget, BudgetPolicy
from agentmine.domain.economics import EstimatedCosts
from agentmine.domain.eligibility import AIParticipationPolicy, EligibilityPolicy, SubmissionSupport
from agentmine.domain.eligibility_review import EligibilityChoice, ManualEligibilityEvidence
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.finance import CostCategory, Reward
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.spending import AuthorizationStatus, BudgetReason, CostContext, OperationType
from agentmine.domain.values import Reference
from agentmine.domain.work import TaskType
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.eligibility_review import SQLiteEligibilityReviewRepository
from agentmine.infrastructure.sqlite.evaluations import SQLiteEvaluationRepository
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository
from agentmine.infrastructure.sqlite.opportunities import SQLiteOpportunityRepository
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository


def usd(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


@dataclass
class World:
    database: SQLiteDatabase
    source: FakeSource
    clock: FakeClock
    specification: WorkSpecification
    request: ExecuteWorkerRequest

    def runtime(self) -> SQLiteWorkerRuntimeRepository:
        return SQLiteWorkerRuntimeRepository(self.database)

    def budget(self) -> BudgetManager:
        return BudgetManager(
            SQLiteCostLedgerRepository(self.database), Reference("ledger"), self.clock
        )

    def use_case(self) -> ExecuteWorkerTask:
        return ExecuteWorkerTask(
            SQLiteOpportunityRepository(self.database),
            SQLiteEvaluationRepository(self.database),
            self.runtime(),
            self.budget(),
            SQLiteDataJournal(self.database),
            self.source,
            Reference("operator"),
            SQLiteEligibilityReviewRepository(self.database),
        )

    def current(self) -> Opportunity:
        value = SQLiteOpportunityRepository(self.database).get(Reference("op"))
        assert value is not None
        return value.value


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build_world(tmp_path)


def build_world(tmp_path: Path, *, manual: bool = False) -> World:
    database = SQLiteDatabase(tmp_path / "execution.sqlite3")
    clock = FakeClock(datetime(2026, 10, 25, tzinfo=UTC))
    now = clock.now()
    observation = OpportunityObservation(
        Opportunity(Reference("op"), "Normalize names", Reward(usd("20"))),
        Reference("listing:op"),
        "Normalize supplied data",
        now,
        True,
        now + timedelta(days=2),
    )
    source = FakeSource(
        clock,
        (observation,),
        deadline=observation.deadline,
        terms_reference=Reference("source:body-v1"),
        requirements=observation.requirements,
    )
    opportunities = SQLiteOpportunityRepository(database)
    evaluations = SQLiteEvaluationRepository(database)
    DiscoverOpportunities(source, opportunities, clock).execute(DiscoveryRequest(1))
    NormalizeOpportunity(opportunities).execute(Reference("op"))
    facts = eligibility_request(Reference("op"))
    facts = replace(facts, facts=replace(facts.facts, task_type=TaskType.DATA_PROCESSING))
    policy = EligibilityPolicy(timedelta(hours=1))
    review_reference = None
    if manual:
        facts = replace(facts, facts=replace(facts.facts, submission=SubmissionSupport.MANUAL))
        reviews = SQLiteEligibilityReviewRepository(database)
        review_reference = Reference("eligibility-review")
        PrepareEligibilityReview(opportunities, reviews, source, clock).execute(
            review_reference, facts, policy
        )
        ResolveEligibilityReview(
            opportunities, reviews, source, clock, Reference("operator")
        ).execute(
            review_reference,
            EligibilityChoice.APPROVE,
            "Test operator verified manual requirements",
            ManualEligibilityEvidence(
                Reference("destination"),
                Reference("instructions"),
                Reference("account-access"),
                Reference("requirements"),
                True,
            ),
        )
    else:
        CheckEligibility(opportunities, source, clock, EligibilityEngine(policy)).execute(facts)
    economics = replace(
        economic_inputs(), estimated_cost=EstimatedCosts(*(usd("0") for _ in range(4)))
    )
    EvaluateOpportunity(opportunities, source, clock).execute(Reference("op"), economics)
    ScoreOpportunity(opportunities, evaluations, source, clock, scoring_policy()).execute(
        ScoreRequest(
            Reference("op"),
            Reference("evaluation"),
            scoring_signals(),
            (Reference("operator:forecast"),),
        )
    )
    PlanTask(opportunities, source, clock).execute(
        PlanTaskRequest(
            Reference("op"), Reference("task"), TaskType.DATA_PROCESSING, "Normalize names"
        )
    )
    previous = opportunities.get(Reference("op"))
    evaluation = evaluations.get(Reference("evaluation"))
    assert previous is not None and previous.value.task is not None and evaluation is not None
    data = DataSource(
        Reference("input"),
        "operator:captured.json",
        now,
        DataFormat.JSON,
        '[{"name":" Alice "},{"name":"Bob"}]',
    )
    status = source.refresh(
        RefreshOpportunityRequest(Reference("op"), observation.source_reference)
    )
    specification = WorkSpecification(
        Reference("spec"),
        previous.value.task,
        Reference("ledger"),
        Reference("operator"),
        now,
        status,
        (data,),
        (InputEvidence(data.reference, Reference("sha256:" + data.digest)),),
        (DataColumn("name", ("name",)),),
        min_records=2,
        max_records=2,
        execution_evidence=DataExecutionEvidence(facts, policy, evaluation, review_reference),
    )
    SQLiteWorkerRuntimeRepository(database).save_specification(specification)
    budget = Budget(BudgetPolicy(usd("10"), usd("5"), usd("3"), usd("1")))
    SQLiteCostLedgerRepository(database).commit(
        BudgetCommit(Reference("ledger"), budget, None, None)
    )
    binding = ExecutionBinding(
        specification.reference,
        Reference("execution"),
        Reference("operation"),
        Reference("deliverable"),
    )
    return World(
        database, source, clock, specification, ExecuteWorkerRequest(binding, previous.revision)
    )


def test_real_worker_finishes_and_retries_without_work_or_duplicate_cost(world: World) -> None:
    result = world.use_case().execute(world.request)
    assert result.status == WorkerExecutionStatus.COMPLETED
    assert result.result is not None and len(result.result.records) == 2
    assert result.result.records[0].cells[0].value == "Alice"
    assert world.current().state == OpportunityState.QA_PENDING
    assert world.current().approval is None and world.current().submission is None
    assert world.current().verified_revenue == usd("0")
    with patch.object(DataWorker, "execute", side_effect=AssertionError("must reuse result")):
        assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED
    ledger = SQLiteCostLedgerRepository(world.database).get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.records) == 1
    assert ledger.value.records[0].actual_cost == usd("0")


@pytest.mark.parametrize("changed", ["version", "requirements", "closed", "deadline", "unknown"])
def test_changed_source_blocks_before_start(world: World, changed: str) -> None:
    if changed == "version":
        world.source.terms_reference = Reference("v2")
    elif changed == "requirements":
        world.source.requirements = "New identity requirement"
    elif changed == "closed":
        world.source.is_open = False
    elif changed == "deadline":
        world.source.deadline = world.clock.now()
    else:
        world.source.terms_reference = None
    with patch.object(DataWorker, "execute", side_effect=AssertionError("no worker")):
        outcome = world.use_case().execute(world.request)
    assert outcome.status == WorkerExecutionStatus.BLOCKED
    assert world.current().state == OpportunityState.PLANNED
    assert world.runtime().get_run(Reference("execution")) is None


def test_unavailable_source_never_invents_freshness(world: World) -> None:
    with patch.object(
        FakeSource,
        "refresh",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "source", "Unavailable"),
    ):
        outcome = world.use_case().execute(world.request)
    assert outcome.reason == WorkerExecutionReason.SOURCE_UNAVAILABLE
    assert world.current().state == OpportunityState.PLANNED


def test_stale_requested_revision_blocks(world: World) -> None:
    request = replace(
        world.request, expected_opportunity_revision=world.request.expected_opportunity_revision + 1
    )
    assert world.use_case().execute(request).reason == WorkerExecutionReason.STALE_REVISION


def test_budget_and_spending_approval_denial_never_dispatch(world: World) -> None:
    manager = world.budget()
    snapshot = manager.ledger.get(Reference("ledger"))
    assert snapshot is not None
    context = CostContext(
        Reference("operation"),
        OperationType.TASK_EXECUTION,
        world.clock.now(),
        Reference("task"),
        Reference("op"),
    )
    request = snapshot.value.authorize(usd("0"), CostCategory.AI, context).request
    for status, reason, expected in (
        (AuthorizationStatus.DENIED, BudgetReason.SCOUT_ONLY, WorkerExecutionReason.BUDGET_DENIED),
        (
            AuthorizationStatus.REQUIRES_HUMAN_APPROVAL,
            BudgetReason.HUMAN_APPROVAL,
            WorkerExecutionReason.SPENDING_APPROVAL_REQUIRED,
        ),
    ):
        denied = AuthorizationDecision(
            request,
            status,
            reason,
            snapshot.value.operating_mode(world.clock.now()),
            snapshot.value,
        )
        with (
            patch.object(BudgetManager, "authorize", return_value=denied),
            patch.object(DataWorker, "execute", side_effect=AssertionError("no dispatch")),
        ):
            outcome = world.use_case().execute(world.request)
        assert outcome.reason == expected
    assert world.current().state == OpportunityState.PLANNED


def test_operator_approval_identity_cannot_be_changed(world: World) -> None:
    command = replace(world.use_case(), operator=Reference("other"))
    assert command.execute(world.request).reason == WorkerExecutionReason.APPROVAL_DENIED


def test_conflicting_execution_id_does_not_create_rework(world: World) -> None:
    world.use_case().execute(world.request)
    changed = replace(
        world.request,
        binding=replace(world.request.binding, execution_reference=Reference("another")),
    )
    assert world.use_case().execute(changed).status == WorkerExecutionStatus.BLOCKED
    assert world.runtime().get_run(Reference("another")) is None


def test_worker_failure_can_replay_only_same_frozen_plan(world: World) -> None:
    with patch.object(
        DataWorker, "execute", side_effect=RuntimeError("sensitive exception must not escape")
    ):
        failed = world.use_case().execute(world.request)
    assert failed.status == WorkerExecutionStatus.RECOVERABLE
    assert failed.reason == WorkerExecutionReason.WORKER_FAILED
    assert world.current().state == OpportunityState.IN_PROGRESS
    world.database = SQLiteDatabase(world.database.path)
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED


def test_crash_after_start_preserves_ids_and_revalidates(world: World) -> None:
    original = SQLiteWorkerRuntimeRepository.start

    def crash(repository: SQLiteWorkerRuntimeRepository, command: WorkerRunStart) -> bool:
        original(repository, command)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "start", "Acknowledgement lost")

    with (
        patch.object(SQLiteWorkerRuntimeRepository, "start", crash),
        patch.object(
            DataWorker, "execute", side_effect=AssertionError("no work after unknown commit")
        ),
    ):
        assert world.use_case().execute(world.request).status == WorkerExecutionStatus.RECOVERABLE
    assert world.current().state == OpportunityState.IN_PROGRESS
    world.source.requirements = "Changed while stopped"
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.BLOCKED
    world.source.requirements = world.specification.source_context.requirements
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED
    execution = world.current().execution
    assert execution is not None and execution.reference == Reference("execution")


def test_crash_after_result_recovers_without_recomputation(world: World) -> None:
    with patch.object(
        SQLiteWorkerRuntimeRepository,
        "finish",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "finish", "Unavailable"),
    ):
        outcome = world.use_case().execute(world.request)
    assert outcome.status == WorkerExecutionStatus.RECOVERABLE
    view = world.runtime().inspect(Reference("execution"))
    assert view is not None and view.result is not None and not view.finished
    world.database = SQLiteDatabase(world.database.path)
    with (
        patch.object(
            DataWorker, "execute", side_effect=AssertionError("never recompute retained result")
        ),
        patch.object(FakeSource, "refresh", side_effect=AssertionError("completion only")),
    ):
        assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED


def test_revision_changes_during_worker_prevent_finish(world: World) -> None:
    original = DataWorker.execute

    def work(worker: DataWorker, plan: DataPlan) -> DataResult:
        result = original(worker, plan)
        repo = SQLiteOpportunityRepository(world.database)
        old = repo.get(Reference("op"))
        assert old is not None
        repo.save(OpportunitySave(old.value, old.revision))
        return result

    with patch.object(DataWorker, "execute", work):
        outcome = world.use_case().execute(world.request)
    assert outcome.status == WorkerExecutionStatus.RECOVERABLE
    assert world.current().state == OpportunityState.IN_PROGRESS
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED


def change_specification(world: World, specification: WorkSpecification) -> None:
    world.runtime().save_specification(specification)
    world.specification = specification
    world.request = replace(
        world.request,
        binding=replace(world.request.binding, specification_reference=specification.reference),
    )


def test_legacy_b1_spec_missing_evidence_stays_readable_but_blocked(world: World) -> None:
    import json

    codec = world.database.codec
    payload = json.loads(codec.dumps(replace(world.specification, execution_evidence=None)))
    del payload["value"]["fields"]["execution_evidence"]
    loaded = codec.loads(json.dumps(payload), WorkSpecification)
    assert loaded.execution_evidence is None
    change_specification(world, replace(loaded, reference=Reference("legacy")))
    assert world.use_case().execute(world.request).reason == WorkerExecutionReason.EVIDENCE_INVALID


def test_tampered_snapshot_digest_is_rejected_even_from_bad_port(world: World) -> None:
    # Simulate a contract-violating port, not a supported way to mutate approval.
    source = replace(world.specification.sources[0])
    object.__setattr__(source, "content", '[{"name":"Tampered"}]')
    spec = replace(world.specification)
    object.__setattr__(spec, "sources", (source,))
    with patch.object(SQLiteWorkerRuntimeRepository, "get_specification", return_value=spec):
        outcome = world.use_case().execute(world.request)
    assert outcome.reason == WorkerExecutionReason.EVIDENCE_INVALID
    assert world.current().state == OpportunityState.PLANNED


@pytest.mark.parametrize("changed", ["ai_policy", "unknown_facts", "time_remaining"])
def test_eligibility_is_recomputed_not_a_historical_boolean(world: World, changed: str) -> None:
    evidence = world.specification.execution_evidence
    assert evidence is not None
    if changed == "time_remaining":
        world.clock.instant += timedelta(days=2, minutes=-30)
    else:
        facts = evidence.eligibility_request.facts
        facts = (
            replace(facts, ai_policy=AIParticipationPolicy.PROHIBITED)
            if changed == "ai_policy"
            else replace(facts, geography=None)
        )
        updated = replace(
            evidence, eligibility_request=replace(evidence.eligibility_request, facts=facts)
        )
        change_specification(
            world,
            replace(
                world.specification, reference=Reference("changed-spec"), execution_evidence=updated
            ),
        )
    assert (
        world.use_case().execute(world.request).reason == WorkerExecutionReason.ELIGIBILITY_BLOCKED
    )
    assert world.current().state == OpportunityState.PLANNED


def test_missing_evaluation_cannot_be_replaced_by_an_asserted_score(world: World) -> None:
    with patch.object(SQLiteEvaluationRepository, "get", return_value=None):
        assert (
            world.use_case().execute(world.request).reason == WorkerExecutionReason.EVIDENCE_INVALID
        )


def test_economic_assessment_must_match_authoritative_aggregate(world: World) -> None:
    evidence = world.specification.execution_evidence
    assert evidence is not None
    # An internally valid but different evaluation is insufficient even if the port returns it.
    assessment = evidence.evaluation.scoring_assessment
    new_economic = replace(
        assessment.economics,
        inputs=replace(
            assessment.economics.inputs,
            predicted_success_probability=replace(
                assessment.economics.inputs.predicted_success_probability, value=Decimal("0.2")
            ),
        ),
    )
    new_scoring = replace(assessment, economics=new_economic)
    evaluation = replace(
        evidence.evaluation,
        scoring_assessment=new_scoring,
        score=new_scoring.score,
        expected_value=new_economic.expected_net_value,
    )
    spec = replace(
        world.specification,
        reference=Reference("new-spec"),
        execution_evidence=replace(evidence, evaluation=evaluation),
    )
    change_specification(world, spec)
    with patch.object(SQLiteEvaluationRepository, "get", return_value=evaluation):
        assert (
            world.use_case().execute(world.request).reason == WorkerExecutionReason.EVIDENCE_INVALID
        )


def test_source_refresh_revision_race_blocks_before_authorization(world: World) -> None:
    original = FakeSource.refresh

    def refresh(source: FakeSource, request: RefreshOpportunityRequest) -> object:
        status = original(source, request)
        repository = SQLiteOpportunityRepository(world.database)
        old = repository.get(Reference("op"))
        assert old is not None
        repository.save(OpportunitySave(old.value, old.revision))
        return status

    with (
        patch.object(FakeSource, "refresh", refresh),
        patch.object(
            BudgetManager,
            "authorize",
            side_effect=AssertionError("no authorize after stale preflight"),
        ),
    ):
        assert (
            world.use_case().execute(world.request).reason == WorkerExecutionReason.STALE_REVISION
        )


def test_current_ledger_revision_race_at_atomic_start_does_not_dispatch(world: World) -> None:
    original = SQLiteWorkerRuntimeRepository.start

    def start(repository: SQLiteWorkerRuntimeRepository, command: WorkerRunStart) -> bool:
        ledger = SQLiteCostLedgerRepository(world.database)
        current = ledger.get(Reference("ledger"))
        assert current is not None
        ledger.commit(BudgetCommit(Reference("ledger"), current.value, current.revision, None))
        return original(repository, command)

    with (
        patch.object(SQLiteWorkerRuntimeRepository, "start", start),
        patch.object(
            DataWorker, "execute", side_effect=AssertionError("no dispatch after conflict")
        ),
    ):
        outcome = world.use_case().execute(world.request)
    assert outcome.status == WorkerExecutionStatus.RECOVERABLE
    assert world.current().state == OpportunityState.PLANNED
    ledger = SQLiteCostLedgerRepository(world.database).get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.outstanding) == 1


def authorize_start(world: World, *, start: bool = True) -> WorkerRunStart:
    context = CostContext(
        Reference("operation"),
        OperationType.TASK_EXECUTION,
        world.clock.now(),
        Reference("task"),
        Reference("op"),
    )
    world.budget().authorize(usd("0"), context)
    previous = SQLiteOpportunityRepository(world.database).get(Reference("op"))
    ledger = SQLiteCostLedgerRepository(world.database).get(Reference("ledger"))
    assert previous is not None and ledger is not None
    command = WorkerRunStart(
        world.specification, world.request.binding, previous, ledger, world.clock.now()
    )
    if start:
        world.runtime().start(command)
    return command


@pytest.mark.parametrize("started", [False, True])
def test_unknown_ai_claim_is_never_retried_as_deterministic(world: World, started: bool) -> None:
    command = authorize_start(world, start=started)
    SQLiteDataJournal(world.database).claim_ai(command.run.plan)
    with patch.object(
        DataWorker, "execute", side_effect=AssertionError("unknown AI outcome must block")
    ):
        outcome = world.use_case().execute(world.request)
    assert outcome.status == WorkerExecutionStatus.BLOCKED
    assert outcome.reason == WorkerExecutionReason.EXTERNAL_OUTCOME_UNKNOWN


def test_crash_after_worker_journal_before_ledger_is_repaired_from_real_result(
    world: World,
) -> None:
    with patch.object(
        BudgetManager,
        "record",
        side_effect=PortError(PortErrorCode.UNAVAILABLE, "record", "DB failure"),
    ):
        assert world.use_case().execute(world.request).status == WorkerExecutionStatus.RECOVERABLE
    ledger = SQLiteCostLedgerRepository(world.database).get(Reference("ledger"))
    assert ledger is not None and not ledger.value.records and len(ledger.value.outstanding) == 1
    with patch.object(DataWorker, "execute", side_effect=AssertionError("use existing result")):
        assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED
    ledger = SQLiteCostLedgerRepository(world.database).get(Reference("ledger"))
    assert ledger is not None and len(ledger.value.records) == 1 and not ledger.value.outstanding


def test_new_data_result_and_original_ids_survive_reopened_recovery(world: World) -> None:
    authorize_start(world)
    world.clock.instant += timedelta(minutes=1)
    world.database = SQLiteDatabase(world.database.path)
    outcome = world.use_case().execute(world.request)
    assert outcome.status == WorkerExecutionStatus.COMPLETED
    current = world.current()
    assert current.execution is not None and current.deliverable is not None
    assert current.execution.reference == world.request.binding.execution_reference
    assert (
        current.execution.authorization.request.context.operation_reference
        == world.request.binding.operation_reference
    )
    assert (
        current.deliverable.reference == world.request.binding.deliverable_reference
        and current.deliverable.version == 1
    )


def test_recovery_without_result_requires_current_source(world: World) -> None:
    authorize_start(world)
    with (
        patch.object(
            FakeSource,
            "refresh",
            side_effect=PortError(PortErrorCode.UNAVAILABLE, "source", "No source"),
        ),
        patch.object(DataWorker, "execute", side_effect=AssertionError("no work")),
    ):
        assert (
            world.use_case().execute(world.request).reason
            == WorkerExecutionReason.SOURCE_UNAVAILABLE
        )


def test_manual_eligibility_reuses_only_matching_recorded_f04_resolution(tmp_path: Path) -> None:
    world = build_world(tmp_path, manual=True)
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED
    assert world.current().approval is None and world.current().submission is None


def test_manual_without_review_record_is_not_eligible_permission(tmp_path: Path) -> None:
    world = build_world(tmp_path, manual=True)
    evidence = world.specification.execution_evidence
    assert evidence is not None
    change_specification(
        world,
        replace(
            world.specification,
            reference=Reference("without-review"),
            execution_evidence=replace(evidence, eligibility_review_reference=None),
        ),
    )
    assert (
        world.use_case().execute(world.request).reason == WorkerExecutionReason.ELIGIBILITY_BLOCKED
    )


def test_no_submission_gateway_is_ever_instantiated_or_invoked(world: World) -> None:
    from agentmine.application.use_cases.settlement import SubmitTask

    with patch.object(SubmitTask, "execute", side_effect=AssertionError("submission forbidden")):
        assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED


def test_validation_failure_is_a_real_artifact_not_an_automatic_qa_pass(world: World) -> None:
    source = replace(world.specification.sources[0], content='[{"wrong":"missing name"}]')
    spec = replace(
        world.specification,
        reference=Reference("invalid-input-spec"),
        sources=(source,),
        input_evidence=(InputEvidence(source.reference, Reference("sha256:" + source.digest)),),
    )
    change_specification(world, spec)
    outcome = world.use_case().execute(world.request)
    assert outcome.status == WorkerExecutionStatus.COMPLETED
    assert outcome.result is not None and not outcome.result.valid
    assert [artifact.name for artifact in outcome.result.artifacts] == ["validation.json"]
    assert world.current().state == OpportunityState.QA_PENDING and world.current().qa is None


def test_existing_costs_and_unknown_commitments_are_preserved(world: World) -> None:
    manager = world.budget()
    prior = manager.authorize(
        usd("1"), CostContext(Reference("prior-cost"), OperationType.SCORING, world.clock.now())
    )
    assert prior.authorization is not None
    manager.record(prior.authorization, usd("0.75"), world.clock.now())
    unknown = manager.authorize(
        usd("0.5"), CostContext(Reference("unknown-cost"), OperationType.SCORING, world.clock.now())
    )
    assert unknown.authorization is not None
    before = manager.ledger.get(Reference("ledger"))
    assert before is not None
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED
    after = manager.ledger.get(Reference("ledger"))
    assert after is not None
    assert after.value.outstanding == before.value.outstanding
    assert after.value.records[0] == before.value.records[0]
    assert len(after.value.records) == 2 and after.value.ai_spent(world.clock.now()) == usd("0.75")


def test_exhausted_scout_budget_does_not_block_zero_cost_worker(world: World) -> None:
    repository = SQLiteCostLedgerRepository(world.database)
    old = repository.get(Reference("ledger"))
    assert old is not None
    policy = replace(old.value.policy, monthly_ai_budget=usd("0"), daily_ai_budget=usd("0"))
    repository.commit(
        BudgetCommit(Reference("ledger"), old.value.with_policy(policy), old.revision, None)
    )
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED
    current = world.current()
    assert current.execution is not None and current.execution.mode.value == "scout_only"


def test_start_is_durable_before_real_worker_is_called(world: World) -> None:
    original = DataWorker.execute

    def worker(worker: DataWorker, plan: DataPlan) -> DataResult:
        assert worker.llm is None
        assert world.current().state == OpportunityState.IN_PROGRESS
        retained = world.runtime().get_run(plan.execution.reference)
        assert retained is not None and retained.plan == plan
        ledger = world.budget().ledger.get(Reference("ledger"))
        assert ledger is not None and plan.execution.authorization in ledger.value.outstanding
        return original(worker, plan)

    with patch.object(DataWorker, "execute", worker):
        assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED


@pytest.mark.parametrize(
    "field", ["operation_reference", "deliverable_reference", "specification_reference"]
)
def test_recovery_cannot_change_original_identity(world: World, field: str) -> None:
    authorize_start(world)
    binding = replace(world.request.binding, **{field: Reference("different")})
    outcome = world.use_case().execute(replace(world.request, binding=binding))
    assert outcome.status == WorkerExecutionStatus.BLOCKED
    assert world.current().state == OpportunityState.IN_PROGRESS


def test_no_replay_after_deadline_when_result_is_missing(world: World) -> None:
    authorize_start(world)
    world.clock.instant += timedelta(days=3)
    with patch.object(
        DataWorker, "execute", side_effect=AssertionError("expired task cannot execute")
    ):
        assert (
            world.use_case().execute(world.request).reason
            == WorkerExecutionReason.ELIGIBILITY_BLOCKED
        )


def test_finished_retry_does_not_rewind_later_qa_state(world: World) -> None:
    from agentmine.domain.work import QAResult, QAStatus

    world.use_case().execute(world.request)
    repository = SQLiteOpportunityRepository(world.database)
    before = repository.get(Reference("op"))
    assert before is not None and before.value.deliverable is not None
    qa = before.value.review_qa(
        QAResult(before.value.deliverable, QAStatus.PASSED, "Test-only QA assertion")
    )
    saved = repository.save(OpportunitySave(qa, before.revision))
    assert world.use_case().execute(world.request).status == WorkerExecutionStatus.COMPLETED
    assert repository.get(Reference("op")) == saved
