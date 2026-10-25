"""Atomic eligibility decision and Opportunity revision, with immutable review evidence."""

from dataclasses import dataclass

from agentmine.application.contracts.eligibility import EligibilityReview, EligibilityReviewCommit
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.eligibility_review import EligibilityResolution
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase


@dataclass(frozen=True, slots=True)
class SQLiteEligibilityReviewRepository:
    database: SQLiteDatabase

    def save_review(self, review: EligibilityReview) -> None:
        self.database.immutable("eligibility_review", review.reference.value, review)

    def get_review(self, reference: Reference) -> EligibilityReview | None:
        row = self.database.get("eligibility_review", reference.value, EligibilityReview)
        return None if row is None else row.value

    def get_resolution(self, reference: Reference) -> EligibilityResolution | None:
        row = self.database.get("eligibility_resolution", reference.value, EligibilityResolution)
        return None if row is None else row.value

    def resolve(self, commit: EligibilityReviewCommit) -> None:
        reference = commit.review.reference.value
        with self.database.transaction(write=True) as connection:
            retained = self.database.read(
                connection, "eligibility_review", reference, EligibilityReview
            )
            if retained is None or retained.value != commit.review:
                raise PortError(PortErrorCode.CONFLICT, "eligibility_review", "Review mismatch")
            prior = self.database.read(
                connection, "eligibility_resolution", reference, EligibilityResolution
            )
            if prior is not None:
                if prior.value != commit.resolution:
                    raise PortError(PortErrorCode.CONFLICT, "eligibility_review", "Already decided")
                return
            expected = commit.review.opportunity_snapshot
            current = self.database.read(
                connection, "opportunity", expected.value.reference.value, Opportunity
            )
            if current != expected:
                raise PortError(PortErrorCode.CONFLICT, "eligibility_review", "Opportunity changed")
            updated = commit.opportunity
            self.database.compare_and_swap(
                connection,
                "opportunity",
                updated.reference.value,
                updated,
                expected.revision,
                IndexValues(status=updated.state.value),
            )
            self.database.write(
                connection,
                "eligibility_resolution",
                reference,
                commit.resolution,
                1,
                IndexValues(
                    parent=updated.reference.value, occurred_at=commit.resolution.decided_at
                ),
            )
