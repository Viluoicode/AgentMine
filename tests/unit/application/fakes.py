"""Test-only, instance-local port implementations; no external I/O."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from agentmine.application.contracts.ai import (
    AIResponse,
    DeliverableDraft,
    EvaluationAdvice,
    EvaluationRequest,
    QAAdvice,
    QARequest,
    ReferencedText,
    WorkRequest,
)
from agentmine.application.contracts.eligibility import EligibilityCheckRequest
from agentmine.application.contracts.opportunities import (
    DiscoveryRequest,
    OpportunityBatch,
    OpportunityObservation,
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.contracts.records import (
    BudgetCommit,
    EvaluationRecord,
    OpportunitySave,
    Versioned,
)
from agentmine.application.contracts.submission import (
    OutcomeObservation,
    PaymentStatus,
    PaymentVerificationRequest,
    PaymentVerificationResult,
    SubmissionAttemptStatus,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.contracts.workflow import ExecuteTaskRequest
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.budget import Budget
from agentmine.domain.economics import EconomicInputs, EstimatedCosts, SignalEstimate
from agentmine.domain.eligibility import (
    AIParticipationPolicy,
    EligibilityFacts,
    GeographicRestrictions,
    ParticipantProfile,
    PaymentRequirements,
    Requirement,
    SubmissionSupport,
)
from agentmine.domain.finance import Cost, CostCategory, Reward, RewardStage
from agentmine.domain.money import Money
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.scoring import ScoringPolicy, ScoringSignals
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference
from agentmine.domain.work import (
    Deliverable,
    Execution,
    Outcome,
    OutcomeStatus,
    QAResult,
    Submission,
    TaskType,
)


def eligibility_request(reference: Reference) -> EligibilityCheckRequest:
    return EligibilityCheckRequest(
        EligibilityFacts(
            reference,
            ai_policy=AIParticipationPolicy.ALLOWED,
            geography=GeographicRestrictions(),
            account=Requirement.NOT_REQUIRED,
            identity=Requirement.NOT_REQUIRED,
            physical_presence=Requirement.NOT_REQUIRED,
            task_type=TaskType.RESEARCH,
            required_skills=frozenset(),
            submission=SubmissionSupport.AUTOMATIC,
            payment=PaymentRequirements(False, False),
            prohibited_actions=frozenset(),
        ),
        ParticipantProfile(),
    )


def put[K, V](store: dict[K, V], key: K, value: V) -> None:
    if key in store and store[key] != value:
        raise PortError(PortErrorCode.CONFLICT, "save", "Immutable identity conflict")
    store[key] = value


@dataclass
class FakeClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


@dataclass
class FakeSource:
    clock: FakeClock
    observations: tuple[OpportunityObservation, ...]
    is_open: bool | None = True
    deadline: datetime | None = None
    deadline_known: bool = True
    refreshes: int = 0

    def discover(self, request: DiscoveryRequest) -> OpportunityBatch:
        return OpportunityBatch(self.observations[: request.limit])

    def refresh(self, request: RefreshOpportunityRequest) -> OpportunityStatus:
        self.refreshes += 1
        return OpportunityStatus(
            request.opportunity_reference,
            request.source_reference,
            self.clock.now(),
            self.is_open,
            self.deadline,
            self.deadline_known,
        )


@dataclass
class FakeOpportunities:
    snapshots: dict[Reference, Versioned[Opportunity]] = field(default_factory=dict)
    observations: dict[Reference, OpportunityObservation] = field(default_factory=dict)
    fail_save: bool = False

    def get(self, reference: Reference) -> Versioned[Opportunity] | None:
        return self.snapshots.get(reference)

    def save(self, request: OpportunitySave) -> Versioned[Opportunity]:
        old = self.get(request.opportunity.reference)
        revision = old.revision if old else None
        if self.fail_save or request.expected_revision != revision:
            raise PortError(PortErrorCode.CONFLICT, "save", "Stale opportunity revision")
        updated = Versioned(request.opportunity, (revision or 0) + 1)
        self.snapshots[request.opportunity.reference] = updated
        return updated

    def save_observation(self, observation: OpportunityObservation) -> None:
        put(self.observations, observation.opportunity.reference, observation)

    def get_observation(self, reference: Reference) -> OpportunityObservation | None:
        return self.observations.get(reference)


@dataclass
class FakeEvaluations:
    records: dict[Reference, EvaluationRecord] = field(default_factory=dict)

    def save(self, evaluation: EvaluationRecord) -> None:
        put(self.records, evaluation.reference, evaluation)

    def get(self, reference: Reference) -> EvaluationRecord | None:
        return self.records.get(reference)

    def for_opportunity(self, reference: Reference) -> tuple[EvaluationRecord, ...]:
        return tuple(
            sorted(
                (item for item in self.records.values() if item.opportunity_reference == reference),
                key=lambda item: item.evaluated_at,
            )
        )


@dataclass
class FakeExecutions:
    executions: dict[Reference, Execution] = field(default_factory=dict)
    deliverables: dict[tuple[Reference, int], Deliverable] = field(default_factory=dict)
    qa: dict[tuple[Reference, int], QAResult] = field(default_factory=dict)
    contents: dict[Reference, ReferencedText] = field(default_factory=dict)
    requests: dict[Reference, ExecuteTaskRequest] = field(default_factory=dict)
    responses: dict[Reference, AIResponse[DeliverableDraft]] = field(default_factory=dict)

    def save(self, execution: Execution) -> None:
        put(self.executions, execution.reference, execution)

    def get(self, reference: Reference) -> Execution | None:
        return self.executions.get(reference)

    def save_deliverable(self, deliverable: Deliverable) -> None:
        put(self.deliverables, (deliverable.reference, deliverable.version), deliverable)

    def get_deliverable(self, reference: Reference, version: int) -> Deliverable | None:
        return self.deliverables.get((reference, version))

    def save_qa(self, result: QAResult) -> None:
        put(self.qa, (result.deliverable.reference, result.deliverable.version), result)

    def get_qa(self, deliverable_reference: Reference, version: int) -> QAResult | None:
        return self.qa.get((deliverable_reference, version))

    def save_content(self, content: ReferencedText) -> None:
        put(self.contents, content.reference, content)

    def get_content(self, reference: Reference) -> ReferencedText | None:
        return self.contents.get(reference)

    def save_work_request(self, request: ExecuteTaskRequest) -> None:
        put(self.requests, request.execution_reference, request)

    def get_work_request(self, execution_reference: Reference) -> ExecuteTaskRequest | None:
        return self.requests.get(execution_reference)

    def save_work_response(
        self, execution_reference: Reference, response: AIResponse[DeliverableDraft]
    ) -> None:
        put(self.responses, execution_reference, response)

    def get_work_response(
        self, execution_reference: Reference
    ) -> AIResponse[DeliverableDraft] | None:
        return self.responses.get(execution_reference)


@dataclass
class FakeLedger:
    snapshots: dict[Reference, Versioned[Budget]]
    audits: list[BudgetCommit] = field(default_factory=list)
    fail_commit: bool = False

    def get(self, ledger_reference: Reference) -> Versioned[Budget] | None:
        return self.snapshots.get(ledger_reference)

    def commit(self, request: BudgetCommit) -> Versioned[Budget]:
        old = self.get(request.ledger_reference)
        revision = old.revision if old else None
        if self.fail_commit or request.expected_revision != revision:
            raise PortError(PortErrorCode.CONFLICT, "commit", "Stale budget revision")
        result = Versioned(request.budget, (revision or 0) + 1)
        self.snapshots[request.ledger_reference] = result
        self.audits.append(request)
        return result


@dataclass
class FakeProvider:
    calls: list[WorkRequest] = field(default_factory=list)
    actual_cost: Money | None = None
    fail: bool = False
    on_response: Callable[[], None] | None = None

    def evaluate_opportunity(self, request: EvaluationRequest) -> AIResponse[EvaluationAdvice]:
        raise AssertionError("Evaluation is deterministic in Milestone 2B")

    def review_deliverable(self, request: QARequest) -> AIResponse[QAAdvice]:
        raise AssertionError("QA is supplied explicitly in Milestone 2B")

    def perform_work(self, request: WorkRequest) -> AIResponse[DeliverableDraft]:
        self.calls.append(request)
        if self.fail:
            raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "work", "Simulated timeout")
        if self.on_response is not None:
            self.on_response()
        spending = request.execution.authorization.request
        measured = (
            None
            if self.actual_cost is None
            else CostRecord(
                Cost(spending.context.operation_reference, self.actual_cost, CostCategory.AI),
                spending.context,
                spending.estimated_cost,
            )
        )
        return AIResponse(
            spending.context.operation_reference,
            DeliverableDraft("Fake research/data report", (Reference("source-evidence"),)),
            measured,
            Reference("provider-evidence"),
        )


@dataclass
class FakeSubmissions:
    requests: dict[Reference, SubmissionRequest] = field(default_factory=dict)
    attempts: list[SubmissionResult] = field(default_factory=list)
    submissions: dict[Reference, Submission] = field(default_factory=dict)
    outcomes: dict[Reference, Outcome] = field(default_factory=dict)

    def save_request(self, request: SubmissionRequest) -> None:
        put(self.requests, request.reference, request)

    def claim_request(self, request: SubmissionRequest) -> bool:
        created = request.reference not in self.requests
        self.save_request(request)
        return created

    def get_request(self, reference: Reference) -> SubmissionRequest | None:
        return self.requests.get(reference)

    def record_attempt(self, result: SubmissionResult) -> None:
        if result not in self.attempts:
            self.attempts.append(result)

    def attempts_for(self, reference: Reference) -> tuple[SubmissionResult, ...]:
        return tuple(item for item in self.attempts if item.reference == reference)

    def save(self, submission: Submission) -> None:
        put(self.submissions, submission.reference, submission)

    def get(self, reference: Reference) -> Submission | None:
        return self.submissions.get(reference)

    def save_outcome(self, outcome: Outcome) -> None:
        put(self.outcomes, outcome.submission_reference, outcome)

    def get_outcome(self, submission_reference: Reference) -> Outcome | None:
        return self.outcomes.get(submission_reference)


@dataclass
class FakeGateway:
    clock: FakeClock
    status: SubmissionAttemptStatus = SubmissionAttemptStatus.CONFIRMED
    outcome_status: OutcomeStatus | None = OutcomeStatus.ACCEPTED
    submits: int = 0
    reconciles: int = 0

    def _result(self, request: SubmissionRequest) -> SubmissionResult:
        receipt = None
        if self.status == SubmissionAttemptStatus.CONFIRMED:
            receipt = Submission(
                request.reference,
                request.deliverable,
                request.qa,
                request.approval,
                request.target,
                Reference("receipt"),
                self.clock.now(),
            )
        return SubmissionResult(
            request.reference, self.status, self.clock.now(), receipt, "Fake observation"
        )

    def submit(self, request: SubmissionRequest) -> SubmissionResult:
        self.submits += 1
        return self._result(request)

    def reconcile(self, request: SubmissionRequest) -> SubmissionResult:
        self.reconciles += 1
        return self._result(request)

    def track_outcome(self, submission: Submission) -> OutcomeObservation:
        outcome = (
            None
            if self.outcome_status is None
            else Outcome(submission.reference, self.outcome_status, Reference("outcome-evidence"))
        )
        return OutcomeObservation(submission.reference, self.clock.now(), outcome)


@dataclass
class FakeVerifier:
    clock: FakeClock
    amount: Money
    status: PaymentStatus = PaymentStatus.PENDING
    calls: int = 0

    def verify_payment(self, request: PaymentVerificationRequest) -> PaymentVerificationResult:
        self.calls += 1
        payment = (
            None
            if self.status != PaymentStatus.VERIFIED
            else Reward(
                self.amount,
                RewardStage.VERIFIED_PAYMENT,
                Reference("payment-evidence"),
                request.submission.reference,
            )
        )
        return PaymentVerificationResult(
            request.submission.reference,
            self.status,
            self.clock.now(),
            payment,
            "Fake verification",
        )


def economic_inputs() -> EconomicInputs:
    return EconomicInputs(
        SignalEstimate(Decimal("0.8"), "Subjective success forecast"),
        EstimatedCosts(*(Money(Decimal(5), "USD") for _ in range(4))),
        "Four estimated costs; not provider billing",
    )


def scoring_signals() -> ScoringSignals:
    favorable = SignalEstimate(Decimal(1), "Test scenario: favorable")
    low = SignalEstimate(Decimal(0), "Test scenario: low risk/competition")
    return ScoringSignals(low, low, favorable, favorable, favorable)


def scoring_policy() -> ScoringPolicy:
    return ScoringPolicy("v1", Money(Decimal(100), "USD"), "Explicit test value target")
