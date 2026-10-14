"""Atomic submission intent ownership and immutable receipts/outcomes."""

import hashlib
from dataclasses import dataclass

from agentmine.application.contracts.submission import SubmissionRequest, SubmissionResult
from agentmine.domain.values import Reference
from agentmine.domain.work import Outcome, Submission
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key


@dataclass(frozen=True, slots=True)
class SQLiteSubmissionRepository:
    database: SQLiteDatabase

    def save_request(self, request: SubmissionRequest) -> None:
        self.database.immutable("submission_request", request.reference.value, request)

    def claim_request(self, request: SubmissionRequest) -> bool:
        # Existing save_request also prevents dispatch, as required by intent semantics.
        return self.database.immutable("submission_request", request.reference.value, request)

    def get_request(self, reference: Reference) -> SubmissionRequest | None:
        result = self.database.get("submission_request", reference.value, SubmissionRequest)
        return None if result is None else result.value

    def record_attempt(self, result: SubmissionResult) -> None:
        with self.database.transaction(write=True) as connection:
            rows = connection.execute(
                "SELECT * FROM snapshots WHERE kind = 'submission_attempt' AND parent = ?",
                (result.reference.value,),
            ).fetchall()
            if any(self.database.decode(row, SubmissionResult).value == result for row in rows):
                return
            digest = hashlib.sha256(self.database.codec.dumps(result).encode()).hexdigest()
            self.database.write(
                connection,
                "submission_attempt",
                composite_key(result.reference.value, digest),
                result,
                1,
                IndexValues(parent=result.reference.value, occurred_at=result.observed_at),
            )

    def attempts_for(self, reference: Reference) -> tuple[SubmissionResult, ...]:
        return tuple(
            item.value
            for item in self.database.find(
                "submission_attempt", SubmissionResult, parent=reference.value
            )
        )

    def save(self, submission: Submission) -> None:
        self.database.immutable(
            "submission",
            submission.reference.value,
            submission,
            IndexValues(occurred_at=submission.submitted_at),
        )

    def get(self, reference: Reference) -> Submission | None:
        result = self.database.get("submission", reference.value, Submission)
        return None if result is None else result.value

    def save_outcome(self, outcome: Outcome) -> None:
        self.database.immutable("outcome", outcome.submission_reference.value, outcome)

    def get_outcome(self, submission_reference: Reference) -> Outcome | None:
        result = self.database.get("outcome", submission_reference.value, Outcome)
        return None if result is None else result.value
