"""Lambda transport -> real use cases -> DynamoDB emulation, including replay."""

from types import SimpleNamespace

from history_fakes import make_world
from test_dynamodb_persistence import dynamo

from agentmine.bootstrap.dynamodb import DynamoDBRepositories, dynamodb_repositories
from agentmine.bootstrap.lambda_runtime import LambdaDependencies, create_lambda_handlers
from agentmine.domain.opportunity import OpportunityState
from agentmine.presentation.lambda_events import Workflow

__all__ = ["dynamo"]


def test_handler_resolves_fresh_repositories_and_persists_replayed_event(
    dynamo: DynamoDBRepositories,
) -> None:
    world = make_world("lambda-op")
    resolved: list[Workflow] = []

    def factory(workflow: Workflow) -> LambdaDependencies:
        resolved.append(workflow)
        store = dynamo.opportunities.database
        fresh = dynamodb_repositories(store.client, store.table)
        return LambdaDependencies(fresh.opportunities, world.clock, world.source)

    handlers = create_lambda_handlers(factory)
    context = SimpleNamespace(aws_request_id="aws-id")
    event = {
        "source": "agentmine",
        "detail-type": "agentmine.discover",
        "id": "schedule-1",
        "detail": {"schema_version": 1, "limit": 1},
    }
    handlers.discover(event, context)
    handlers.discover(event, context)
    command = {"schema_version": 1, "opportunity_id": "lambda-op", "correlation_id": "schedule-1"}
    handlers.normalize(command, context)
    result = handlers.normalize(command, context)
    assert result["data"]["state"] == "normalized"
    stored = dynamo.opportunities.get(world.reference)
    assert stored is not None and stored.revision == 2
    assert stored.value.state == OpportunityState.NORMALIZED
    assert dynamo.opportunities.get_observation(world.reference) == world.source.observations[0]
    assert resolved == [
        Workflow.DISCOVER,
        Workflow.DISCOVER,
        Workflow.NORMALIZE,
        Workflow.NORMALIZE,
    ]
