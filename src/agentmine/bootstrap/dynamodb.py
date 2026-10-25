"""Explicit adapter composition around an injected SDK client; creates no resources."""

from dataclasses import dataclass

from agentmine.infrastructure.dynamodb.approval import DynamoDBApprovalRepository
from agentmine.infrastructure.dynamodb.data import DynamoDBDataJournal
from agentmine.infrastructure.dynamodb.eligibility_review import DynamoDBEligibilityReviewRepository
from agentmine.infrastructure.dynamodb.evaluations import DynamoDBEvaluationRepository
from agentmine.infrastructure.dynamodb.executions import DynamoDBExecutionRepository
from agentmine.infrastructure.dynamodb.history import DynamoDBHistoricalRepository
from agentmine.infrastructure.dynamodb.ledger import DynamoDBCostLedgerRepository
from agentmine.infrastructure.dynamodb.opportunities import DynamoDBOpportunityRepository
from agentmine.infrastructure.dynamodb.qa import DynamoDBQAJournal
from agentmine.infrastructure.dynamodb.research import DynamoDBResearchJournal
from agentmine.infrastructure.dynamodb.store import DynamoClient, DynamoStore
from agentmine.infrastructure.dynamodb.submissions import DynamoDBSubmissionRepository


@dataclass(frozen=True)
class DynamoDBRepositories:
    opportunities: DynamoDBOpportunityRepository
    evaluations: DynamoDBEvaluationRepository
    executions: DynamoDBExecutionRepository
    submissions: DynamoDBSubmissionRepository
    ledger: DynamoDBCostLedgerRepository
    approvals: DynamoDBApprovalRepository
    history: DynamoDBHistoricalRepository
    research: DynamoDBResearchJournal
    data: DynamoDBDataJournal
    qa: DynamoDBQAJournal
    eligibility_reviews: DynamoDBEligibilityReviewRepository


def dynamodb_repositories(
    client: DynamoClient, table: str, *, page_size: int = 100
) -> DynamoDBRepositories:
    store = DynamoStore(client, table, page_size=page_size)
    return DynamoDBRepositories(
        DynamoDBOpportunityRepository(store),
        DynamoDBEvaluationRepository(store),
        DynamoDBExecutionRepository(store),
        DynamoDBSubmissionRepository(store),
        DynamoDBCostLedgerRepository(store),
        DynamoDBApprovalRepository(store),
        DynamoDBHistoricalRepository(store),
        DynamoDBResearchJournal(store),
        DynamoDBDataJournal(store),
        DynamoDBQAJournal(store),
        DynamoDBEligibilityReviewRepository(store),
    )
