"""Atomic submission intent ownership and immutable receipts/outcomes."""

import hashlib
from dataclasses import dataclass

from agentmine.application.contracts.submission import (
    OutcomeObservation,
    PaymentVerificationResult,
    SubmissionAttemptStatus,
    SubmissionRequest,
    SubmissionResult,
)
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.values import Reference
from agentmine.domain.work import Outcome, Submission
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key


@dataclass(frozen=True, slots=True)
class SQLiteSubmissionRepository:
    database: SQLiteDatabase

    def save_request(self, request: SubmissionRequest) -> None:
        self.claim_request(request)

    def claim_request(self, request: SubmissionRequest) -> bool:
        with self.database.transaction(write=True) as connection:
            rows = connection.execute(
                "SELECT * FROM snapshots WHERE kind = ?", ("submission_request",)
            ).fetchall()
            for row in rows:
                other = self.database.decode(row, SubmissionRequest).value
                if other.reference == request.reference:
                    if other != request:
                        raise PortError(
                            PortErrorCode.CONFLICT, "submit", "Submission identity changed"
                        )
                    return False
                if (other.deliverable.reference, other.deliverable.version) == (
                    request.deliverable.reference,
                    request.deliverable.version,
                ):
                    raise PortError(
                        PortErrorCode.CONFLICT,
                        "submit",
                        "Deliverable version already has a submission intent",
                    )
            self.database.write(
                connection, "submission_request", request.reference.value, request, 1, IndexValues()
            )
            return True

    def get_request(self, reference: Reference) -> SubmissionRequest | None:
        result = self.database.get("submission_request", reference.value, SubmissionRequest)
        return None if result is None else result.value

    def record_attempt(self, result: SubmissionResult) -> None:
        with self.database.transaction(write=True) as connection:
            rows = connection.execute(
                "SELECT * FROM snapshots WHERE kind = 'submission_attempt' AND parent = ?",
                (result.reference.value,),
            ).fetchall()
            existing = tuple(self.database.decode(row, SubmissionResult).value for row in rows)
            if result in existing:
                return
            if result.status == SubmissionAttemptStatus.CONFIRMED and any(
                item.status == SubmissionAttemptStatus.CONFIRMED for item in existing
            ):
                raise PortError(
                    PortErrorCode.CONFLICT, "receipt", "Confirmation already recorded differently"
                )
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

    def record_outcome_observation(self, observation: OutcomeObservation) -> None:
        self._record_observation(observation)

    def outcome_history(self, reference: Reference) -> tuple[OutcomeObservation, ...]:
        return tuple(
            item.value
            for item in self.database.find(
                "outcome_observation", OutcomeObservation, parent=reference.value
            )
        )

    def record_payment_observation(self, result: PaymentVerificationResult) -> None:
        self._record_observation(result)

    def payment_history(self, reference: Reference) -> tuple[PaymentVerificationResult, ...]:
        return tuple(
            item.value
            for item in self.database.find(
                "payment_observation", PaymentVerificationResult, parent=reference.value
            )
        )

    def _record_observation(
        self, observation: OutcomeObservation | PaymentVerificationResult
    ) -> None:
        kind = (
            "outcome_observation"
            if isinstance(observation, OutcomeObservation)
            else "payment_observation"
        )
        with self.database.transaction(write=True) as connection:
            rows = connection.execute("SELECT * FROM snapshots WHERE kind = ?", (kind,)).fetchall()
            for row in rows:
                if isinstance(observation, OutcomeObservation):
                    prior_outcome = self.database.decode(row, OutcomeObservation).value
                    if prior_outcome == observation:
                        return
                    if (
                        prior_outcome.submission_reference == observation.submission_reference
                        and prior_outcome.outcome is not None
                        and observation.outcome is not None
                        and prior_outcome.outcome != observation.outcome
                    ):
                        raise PortError(PortErrorCode.CONFLICT, "outcome", "Final outcome changed")
                else:
                    prior = self.database.decode(row, PaymentVerificationResult).value
                    if prior == observation:
                        return
                    old, new = prior.verification, observation.verification
                    if old is not None and new is not None:
                        if (
                            prior.submission_reference == observation.submission_reference
                            and old != new
                        ):
                            raise PortError(
                                PortErrorCode.CONFLICT, "payment", "Verified payment changed"
                            )
                        if prior.submission_reference != observation.submission_reference and (
                            old.verification_source,
                            old.payment_reference,
                        ) == (new.verification_source, new.payment_reference):
                            raise PortError(
                                PortErrorCode.CONFLICT,
                                "payment",
                                "Payment already credited to another submission",
                            )
            digest = hashlib.sha256(self.database.codec.dumps(observation).encode()).hexdigest()
            self.database.write(
                connection,
                kind,
                composite_key(observation.submission_reference.value, digest),
                observation,
                1,
                IndexValues(
                    parent=observation.submission_reference.value,
                    occurred_at=observation.observed_at,
                ),
            )

    def save_outcome(self, outcome: Outcome) -> None:
        self.database.immutable("outcome", outcome.submission_reference.value, outcome)

    def get_outcome(self, submission_reference: Reference) -> Outcome | None:
        result = self.database.get("outcome", submission_reference.value, Outcome)
        return None if result is None else result.value
