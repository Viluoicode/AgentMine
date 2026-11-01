"""Atomic offline handoff ownership and provisional receipt completion."""

import hashlib
import sqlite3
from dataclasses import dataclass, replace

from agentmine.application.contracts.manual_handoff import (
    HandoffError,
    HandoffReason,
    ManualHandoffClaim,
    ManualHandoffDraft,
    ManualHandoffView,
    ManualReceipt,
)
from agentmine.application.contracts.operator import OperatorReview
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.submission import SubmissionAttemptStatus, SubmissionResult
from agentmine.application.contracts.submission_context import (
    require,
)
from agentmine.application.use_cases.context import content_reference
from agentmine.domain.approval import ApprovalDecision, OperatorDecision
from agentmine.domain.budget import Budget
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key
from agentmine.infrastructure.sqlite.submissions import SQLiteSubmissionRepository


@dataclass(frozen=True, slots=True)
class SQLiteManualHandoffRepository:
    database: SQLiteDatabase

    def _value[T](
        self, connection: sqlite3.Connection, kind: str, key: str, cls: type[T]
    ) -> T | None:
        row = self.database.read(connection, kind, key, cls)
        return None if row is None else row.value

    def _matches(self, connection: sqlite3.Connection, kind: str, key: str, value: object) -> bool:
        return self._value(connection, kind, key, type(value)) == value

    def _keep(
        self,
        connection: sqlite3.Connection,
        kind: str,
        key: str,
        value: object,
        indexes: IndexValues | None = None,
    ) -> None:
        old = self._value(connection, kind, key, type(value))
        require(old is None or old == value)
        if old is None:
            self.database.write(connection, kind, key, value, 1, indexes or IndexValues())

    def _context(self, connection: sqlite3.Connection, draft: ManualHandoffDraft) -> None:
        envelope = draft.envelope
        require(
            self._matches(connection, "submission_envelope", envelope.reference.value, envelope)
            and self._matches(
                connection, "submission_scope", envelope.scope.value, envelope.reference
            )
            and self._matches(
                connection, "submission_account", envelope.account.reference.value, envelope.account
            )
            and self._matches(
                connection,
                "submission_channel",
                envelope.request.channel.reference.value,
                envelope.request.channel,
            )
        )
        review = self._value(
            connection, "operator_review", draft.review_reference.value, OperatorReview
        )
        decision = self._value(
            connection, "operator_decision", draft.review_reference.value, ApprovalDecision
        )
        require(review is not None and decision is not None)
        assert review is not None and decision is not None
        approval = draft.approved_snapshot.value.approval
        require(
            approval is not None
            and decision.decision == OperatorDecision.APPROVE
            and decision.actor == approval.actor
            and decision.decided_at == approval.approved_at
            and review.opportunity_snapshot == envelope.opportunity_snapshot
            and review.scope.destination == envelope.scope
            and review.scope.deliverable == envelope.deliverable
            and review.ledger_reference == envelope.run.specification.ledger_reference
            and review.content == draft.request.content
            and review.opportunity.approve(approval) == draft.approved_snapshot.value
        )
        # Check retained authoritative work/QA again within the ownership transaction.
        require(
            self._matches(
                connection,
                "execution",
                envelope.request.execution.value,
                envelope.run.plan.execution,
            )
            and self._matches(
                connection, "data_plan", envelope.request.execution.value, envelope.run.plan
            )
            and self._matches(
                connection,
                "data_result",
                envelope.request.execution.value,
                envelope.retained.result,
            )
            and self._matches(
                connection,
                "deliverable",
                composite_key(envelope.deliverable.reference.value, envelope.deliverable.version),
                envelope.deliverable,
            )
            and self._matches(
                connection,
                "content",
                envelope.deliverable.content_reference.value,
                bundle_content(envelope.retained.result),
            )
            and self._matches(
                connection, "qa_inspection", envelope.report.reference.value, envelope.inspection
            )
            and self._matches(
                connection, "qa_report", envelope.report.reference.value, envelope.report
            )
            and self._matches(
                connection,
                "operational_qa_applied",
                envelope.report.reference.value,
                envelope.report.reference,
            )
        )
        require(
            connection.execute("SELECT count(*) FROM snapshots WHERE kind='budget'").fetchone()[0]
            == 1
        )
        require(
            self._value(
                connection, "budget", envelope.run.specification.ledger_reference.value, Budget
            )
            is not None
        )

    def _current(self, connection: sqlite3.Connection, draft: ManualHandoffDraft) -> None:
        self._context(connection, draft)
        current = self.database.read(
            connection, "opportunity", draft.approved_snapshot.value.reference.value, Opportunity
        )
        if current != draft.approved_snapshot:
            raise HandoffError(HandoffReason.STALE_STATE)
        ledger = self.database.read(
            connection, "budget", draft.envelope.run.specification.ledger_reference.value, Budget
        )
        if ledger is None or ledger.revision != draft.ledger_revision:
            raise HandoffError(HandoffReason.LEDGER_CHANGED)

    def prepare(self, draft: ManualHandoffDraft) -> ManualHandoffDraft:
        draft = replace(draft)
        with self.database.transaction(write=True) as connection:
            old = self._value(
                connection, "manual_handoff_draft", draft.reference.value, ManualHandoffDraft
            )
            if old is not None:
                require(
                    old.submission_reference == draft.submission_reference
                    and old.envelope == draft.envelope
                    and old.review_reference == draft.review_reference
                    and old.approved_snapshot == draft.approved_snapshot
                    and old.ledger_revision == draft.ledger_revision
                )
                return old
            self._current(connection, draft)
            self._keep(
                connection,
                "manual_handoff_submission",
                draft.submission_reference.value,
                draft.reference,
            )
            self._keep(
                connection,
                "manual_handoff_draft",
                draft.reference.value,
                draft,
                IndexValues(parent=draft.envelope.reference.value),
            )
            return draft

    def claim(self, claim: ManualHandoffClaim) -> ManualHandoffClaim:
        claim = replace(claim)
        draft = claim.draft
        with self.database.transaction(write=True) as connection:
            require(self._matches(connection, "manual_handoff_draft", draft.reference.value, draft))
            old = self._value(
                connection, "manual_handoff_claim", draft.reference.value, ManualHandoffClaim
            )
            if old is not None:
                require(old.draft == draft)
                return old
            self._current(connection, draft)
            # Existing legacy package/intents cannot be adopted as B2 claim authority.
            require(
                SQLiteSubmissionRepository(self.database)._claim_request(connection, draft.request)
            )
            account = draft.envelope.account
            owner = composite_key(
                account.provider.value,
                account.effective_account,
                draft.envelope.request.channel.listing.value,
            )
            self._keep(connection, "manual_handoff_external_owner", owner, draft.reference)
            self._keep(connection, "manual_handoff_claim", draft.reference.value, claim)
            updated = draft.in_flight
            self.database.compare_and_swap(
                connection,
                "opportunity",
                updated.value.reference.value,
                updated.value,
                draft.approved_snapshot.revision,
                IndexValues(status=updated.value.state.value),
            )
            return claim

    def inspect(self, reference: Reference) -> ManualHandoffView | None:
        with self.database.transaction() as connection:
            draft = self._value(
                connection, "manual_handoff_draft", reference.value, ManualHandoffDraft
            )
            if draft is None:
                return None
            require(
                self._matches(
                    connection,
                    "manual_handoff_submission",
                    draft.submission_reference.value,
                    reference,
                )
            )
            claim = self._value(
                connection, "manual_handoff_claim", reference.value, ManualHandoffClaim
            )
            receipt = self._value(
                connection, "manual_handoff_receipt", reference.value, ManualReceipt
            )
            marker = self._value(connection, "manual_handoff_applied", reference.value, Reference)
            require((claim is None and receipt is None and marker is None) or claim is not None)
            if claim is not None:
                require(
                    claim.draft == draft
                    and self._matches(
                        connection,
                        "submission_request",
                        draft.submission_reference.value,
                        draft.request,
                    )
                )
            if receipt is not None:
                require(receipt.claim == claim)
                self._capture(connection, receipt)
            if marker is not None:
                require(marker == reference and receipt is not None)
            current = self.database.read(
                connection,
                "opportunity",
                draft.approved_snapshot.value.reference.value,
                Opportunity,
            )
            return ManualHandoffView(draft, claim, receipt, marker is not None, current)

    def _capture(self, connection: sqlite3.Connection, receipt: ManualReceipt) -> None:
        require(
            self._matches(
                connection,
                "submission_evidence",
                receipt.evidence.reference.value,
                receipt.evidence,
            )
            and self._matches(
                connection, "submission_capture", receipt.evidence.reference.value, receipt.capture
            )
            and receipt.capture.reference == content_reference(receipt.capture.text)
        )

    def retain_receipt(self, receipt: ManualReceipt) -> ManualReceipt:
        receipt = replace(receipt)
        reference = receipt.claim.draft.reference
        with self.database.transaction(write=True) as connection:
            require(
                self._matches(connection, "manual_handoff_claim", reference.value, receipt.claim)
            )
            self._capture(connection, receipt)
            self._keep(connection, "manual_handoff_receipt", reference.value, receipt)
            return receipt

    def complete_receipt(self, receipt: ManualReceipt) -> None:
        draft = receipt.claim.draft
        with self.database.transaction(write=True) as connection:
            require(
                self._matches(connection, "manual_handoff_receipt", draft.reference.value, receipt)
                and self._matches(
                    connection, "manual_handoff_claim", draft.reference.value, receipt.claim
                )
            )
            self._capture(connection, receipt)
            marker = self._value(
                connection, "manual_handoff_applied", draft.reference.value, Reference
            )
            if marker is not None:
                require(marker == draft.reference)
                return
            self._context(connection, draft)
            current = self.database.read(
                connection,
                "opportunity",
                draft.approved_snapshot.value.reference.value,
                Opportunity,
            )
            if current != draft.in_flight:
                raise HandoffError(HandoffReason.STALE_STATE)
            result = receipt.result
            rows = connection.execute(
                "SELECT * FROM snapshots WHERE kind='submission_attempt' AND parent=?",
                (draft.submission_reference.value,),
            ).fetchall()
            for row in rows:
                old = self.database.decode(row, SubmissionResult).value
                require(old.status != SubmissionAttemptStatus.CONFIRMED or old == result)
            result_key = composite_key(
                draft.submission_reference.value,
                hashlib.sha256(self.database.codec.dumps(result).encode()).hexdigest(),
            )
            self._keep(
                connection,
                "submission_attempt",
                result_key,
                result,
                IndexValues(
                    parent=draft.submission_reference.value, occurred_at=result.observed_at
                ),
            )
            self._keep(
                connection, "submission", draft.submission_reference.value, receipt.submission
            )
            updated = draft.in_flight.value.submit(receipt.submission)
            self.database.compare_and_swap(
                connection,
                "opportunity",
                updated.reference.value,
                updated,
                draft.in_flight.revision,
                IndexValues(status=updated.state.value),
            )
            self._keep(connection, "manual_handoff_applied", draft.reference.value, draft.reference)
