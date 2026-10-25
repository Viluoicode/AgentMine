"""Conditional transactional eligibility resolution; no eligibility policy in storage."""

from dataclasses import dataclass

from agentmine.application.contracts.eligibility import EligibilityReview, EligibilityReviewCommit
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.eligibility_review import EligibilityResolution
from agentmine.domain.values import Reference
from agentmine.infrastructure.dynamodb.store import DynamoStore, conflict, key


@dataclass(frozen=True, slots=True)
class DynamoDBEligibilityReviewRepository:
    database: DynamoStore

    def save_review(self, review: EligibilityReview) -> None:
        self.database.immutable("eligibility_review", review.reference.value, review)

    def get_review(self, reference: Reference) -> EligibilityReview | None:
        return self.database.value("eligibility_review", reference.value, EligibilityReview)

    def get_resolution(self, reference: Reference) -> EligibilityResolution | None:
        return self.database.value("eligibility_resolution", reference.value, EligibilityResolution)

    def resolve(self, commit: EligibilityReviewCommit) -> None:
        if self.get_review(commit.review.reference) != commit.review:
            raise conflict()
        prior = self.get_resolution(commit.review.reference)
        if prior is not None:
            if prior != commit.resolution:
                raise conflict()
            return
        expected = commit.review.opportunity_snapshot
        op = commit.opportunity
        raw = self.database.raw(*key("opportunity", op.reference.value))
        if raw is None or self.database.decode(raw, type(op)) != expected:
            raise conflict()
        item = self.database.item(
            *key("opportunity", op.reference.value), op, expected.revision + 1
        )
        item.update({name: value for name, value in raw.items() if name.startswith("GSI")})
        item["GSI1PK"] = "STATE#" + op.state.value
        decision = self.database.item(
            *key("eligibility_resolution", commit.review.reference.value), commit.resolution
        )
        try:
            self.database.transact(
                [self.database.put(item, revision=expected.revision), self.database.put(decision)]
            )
        except PortError as error:
            if (
                error.code != PortErrorCode.CONFLICT
                or self.get_resolution(commit.review.reference) != commit.resolution
            ):
                raise
