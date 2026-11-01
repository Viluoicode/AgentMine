"""Immutable outcome captures, verification decisions and atomic Domain finalization."""

import sqlite3
from dataclasses import dataclass

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.outcome_evidence import (
    OutcomeEvent,
    OutcomeEvidenceError,
    OutcomeVerification,
    OutcomeVerificationRequest,
    OutcomeVerificationView,
    VerificationStatus,
)
from agentmine.application.contracts.submission_context import require
from agentmine.application.use_cases.context import content_reference
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference
from agentmine.domain.work import Outcome
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key


@dataclass(frozen=True, slots=True)
class SQLiteOutcomeEvidenceRepository:
    database: SQLiteDatabase

    def _value[T](
        self, connection: sqlite3.Connection, kind: str, key: str, cls: type[T]
    ) -> T | None:
        row = self.database.read(connection, kind, key, cls)
        return None if row is None else row.value

    def _keep(self, connection: sqlite3.Connection, kind: str, key: str, value: object) -> None:
        old = self._value(connection, kind, key, type(value))
        if old is not None and old != value:
            raise OutcomeEvidenceError(VerificationStatus.CONFLICT)
        if old is None:
            self.database.write(connection, kind, key, value, 1, IndexValues())

    def _event(self, connection: sqlite3.Connection, event: OutcomeEvent) -> None:
        receipt = event.receipt
        draft = receipt.claim.draft
        for kind, key, value in (
            ("manual_handoff_receipt", draft.reference.value, receipt),
            ("manual_handoff_claim", draft.reference.value, receipt.claim),
            ("manual_handoff_draft", draft.reference.value, draft),
            ("manual_handoff_applied", draft.reference.value, draft.reference),
            ("submission", draft.submission_reference.value, receipt.submission),
            ("submission_envelope", draft.envelope.reference.value, draft.envelope),
            ("submission_account", draft.envelope.account.reference.value, draft.envelope.account),
            (
                "submission_channel",
                draft.envelope.request.channel.reference.value,
                draft.envelope.request.channel,
            ),
            ("submission_evidence", event.reference.value, event.metadata),
        ):
            require(self._value(connection, kind, key, type(value)) == value)
        capture = self._value(
            connection, "submission_capture", event.reference.value, ReferencedText
        )
        require(
            capture is not None
            and content_reference(capture.text)
            == capture.reference
            == event.metadata.content_digest
        )
        require(
            connection.execute("SELECT count(*) FROM snapshots WHERE kind='budget'").fetchone()[0]
            == 1
        )
        require(
            connection.execute(
                "SELECT 1 FROM snapshots WHERE kind='budget' AND id=?",
                (draft.envelope.run.specification.ledger_reference.value,),
            ).fetchone()
            is not None
        )

    def record(self, event: OutcomeEvent) -> OutcomeEvent:
        with self.database.transaction(write=True) as connection:
            self._event(connection, event)
            account = event.receipt.claim.draft.envelope.account
            key = composite_key(
                account.provider.value,
                account.effective_account,
                event.receipt.claim.draft.envelope.request.channel.listing.value,
                event.metadata.event.value if event.metadata.event else "",
            )
            self._keep(connection, "outcome_event_owner", key, event.reference)
            self._keep(connection, "outcome_event", event.reference.value, event)
            return event

    def get(self, reference: Reference) -> OutcomeEvent | None:
        with self.database.transaction() as connection:
            event = self._value(connection, "outcome_event", reference.value, OutcomeEvent)
            if event is not None:
                self._event(connection, event)
            return event

    def prepare(self, request: OutcomeVerificationRequest) -> OutcomeVerificationRequest:
        with self.database.transaction(write=True) as connection:
            old = self._value(
                connection,
                "outcome_verification_request",
                request.reference.value,
                OutcomeVerificationRequest,
            )
            if old is not None:
                if old != request:
                    raise OutcomeEvidenceError(VerificationStatus.CONFLICT)
                return old
            self._event(connection, request.event)
            require(
                self._value(
                    connection, "outcome_event", request.event.reference.value, OutcomeEvent
                )
                == request.event
            )
            current = self.database.read(
                connection, "opportunity", request.snapshot.value.reference.value, Opportunity
            )
            if current != request.snapshot:
                raise OutcomeEvidenceError(VerificationStatus.CONFLICT)
            self._keep(connection, "outcome_verification_request", request.reference.value, request)
            return request

    def inspect(self, reference: Reference) -> OutcomeVerificationView | None:
        with self.database.transaction() as connection:
            request = self._value(
                connection,
                "outcome_verification_request",
                reference.value,
                OutcomeVerificationRequest,
            )
            if request is None:
                return None
            self._event(connection, request.event)
            require(
                self._value(
                    connection, "outcome_event", request.event.reference.value, OutcomeEvent
                )
                == request.event
            )
            decision = self._value(
                connection, "outcome_verification", reference.value, OutcomeVerification
            )
            marker = self._value(connection, "outcome_application", reference.value, Outcome)
            require(decision is None or decision.request == request)
            require(
                marker is None
                or (
                    decision is not None
                    and decision.outcome == marker
                    and self._value(
                        connection, "outcome", marker.submission_reference.value, Outcome
                    )
                    == marker
                )
            )
            current = self.database.read(
                connection, "opportunity", request.snapshot.value.reference.value, Opportunity
            )
            return OutcomeVerificationView(request, decision, marker is not None, current)

    def retain(self, decision: OutcomeVerification) -> OutcomeVerification:
        with self.database.transaction(write=True) as connection:
            require(
                self._value(
                    connection,
                    "outcome_verification_request",
                    decision.request.reference.value,
                    OutcomeVerificationRequest,
                )
                == decision.request
            )
            self._event(connection, decision.request.event)
            old = self._value(
                connection,
                "outcome_verification",
                decision.request.reference.value,
                OutcomeVerification,
            )
            if old is not None:
                # Concurrent identical observations keep the original server-owned decision time.
                from dataclasses import replace

                if old != replace(decision, verified_at=old.verified_at):
                    raise OutcomeEvidenceError(VerificationStatus.CONFLICT)
                return old
            self._keep(
                connection, "outcome_verification", decision.request.reference.value, decision
            )
            return decision

    def apply(self, decision: OutcomeVerification) -> None:
        outcome = decision.outcome
        if outcome is None:
            return
        with self.database.transaction(write=True) as connection:
            require(
                self._value(
                    connection,
                    "outcome_verification",
                    decision.request.reference.value,
                    OutcomeVerification,
                )
                == decision
            )
            self._event(connection, decision.request.event)
            old = self._value(
                connection, "outcome_application", decision.request.reference.value, Outcome
            )
            if old is not None:
                require(old == outcome)
                return
            request = decision.request
            current = self.database.read(
                connection, "opportunity", request.snapshot.value.reference.value, Opportunity
            )
            if current != request.snapshot:
                raise OutcomeEvidenceError(VerificationStatus.CONFLICT)
            updated = current.value.record_outcome(outcome)
            self._keep(connection, "outcome", outcome.submission_reference.value, outcome)
            self.database.compare_and_swap(
                connection,
                "opportunity",
                updated.reference.value,
                updated,
                current.revision,
                IndexValues(status=updated.state.value),
            )
            self._keep(connection, "outcome_application", request.reference.value, outcome)
