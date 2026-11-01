"""Explicit provisional reporting use cases; no PaymentVerifier dependency."""

from dataclasses import dataclass, replace

from agentmine.application.contracts.payment_evidence import (
    PaymentEvidenceStatus,
    PaymentEvidenceView,
    PaymentObservation,
    PaymentReport,
    PaymentReportError,
    PaymentReportRequest,
)
from agentmine.application.contracts.submission_context import (
    EvidenceState,
    EvidenceTrust,
    EvidenceType,
    ImportEvidence,
    require,
)
from agentmine.application.ports.payment_evidence import PaymentEvidenceRepository
from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.context import check_content
from agentmine.application.use_cases.manual_handoff import GetManualHandoff
from agentmine.application.use_cases.submission_context import RecordSubmissionEvidence
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class GetPaymentEvidence:
    repository: PaymentEvidenceRepository
    actor: Reference
    ledger: Reference

    def execute(self, reference: Reference) -> PaymentEvidenceView:
        view = self.repository.inspect(reference)
        if view.report is not None:
            require(view.report.actor == self.actor and view.report.ledger == self.ledger)
        return view


@dataclass(frozen=True, slots=True)
class RecordPaymentEvidence:
    repository: PaymentEvidenceRepository
    get: GetPaymentEvidence
    handoffs: GetManualHandoff
    evidence: RecordSubmissionEvidence
    clock: Clock

    def execute(self, request: PaymentReportRequest) -> PaymentEvidenceView:
        request = replace(request)
        check_content(request.capture, request.capture.reference)
        existing = self.get.execute(request.reference)
        if existing.report is not None:
            if existing.report.request != request:
                raise PaymentReportError(PaymentEvidenceStatus.CONFLICT)
            if existing.observation is not None:
                return existing
            if existing.status == PaymentEvidenceStatus.CONFLICT:
                raise PaymentReportError(existing.status)
            report = existing.report
        else:
            handoff = self.handoffs.execute(request.handoff)
            require(
                handoff.applied and handoff.receipt is not None and handoff.opportunity is not None
            )
            assert handoff.opportunity is not None
            draft = handoff.draft
            report = self.repository.prepare(
                PaymentReport(
                    request,
                    draft.envelope.reference,
                    draft.envelope.scope,
                    draft.envelope.account,
                    draft.envelope.request.channel.reference,
                    draft.envelope.request.channel.listing,
                    self.get.actor,
                    self.get.ledger,
                    handoff.opportunity,
                    self.clock.now(),
                )
            )
        metadata = self.evidence.import_report(
            ImportEvidence(
                request.reference,
                report.envelope,
                report.source_snapshot.value.submission.reference
                if report.source_snapshot.value.submission is not None
                else None,
                EvidenceType.PAYMENT_REPORT,
                EvidenceTrust.OPERATOR_REPORTED,
                EvidenceState.UNVERIFIED,
                None,
                None,
                request.event_at,
                request.observed_at,
                request.provenance,
                request.capture,
            )
        )
        self.repository.attach(PaymentObservation(request.reference, metadata))
        return self.get.execute(request.reference)
