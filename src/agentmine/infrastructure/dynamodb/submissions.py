"""Transactional ownership and evidence guards; no external submission side effects."""

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
from agentmine.infrastructure.dynamodb.store import (
    DynamoStore,
    IndexValues,
    conflict,
    identity,
    key,
)


@dataclass(frozen=True)
class DynamoDBSubmissionRepository:
    database: DynamoStore

    def save_request(self, request: SubmissionRequest) -> None:
        self.claim_request(request)

    def claim_request(self, request: SubmissionRequest) -> bool:
        # Both uniqueness conditions must win in the SAME transaction.
        items = [
            self.database.item(*key("submission_request", request.reference.value), request),
            self.database.item(
                "SUBMISSION_VERSION#"
                + identity(request.deliverable.reference.value, request.deliverable.version),
                "OWNER",
                request.reference,
            ),
        ]
        try:
            self.database.transact([self.database.put(item) for item in items])
            return True
        except PortError as error:
            if error.code != PortErrorCode.CONFLICT:
                raise
            if self.get_request(request.reference) != request:
                raise conflict() from None
            return False

    def get_request(self, reference: Reference) -> SubmissionRequest | None:
        return self.database.value("submission_request", reference.value, SubmissionRequest)

    def record_attempt(self, result: SubmissionResult) -> None:
        items = self.database.evidence(
            "submission_attempt",
            identity(self.database.codec.dumps(result)),
            result,
            IndexValues(result.reference.value, result.observed_at),
        )
        if result.status == SubmissionAttemptStatus.CONFIRMED:
            items.append(
                self.database.item(*key("submission_confirmation", result.reference.value), result)
            )
        self.database.transact([self.database.put(item, identical=True) for item in items])

    def attempts_for(self, reference: Reference) -> tuple[SubmissionResult, ...]:
        return tuple(
            item.value
            for item in self.database.find(
                "submission_attempt", SubmissionResult, parent=reference.value
            )
        )

    def save(self, submission: Submission) -> None:
        self.database.immutable("submission", submission.reference.value, submission)

    def get(self, reference: Reference) -> Submission | None:
        return self.database.value("submission", reference.value, Submission)

    def record_outcome_observation(self, observation: OutcomeObservation) -> None:
        items = self.database.evidence(
            "outcome_observation",
            identity(self.database.codec.dumps(observation)),
            observation,
            IndexValues(observation.submission_reference.value, observation.observed_at),
        )
        if observation.outcome is not None:
            items.append(
                self.database.item(
                    *key("outcome_guard", observation.submission_reference.value),
                    observation.outcome,
                )
            )
        self.database.transact([self.database.put(item, identical=True) for item in items])

    def outcome_history(self, reference: Reference) -> tuple[OutcomeObservation, ...]:
        return tuple(
            item.value
            for item in self.database.find(
                "outcome_observation", OutcomeObservation, parent=reference.value
            )
        )

    def record_payment_observation(self, result: PaymentVerificationResult) -> None:
        items = self.database.evidence(
            "payment_observation",
            identity(self.database.codec.dumps(result)),
            result,
            IndexValues(result.submission_reference.value, result.observed_at),
        )
        proof = result.verification
        if proof is not None:
            items.append(
                self.database.item(*key("payment_guard", result.submission_reference.value), proof)
            )
            items.append(
                self.database.item(
                    "PAYMENT_OWNER#"
                    + identity(proof.verification_source.value, proof.payment_reference.value),
                    "OWNER",
                    result.submission_reference,
                )
            )
        self.database.transact([self.database.put(item, identical=True) for item in items])

    def payment_history(self, reference: Reference) -> tuple[PaymentVerificationResult, ...]:
        return tuple(
            item.value
            for item in self.database.find(
                "payment_observation", PaymentVerificationResult, parent=reference.value
            )
        )

    def save_outcome(self, outcome: Outcome) -> None:
        self.database.immutable("outcome", outcome.submission_reference.value, outcome)

    def get_outcome(self, submission_reference: Reference) -> Outcome | None:
        return self.database.value("outcome", submission_reference.value, Outcome)
