"""Submission/cancellation ordering at real persistence boundaries; no external calls."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import pytest
from fakes import FakeGateway, FakeSource
from local_cases import RepositoryPorts
from test_dynamodb_persistence import dynamo
from test_resilience import ReceiptGateway, TimeoutAfterSend, seed
from test_use_cases import World, world

from agentmine.application.contracts.opportunities import (
    OpportunityStatus,
    RefreshOpportunityRequest,
)
from agentmine.application.contracts.records import OpportunitySave, Versioned
from agentmine.application.contracts.submission import (
    SubmissionAttemptStatus,
    SubmissionDispatch,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.use_cases.settlement import SubmitTask
from agentmine.bootstrap.dynamodb import DynamoDBRepositories, dynamodb_repositories
from agentmine.bootstrap.local import LocalRepositories, open_local_repositories
from agentmine.domain.errors import DomainError
from agentmine.domain.opportunity import Opportunity, OpportunityState
from agentmine.domain.values import Reference
from agentmine.infrastructure.dynamodb.store import Wire
from agentmine.infrastructure.sqlite.database import SQLiteDatabase

__all__ = ["world", "dynamo"]

type Durable = tuple[RepositoryPorts, Callable[[], RepositoryPorts]]


def ports(repos: LocalRepositories | DynamoDBRepositories) -> RepositoryPorts:
    return RepositoryPorts(
        repos.opportunities, repos.evaluations, repos.executions, repos.submissions, repos.ledger
    )


@pytest.fixture(params=["sqlite", "dynamodb"])
def durable(world: World, tmp_path: Path, request: pytest.FixtureRequest) -> Durable:
    path = tmp_path / "durable.sqlite"
    local = seed(world, path, approval=True)
    if request.param == "sqlite":
        return ports(local), lambda: ports(open_local_repositories(path))
    store = request.getfixturevalue("dynamo")
    assert isinstance(store, DynamoDBRepositories)
    store.opportunities.save(OpportunitySave(world.current(), None))
    observation = local.opportunities.get_observation(world.reference)
    assert observation is not None
    store.opportunities.save_observation(observation)
    deliverable = world.current().deliverable
    assert deliverable is not None
    content = local.executions.get_content(deliverable.content_reference)
    assert content is not None
    store.executions.save_content(content)
    database = store.opportunities.database
    return ports(store), lambda: ports(dynamodb_repositories(database.client, database.table))


def current(repos: RepositoryPorts, world: World) -> Versioned[Opportunity]:
    result = repos.opportunities.get(world.reference)
    assert result is not None
    return result


def dispatch_for(repos: RepositoryPorts, world: World) -> SubmissionDispatch:
    snapshot = current(repos, world)
    op = snapshot.value
    assert op.deliverable is not None and op.qa is not None and op.approval is not None
    content = repos.executions.get_content(op.deliverable.content_reference)
    assert content is not None
    return SubmissionDispatch(
        SubmissionRequest(
            Reference("send"), op.deliverable, op.qa, op.approval, op.approval.target, content
        ),
        snapshot,
    )


def command_for(repos: RepositoryPorts, world: World, gateway: FakeGateway) -> SubmitTask:
    return SubmitTask(
        repos.opportunities, repos.executions, repos.submissions, gateway, world.source, world.clock
    )


def test_cancel_during_refresh_prevents_claim_and_external_send(
    world: World, durable: Durable
) -> None:
    repos, _ = durable
    refresh = FakeSource.refresh

    def cancel(source: FakeSource, request: RefreshOpportunityRequest) -> OpportunityStatus:
        result = refresh(source, request)
        current = repos.opportunities.get(world.reference)
        assert current is not None
        repos.opportunities.save(
            OpportunitySave(current.value.skip("Cancelled before authorization"), current.revision)
        )
        return result

    command = SubmitTask(
        repos.opportunities,
        repos.executions,
        repos.submissions,
        world.gateway,
        world.source,
        world.clock,
    )
    with patch.object(FakeSource, "refresh", cancel), pytest.raises(PortError):
        command.execute(world.reference, Reference("send"))
    assert world.gateway.submits == world.gateway.reconciles == 0
    assert repos.submissions.get_request(Reference("send")) is None
    current = repos.opportunities.get(world.reference)
    assert current is not None and current.value.state == OpportunityState.SKIPPED


def test_claim_wins_cancellation_is_rejected_before_receipt_returns(
    world: World, durable: Durable
) -> None:
    repos, _ = durable
    submit = FakeGateway.submit

    def receipt(gateway: FakeGateway, request: SubmissionRequest) -> SubmissionResult:
        current = repos.opportunities.get(world.reference)
        assert current is not None
        assert current.value.state.value == "submission_in_flight"
        with pytest.raises(DomainError):
            current.value.skip("Too late to cancel")
        return submit(gateway, request)

    command = SubmitTask(
        repos.opportunities,
        repos.executions,
        repos.submissions,
        world.gateway,
        world.source,
        world.clock,
    )
    with patch.object(FakeGateway, "submit", receipt):
        result = command.execute(world.reference, Reference("send"))
    assert result.submission is not None
    assert command.execute(world.reference, Reference("send")) == result
    assert world.gateway.submits == 1
    assert repos.submissions.get(Reference("send")) == result.submission


def test_cancel_immediately_before_atomic_authorization(durable: Durable, world: World) -> None:
    repos, reopen = durable
    claim = repos.submissions.claim_dispatch

    def cancelled(_: object, dispatch: SubmissionDispatch) -> bool:
        snapshot = current(repos, world)
        repos.opportunities.save(
            OpportunitySave(snapshot.value.skip("Cancel won"), snapshot.revision)
        )
        return claim(dispatch)

    with (
        patch.object(type(repos.submissions), "claim_dispatch", cancelled),
        pytest.raises(PortError),
    ):
        command_for(repos, world, world.gateway).execute(world.reference, Reference("send"))
    restored = reopen()
    assert world.gateway.submits == world.gateway.reconciles == 0
    assert restored.submissions.get_request(Reference("send")) is None
    assert current(restored, world).value.state == OpportunityState.SKIPPED
    assert current(restored, world).value.approval == world.current().approval


def test_claim_first_blocks_fresh_and_stale_cancellation(durable: Durable, world: World) -> None:
    repos, reopen = durable
    dispatch = dispatch_for(repos, world)
    assert repos.submissions.claim_dispatch(dispatch)
    restored = reopen()
    assert current(restored, world).value.state == OpportunityState.SUBMISSION_IN_FLIGHT
    with pytest.raises(DomainError):
        current(restored, world).value.skip("Fresh cancellation")
    stale = dispatch.opportunity_snapshot
    with pytest.raises(PortError):
        restored.opportunities.save(
            OpportunitySave(stale.value.skip("Stale cancel"), stale.revision)
        )
    assert not restored.submissions.claim_dispatch(dispatch)
    assert restored.submissions.get_request(Reference("send")) == dispatch.request
    assert current(restored, world).value.approval == stale.value.approval
    assert world.gateway.submits == 0


def test_receipt_after_concurrent_revision_recovers_on_reopen(
    durable: Durable, world: World
) -> None:
    repos, reopen = durable
    send = FakeGateway.submit

    def changed(gateway: FakeGateway, request: SubmissionRequest) -> SubmissionResult:
        result = send(gateway, request)
        snapshot = current(repos, world)
        # A harmless concurrent CAS wins after claim, before receipt application.
        repos.opportunities.save(OpportunitySave(snapshot.value, snapshot.revision))
        return result

    with patch.object(FakeGateway, "submit", changed), pytest.raises(PortError):
        command_for(repos, world, world.gateway).execute(world.reference, Reference("send"))
    restored = reopen()
    attempts = restored.submissions.attempts_for(Reference("send"))
    assert any(item.status == SubmissionAttemptStatus.CONFIRMED for item in attempts)
    result = command_for(restored, world, world.gateway).execute(world.reference, Reference("send"))
    assert result.submission is not None
    assert current(restored, world).value.state == OpportunityState.SUBMITTED
    assert world.gateway.submits == 1 and world.gateway.reconciles == 0


def test_timeout_after_effect_reconciles_only_after_reopen(durable: Durable, world: World) -> None:
    repos, reopen = durable
    gateway = TimeoutAfterSend(world.clock)
    with pytest.raises(PortError):
        command_for(repos, world, gateway).execute(world.reference, Reference("send"))
    restored = reopen()
    assert current(restored, world).value.state == OpportunityState.SUBMISSION_IN_FLIGHT
    result = command_for(restored, world, gateway).execute(world.reference, Reference("send"))
    assert result == gateway.receipts[Reference("send")]
    assert gateway.submits == gateway.reconciles == 1
    assert current(restored, world).value.approval == world.current().approval


@pytest.mark.parametrize("different_ids", [False, True])
def test_concurrent_api_attempts_send_at_most_once(
    durable: Durable, world: World, different_ids: bool
) -> None:
    repos, reopen = durable
    barrier = Barrier(2)
    refresh = FakeSource.refresh
    gateway = ReceiptGateway(world.clock)

    def synchronize(source: FakeSource, request: RefreshOpportunityRequest) -> OpportunityStatus:
        status = refresh(source, request)
        barrier.wait(timeout=10)
        return status

    def compete(index: int) -> SubmissionResult | None:
        reference = Reference(f"send-{index}" if different_ids else "send")
        try:
            return command_for(repos, world, gateway).execute(world.reference, reference)
        except PortError:
            return None

    with (
        patch.object(FakeSource, "refresh", synchronize),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(compete, (1, 2)))
    assert gateway.submits == 1
    assert any(result is not None and result.submission is not None for result in results)
    restored = reopen()
    op = current(restored, world).value
    assert op.state == OpportunityState.SUBMITTED and op.submission is not None
    retry = command_for(restored, world, gateway).execute(world.reference, op.submission.reference)
    assert retry.submission == op.submission and gateway.submits == 1


@pytest.mark.parametrize("sent", [False, True])
def test_restart_after_claim_never_grants_a_second_send(
    durable: Durable, world: World, sent: bool
) -> None:
    repos, reopen = durable
    dispatch = dispatch_for(repos, world)
    assert repos.submissions.claim_dispatch(dispatch)
    gateway = ReceiptGateway(world.clock)
    if sent:
        gateway.submit(dispatch.request)  # Original owner simulated before process death.
    restored = reopen()
    command = command_for(restored, world, gateway)
    if sent:
        result = command.execute(world.reference, dispatch.request.reference)
        assert result == gateway.receipts[dispatch.request.reference]
        assert current(restored, world).value.state == OpportunityState.SUBMITTED
    else:
        with pytest.raises(PortError):
            command.execute(world.reference, dispatch.request.reference)
        assert current(restored, world).value.state == OpportunityState.SUBMISSION_IN_FLIGHT
    assert gateway.submits == int(sent)
    assert restored.submissions.get_request(dispatch.request.reference) == dispatch.request


def test_dynamodb_cancel_between_preflight_read_and_transaction(
    dynamo: DynamoDBRepositories, world: World, tmp_path: Path
) -> None:
    local = seed(world, tmp_path / "prepare.sqlite", approval=True)
    dynamo.opportunities.save(OpportunitySave(world.current(), None))
    store = dynamo.opportunities.database
    snapshot = local.opportunities.get(world.reference)
    assert snapshot is not None
    op = snapshot.value
    assert op.deliverable is not None and op.qa is not None and op.approval is not None
    content = local.executions.get_content(op.deliverable.content_reference)
    assert content is not None
    dispatch = SubmissionDispatch(
        SubmissionRequest(
            Reference("send"), op.deliverable, op.qa, op.approval, op.approval.target, content
        ),
        snapshot,
    )
    transact = store.transact

    def cancel(actions: list[Wire]) -> None:
        with patch.object(store, "transact", transact):
            dynamo.opportunities.save(
                OpportunitySave(op.skip("Cancelled after read"), snapshot.revision)
            )
        transact(actions)

    with patch.object(store, "transact", cancel), pytest.raises(PortError):
        dynamo.submissions.claim_dispatch(dispatch)
    assert dynamo.submissions.get_request(Reference("send")) is None
    restored = dynamo.opportunities.get(world.reference)
    assert restored is not None and restored.value.state == OpportunityState.SKIPPED


def test_ambiguous_claim_commit_never_grants_dispatch(durable: Durable, world: World) -> None:
    repos, reopen = durable
    claim = repos.submissions.claim_dispatch

    def lost_ack(_: object, dispatch: SubmissionDispatch) -> bool:
        assert claim(dispatch)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "claim", "Commit acknowledgement lost")

    with (
        patch.object(type(repos.submissions), "claim_dispatch", lost_ack),
        pytest.raises(PortError),
    ):
        command_for(repos, world, world.gateway).execute(world.reference, Reference("send"))
    assert world.gateway.submits == 0
    restored = reopen()
    assert current(restored, world).value.state == OpportunityState.SUBMISSION_IN_FLIGHT
    gateway = ReceiptGateway(world.clock)
    with pytest.raises(PortError):
        command_for(restored, world, gateway).execute(world.reference, Reference("send"))
    assert gateway.submits == 0 and gateway.reconciles == 1


def test_sqlite_partial_claim_write_rolls_back(world: World, tmp_path: Path) -> None:
    repos = seed(world, tmp_path / "rollback.sqlite", approval=True)
    before = repos.opportunities.get(world.reference)
    with (
        patch.object(
            SQLiteDatabase,
            "compare_and_swap",
            side_effect=PortError(PortErrorCode.UNAVAILABLE, "claim", "Injected write failure"),
        ),
        pytest.raises(PortError),
    ):
        command_for(ports(repos), world, world.gateway).execute(world.reference, Reference("send"))
    assert repos.submissions.get_request(Reference("send")) is None
    assert repos.opportunities.get(world.reference) == before
    assert world.gateway.submits == 0
