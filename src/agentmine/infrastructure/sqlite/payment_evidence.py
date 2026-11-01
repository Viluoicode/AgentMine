"""Provisional-only journal on the authoritative workspace. No monetary ownership."""

import sqlite3
from dataclasses import dataclass, replace

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.manual_handoff import ManualReceipt
from agentmine.application.contracts.payment_evidence import (
    PaymentEvidenceStatus,
    PaymentEvidenceView,
    PaymentObservation,
    PaymentReport,
    PaymentReportError,
)
from agentmine.application.contracts.submission_context import (
    AccountIdentity,
    EvidenceState,
    EvidenceTrust,
    EvidenceType,
    SubmissionEvidence,
    require,
)
from agentmine.application.use_cases.context import content_reference
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference
from agentmine.domain.work import Outcome, Submission
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase


@dataclass(frozen=True, slots=True)
class SQLitePaymentEvidenceRepository:
    database: SQLiteDatabase

    def _value[T](
        self, connection: sqlite3.Connection, kind: str, key: str, cls: type[T]
    ) -> T | None:
        row = self.database.read(connection, kind, key, cls)
        return None if row is None else row.value

    def _bound(self, connection: sqlite3.Connection, report: PaymentReport) -> None:
        receipt = self._value(
            connection, "manual_handoff_receipt", report.request.handoff.value, ManualReceipt
        )
        require(receipt is not None)
        assert receipt is not None
        draft = receipt.claim.draft
        op = report.source_snapshot.value
        require(
            self._value(connection, "manual_handoff_applied", draft.reference.value, Reference)
            == draft.reference
            and report.envelope == draft.envelope.reference
            and report.scope == draft.envelope.scope
            and report.account == draft.envelope.account
            and report.channel == draft.envelope.request.channel.reference
            and report.listing == draft.envelope.request.channel.listing
            and report.actor == draft.envelope.run.specification.actor
            and report.ledger == draft.envelope.run.specification.ledger_reference
            and op.submission == receipt.submission
            and op.deliverable == receipt.submission.deliverable
            and op.task == draft.envelope.run.specification.task
            and op.execution == draft.envelope.run.plan.execution
            and self._value(connection, "submission", draft.submission_reference.value, Submission)
            == receipt.submission
        )
        require(
            connection.execute("SELECT count(*) FROM snapshots WHERE kind='budget'").fetchone()[0]
            == 1
        )
        require(
            connection.execute(
                "SELECT 1 FROM snapshots WHERE kind='budget' AND id=?", (report.ledger.value,)
            ).fetchone()
            is not None
        )
        if op.outcome is not None:
            require(
                self._value(connection, "outcome", receipt.submission.reference.value, Outcome)
                == op.outcome
            )

    def _lineage_matches(self, connection: sqlite3.Connection, report: PaymentReport) -> bool:
        op = report.source_snapshot.value
        submission = op.submission
        return (
            submission is not None
            and self._value(connection, "submission", submission.reference.value, Submission)
            == submission
            and self._value(
                connection, "manual_handoff_applied", report.request.handoff.value, Reference
            )
            == report.request.handoff
            and self._value(connection, "submission_scope", report.scope.value, Reference)
            == report.envelope
            and self._value(
                connection, "submission_account", report.account.reference.value, AccountIdentity
            )
            == report.account
            and (
                op.outcome is None
                or self._value(connection, "outcome", submission.reference.value, Outcome)
                == op.outcome
            )
        )

    def _current(self, connection: sqlite3.Connection, report: PaymentReport) -> bool:
        return (
            self.database.read(
                connection, "opportunity", report.source_snapshot.value.reference.value, Opportunity
            )
            == report.source_snapshot
        )

    def prepare(self, report: PaymentReport) -> PaymentReport:
        report = replace(report)
        with self.database.transaction(write=True) as connection:
            old = self._value(
                connection, "provisional_payment_report", report.reference.value, PaymentReport
            )
            if old is not None:
                if old != replace(report, prepared_at=old.prepared_at):
                    raise PaymentReportError(PaymentEvidenceStatus.CONFLICT)
                return old
            self._bound(connection, report)
            require(self._lineage_matches(connection, report))
            if not self._current(connection, report):
                raise PaymentReportError(PaymentEvidenceStatus.CONFLICT)
            # Never adopt an existing legacy/unowned capture or independent payment proof.
            require(
                self._value(
                    connection, "submission_evidence", report.reference.value, SubmissionEvidence
                )
                is None
                and self._value(
                    connection, "submission_capture", report.reference.value, ReferencedText
                )
                is None
            )
            require(
                content_reference(report.request.capture.text) == report.request.capture.reference
            )
            self.database.write(
                connection,
                "provisional_payment_report",
                report.reference.value,
                report,
                1,
                IndexValues(parent=report.envelope.value),
            )
            return report

    def _capture_matches(
        self, report: PaymentReport, metadata: SubmissionEvidence, capture: ReferencedText
    ) -> bool:
        request = report.request
        submission = report.source_snapshot.value.submission
        return (
            submission is not None
            and capture == request.capture
            and content_reference(capture.text) == capture.reference == metadata.content_digest
            and metadata.reference == report.reference
            and metadata.envelope == report.envelope
            and metadata.submission == submission.reference
            and metadata.actor == report.actor
            and metadata.provider == report.account.provider
            and metadata.account == report.account.reference
            and metadata.kind == EvidenceType.PAYMENT_REPORT
            and metadata.trust == EvidenceTrust.OPERATOR_REPORTED
            and metadata.state == EvidenceState.UNVERIFIED
            and metadata.observing_source is None
            and metadata.event is None
            and metadata.event_at == request.event_at
            and metadata.observed_at == request.observed_at
            and metadata.provenance == request.provenance
            and metadata.captured_at >= report.prepared_at
        )

    def attach(self, observation: PaymentObservation) -> None:
        observation = replace(observation)
        with self.database.transaction(write=True) as connection:
            ref = observation.report_reference.value
            report = self._value(connection, "provisional_payment_report", ref, PaymentReport)
            require(report is not None)
            assert report is not None
            metadata = self._value(connection, "submission_evidence", ref, SubmissionEvidence)
            capture = self._value(connection, "submission_capture", ref, ReferencedText)
            require(metadata == observation.metadata and capture is not None)
            assert metadata is not None and capture is not None
            require(self._capture_matches(report, metadata, capture))
            old = self._value(
                connection, "provisional_payment_observation", ref, PaymentObservation
            )
            if old is not None:
                require(old == observation)
                return
            self._bound(connection, report)
            require(self._lineage_matches(connection, report))
            if not self._current(connection, report):
                raise PaymentReportError(PaymentEvidenceStatus.CONFLICT)
            self.database.write(
                connection,
                "provisional_payment_observation",
                ref,
                observation,
                1,
                IndexValues(parent=report.envelope.value),
            )

    def inspect(self, reference: Reference) -> PaymentEvidenceView:
        with self.database.transaction() as connection:
            ref = reference.value
            report = self._value(connection, "provisional_payment_report", ref, PaymentReport)
            observation = self._value(
                connection, "provisional_payment_observation", ref, PaymentObservation
            )
            if report is None:
                return PaymentEvidenceView(
                    reference,
                    PaymentEvidenceStatus.MISSING
                    if observation is None
                    else PaymentEvidenceStatus.CONFLICT,
                )
            metadata = self._value(connection, "submission_evidence", ref, SubmissionEvidence)
            capture = self._value(connection, "submission_capture", ref, ReferencedText)
            status = PaymentEvidenceStatus.UNVERIFIED
            if not self._current(connection, report) or not self._lineage_matches(
                connection, report
            ):
                status = PaymentEvidenceStatus.CONFLICT
            elif metadata is None and capture is None:
                status = (
                    PaymentEvidenceStatus.CAPTURE_PENDING
                    if observation is None
                    else PaymentEvidenceStatus.MISSING
                )
            elif metadata is None or capture is None:
                status = PaymentEvidenceStatus.MISSING
            elif not self._capture_matches(report, metadata, capture) or (
                observation is not None and observation.metadata != metadata
            ):
                status = PaymentEvidenceStatus.CONFLICT
            elif observation is None:
                status = PaymentEvidenceStatus.CAPTURE_RETAINED
            return PaymentEvidenceView(
                reference, status, report, observation, metadata, capture is not None
            )
