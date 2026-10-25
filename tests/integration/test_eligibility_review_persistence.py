"""Real review persistence/CAS and safe human resolution with offline source evidence."""

import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest
from fakes import FakeSource
from test_dynamodb_persistence import dynamo
from test_eligibility_use_case import Case, case

from agentmine.application.contracts.eligibility import (
    EligibilityCheckRequest,
    EligibilityReview,
    EligibilityReviewCommit,
)
from agentmine.application.contracts.opportunities import (
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.contracts.records import OpportunitySave
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.eligibility_review import (
    GetEligibilityReview,
    PrepareEligibilityReview,
    ResolveEligibilityReview,
)
from agentmine.bootstrap.dynamodb import DynamoDBRepositories, dynamodb_repositories
from agentmine.bootstrap.local import LocalRepositories, open_local_repositories
from agentmine.domain.eligibility import (
    AIParticipationPolicy,
    EligibilityPolicy,
    PaymentRequirements,
    ProhibitedAction,
    Requirement,
    SubmissionSupport,
)
from agentmine.domain.eligibility_review import (
    EligibilityChoice,
    EligibilityResolution,
    ManualEligibilityEvidence,
)
from agentmine.domain.errors import DomainError
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.domain.work import EligibilityReason, EligibilityStatus
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase

__all__ = ["case", "dynamo"]

type Stores = LocalRepositories | DynamoDBRepositories


def evidence() -> ManualEligibilityEvidence:
    return ManualEligibilityEvidence(
        Reference("manual:target"),
        Reference("capture:instructions"),
        Reference("operator:account-access"),
        Reference("capture:requirements-checklist"),
        True,
    )


@dataclass
class ReviewCase:
    case: Case
    stores: Stores
    reopen: Callable[[], Stores]
    request: EligibilityCheckRequest
    policy: EligibilityPolicy

    def prepare(self, name: str = "eligibility-review") -> EligibilityReview:
        return PrepareEligibilityReview(
            self.stores.opportunities,
            self.stores.eligibility_reviews,
            self.case.source,
            self.case.clock,
        ).execute(Reference(name), self.request, self.policy)

    def decide(
        self, choice: EligibilityChoice = EligibilityChoice.APPROVE
    ) -> EligibilityResolution:
        return ResolveEligibilityReview(
            self.stores.opportunities,
            self.stores.eligibility_reviews,
            self.case.source,
            self.case.clock,
            Reference("alice"),
        ).execute(
            Reference("eligibility-review"),
            choice,
            "Checked documented channel requirements",
            evidence() if choice == EligibilityChoice.APPROVE else None,
        )

    def current(self) -> Opportunity:
        snapshot = self.stores.opportunities.get(self.request.facts.opportunity_reference)
        assert snapshot is not None
        return snapshot.value


@pytest.fixture(params=["sqlite", "dynamodb"])
def review_case(case: Case, tmp_path: Path, request: pytest.FixtureRequest) -> ReviewCase:
    stores: Stores
    if request.param == "sqlite":
        path = tmp_path / "eligibility.sqlite"
        stores = open_local_repositories(path)

        def reopen() -> Stores:
            return open_local_repositories(path)
    else:
        stores = request.getfixturevalue("dynamo")
        assert isinstance(stores, DynamoDBRepositories)
        database = stores.opportunities.database

        def reopen() -> Stores:
            return dynamodb_repositories(database.client, database.table)

    ref = case.request.facts.opportunity_reference
    snapshot = case.repository.get(ref)
    observation = case.repository.get_observation(ref)
    assert snapshot is not None and observation is not None
    stores.opportunities.save(OpportunitySave(snapshot.value, None))
    stores.opportunities.save_observation(observation)
    case.source.terms_reference = Reference("source:version-1")
    case.source.requirements = "Submit the verified report through the documented manual channel"
    return ReviewCase(
        case,
        stores,
        reopen,
        replace(
            case.request, facts=replace(case.request.facts, submission=SubmissionSupport.MANUAL)
        ),
        case.checker.engine.policy,
    )


def test_manual_resolution_is_audited_and_not_submission_approval(review_case: ReviewCase) -> None:
    review = review_case.prepare()
    assert review.inspection.result.reasons == (EligibilityReason.MANUAL_SUBMISSION_REQUIRED,)
    assert review_case.current().state == OpportunityState.ELIGIBILITY_CHECK
    decision = review_case.decide()
    op = review_case.current()
    assert op.state == OpportunityState.ELIGIBLE
    assert op.eligibility is not None and op.eligibility.status == EligibilityStatus.ELIGIBLE
    assert EligibilityReason.HUMAN_ELIGIBILITY_APPROVED in op.eligibility.reasons
    assert op.approval is None and op.submission is None and op.task is None
    assert decision.actor == Reference("alice") and decision.evidence == evidence()
    review_case.stores = review_case.reopen()
    stored = GetEligibilityReview(review_case.stores.eligibility_reviews).execute(review.reference)
    assert stored.review == review and stored.resolution == decision
    assert stored.review.inspection.request == review.inspection.request
    assert stored.review.inspection.source.terms_reference == Reference("source:version-1")
    assert review_case.decide() == decision


def test_operator_rejection_survives_reopen(review_case: ReviewCase) -> None:
    review_case.prepare()
    result = review_case.decide(EligibilityChoice.REJECT)
    review_case.stores = review_case.reopen()
    assert review_case.current().state == OpportunityState.INELIGIBLE
    assert review_case.stores.eligibility_reviews.get_resolution(result.review_reference) == result
    assert result.rationale and result.evidence is None


@pytest.mark.parametrize(
    "condition",
    [
        "ai-prohibited",
        "unsupported",
        "prohibited",
        "account",
        "secret",
        "unknown",
        "suspicious",
        "ai-review",
    ],
)
def test_human_cannot_override_other_conditions(review_case: ReviewCase, condition: str) -> None:
    facts = review_case.request.facts
    if condition == "ai-prohibited":
        facts = replace(facts, ai_policy=AIParticipationPolicy.PROHIBITED)
    elif condition == "unsupported":
        facts = replace(facts, task_type="coding")
    elif condition == "prohibited":
        facts = replace(facts, prohibited_actions=frozenset({ProhibitedAction.TRADING}))
    elif condition == "account":
        facts = replace(facts, account=Requirement.REQUIRED)
        review_case.request = replace(
            review_case.request,
            profile=replace(review_case.request.profile, account_requirement_met=False),
        )
    elif condition == "secret":
        facts = replace(facts, payment=PaymentRequirements(False, True))
    elif condition == "unknown":
        facts = replace(facts, geography=None)
    elif condition == "suspicious":
        facts = replace(facts, payment=PaymentRequirements(True, False))
    else:
        facts = replace(facts, ai_policy=AIParticipationPolicy.HUMAN_REVIEW_REQUIRED)
    review_case.request = replace(review_case.request, facts=facts)
    with pytest.raises((PortError, DomainError)):
        review_case.prepare()
        review_case.decide()
    assert review_case.current().state != OpportunityState.ELIGIBLE
    assert (
        review_case.stores.eligibility_reviews.get_resolution(Reference("eligibility-review"))
        is None
    )


@pytest.mark.parametrize(
    "changed", ["closed", "expired", "version", "requirements", "revision", "unknown-source"]
)
def test_stale_or_expired_review_cannot_grant_eligibility(
    review_case: ReviewCase, changed: str
) -> None:
    review_case.prepare()
    source = review_case.case.source
    if changed == "closed":
        source.is_open = False
    elif changed == "expired":
        review_case.case.clock.instant += timedelta(days=2)
    elif changed == "version":
        source.terms_reference = Reference("source:version-2")
    elif changed == "requirements":
        source.requirements = "New identity requirement"
    elif changed == "unknown-source":
        source.terms_reference = None
    else:
        snapshot = review_case.stores.opportunities.get(
            review_case.request.facts.opportunity_reference
        )
        assert snapshot is not None
        review_case.stores.opportunities.save(OpportunitySave(snapshot.value, snapshot.revision))
    with pytest.raises((PortError, DomainError)):
        review_case.decide()
    assert review_case.current().state == OpportunityState.ELIGIBILITY_CHECK
    assert (
        review_case.stores.eligibility_reviews.get_resolution(Reference("eligibility-review"))
        is None
    )


def test_changed_or_unauthorized_replay_conflicts(review_case: ReviewCase) -> None:
    review = review_case.prepare()
    original = review_case.decide()
    assert review_case.prepare() == review
    with pytest.raises(PortError):
        review_case.decide(EligibilityChoice.REJECT)
    with pytest.raises(PortError):
        ResolveEligibilityReview(
            review_case.stores.opportunities,
            review_case.stores.eligibility_reviews,
            review_case.case.source,
            review_case.case.clock,
            Reference("different-actor"),
        ).execute(review.reference, original.choice, original.rationale, original.evidence)
    assert review_case.stores.eligibility_reviews.get_resolution(review.reference) == original


@pytest.mark.parametrize("different_reviews", [False, True])
def test_contradictory_concurrent_decisions_have_one_winner(
    review_case: ReviewCase, different_reviews: bool
) -> None:
    review_case.prepare()
    second = review_case.prepare("second-review") if different_reviews else None
    barrier = Barrier(2)
    refresh = FakeSource.refresh

    def aligned(source: FakeSource, request: RefreshOpportunityRequest) -> OpportunityStatus:
        status = refresh(source, request)
        if not different_reviews:
            barrier.wait(timeout=10)
        return status

    def decide(choice: EligibilityChoice) -> EligibilityResolution | None:
        try:
            if second is not None and choice == EligibilityChoice.REJECT:
                return ResolveEligibilityReview(
                    review_case.stores.opportunities,
                    review_case.stores.eligibility_reviews,
                    review_case.case.source,
                    review_case.case.clock,
                    Reference("alice"),
                ).execute(second.reference, choice, "Reject based on reviewed requirements")
            return review_case.decide(choice)
        except PortError:
            return None

    with patch.object(FakeSource, "refresh", aligned), ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, (EligibilityChoice.APPROVE, EligibilityChoice.REJECT)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    review_case.stores = review_case.reopen()
    assert (
        review_case.stores.eligibility_reviews.get_resolution(winners[0].review_reference)
        == winners[0]
    )
    assert review_case.current().state == (
        OpportunityState.ELIGIBLE
        if winners[0].choice == EligibilityChoice.APPROVE
        else OpportunityState.INELIGIBLE
    )


@pytest.mark.parametrize("change", ["facts", "profile", "policy"])
def test_new_review_invalidates_previous_context(review_case: ReviewCase, change: str) -> None:
    original = review_case.prepare()
    if change == "facts":
        review_case.request = replace(
            review_case.request, facts=replace(review_case.request.facts, required_skills=None)
        )
    elif change == "profile":
        review_case.request = replace(
            review_case.request,
            profile=replace(review_case.request.profile, account_requirement_met=True),
        )
    else:
        review_case.policy = EligibilityPolicy(timedelta(hours=2))
    fresh = review_case.prepare("fresh-review")
    assert fresh.opportunity_snapshot.revision > original.opportunity_snapshot.revision
    with pytest.raises(PortError):
        review_case.decide()
    assert review_case.stores.eligibility_reviews.get_resolution(original.reference) is None


def test_failed_sqlite_resolution_rolls_back_both_writes(case: Case, tmp_path: Path) -> None:
    stores = open_local_repositories(tmp_path / "rollback.sqlite")
    ref = case.request.facts.opportunity_reference
    op, observation = case.repository.get(ref), case.repository.get_observation(ref)
    assert op is not None and observation is not None
    stores.opportunities.save(OpportunitySave(op.value, None))
    stores.opportunities.save_observation(observation)
    case.source.terms_reference = Reference("terms:version-1")
    case.source.requirements = "Manual report channel"
    request = replace(
        case.request, facts=replace(case.request.facts, submission=SubmissionSupport.MANUAL)
    )
    review = PrepareEligibilityReview(
        stores.opportunities, stores.eligibility_reviews, case.source, case.clock
    ).execute(Reference("review"), request, case.checker.engine.policy)
    write = SQLiteDatabase.write

    def failed(
        database: SQLiteDatabase,
        connection: sqlite3.Connection,
        kind: str,
        key: str,
        value: object,
        revision: int,
        indexes: IndexValues,
    ) -> None:
        if kind == "eligibility_resolution":
            raise PortError(PortErrorCode.UNAVAILABLE, "review", "Injected write failure")
        write(database, connection, kind, key, value, revision, indexes)

    with patch.object(SQLiteDatabase, "write", failed), pytest.raises(PortError):
        ResolveEligibilityReview(
            stores.opportunities,
            stores.eligibility_reviews,
            case.source,
            case.clock,
            Reference("alice"),
        ).execute(
            review.reference, EligibilityChoice.APPROVE, "Checked manual requirements", evidence()
        )
    assert stores.eligibility_reviews.get_resolution(review.reference) is None
    assert stores.opportunities.get(ref) == review.opportunity_snapshot


def test_concurrent_context_change_cannot_leave_partial_decision(review_case: ReviewCase) -> None:
    review_case.prepare()
    original = review_case.stores.eligibility_reviews.resolve

    def changed(_: object, commit: EligibilityReviewCommit) -> None:
        current = review_case.stores.opportunities.get(
            review_case.request.facts.opportunity_reference
        )
        assert current is not None
        review_case.stores.opportunities.save(OpportunitySave(current.value, current.revision))
        original(commit)

    with (
        patch.object(type(review_case.stores.eligibility_reviews), "resolve", changed),
        pytest.raises(PortError),
    ):
        review_case.decide()
    assert review_case.current().state == OpportunityState.ELIGIBILITY_CHECK
    assert (
        review_case.stores.eligibility_reviews.get_resolution(Reference("eligibility-review"))
        is None
    )
