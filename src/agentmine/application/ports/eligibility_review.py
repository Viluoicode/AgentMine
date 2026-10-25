"""Durable eligibility evidence, separate from spending/submission approval."""

from typing import Protocol

from agentmine.application.contracts.eligibility import EligibilityReview, EligibilityReviewCommit
from agentmine.domain.eligibility_review import EligibilityResolution
from agentmine.domain.values import Reference


class EligibilityReviewRepository(Protocol):
    def save_review(self, review: EligibilityReview) -> None: ...

    def get_review(self, reference: Reference) -> EligibilityReview | None: ...

    def get_resolution(self, reference: Reference) -> EligibilityResolution | None: ...

    def resolve(self, commit: EligibilityReviewCommit) -> None:
        """Atomically retain one immutable decision and CAS the reviewed Opportunity.

        Same complete decision is idempotent; contradictory/stale decisions conflict.
        No decision may survive a failed Opportunity CAS. Both stores share authority.
        """
        ...
