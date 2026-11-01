"""Provisional reports are never authority; a separately authenticated verifier is required."""

from dataclasses import dataclass

from agentmine.application.contracts.outcome_evidence import (
    OutcomeEvent,
    OutcomeEvidenceError,
    OutcomeVerificationRequest,
    OutcomeVerificationView,
    ReportOutcomeEvent,
    VerificationStatus,
)
from agentmine.application.contracts.submission_context import (
    EvidenceState,
    EvidenceTrust,
    EvidenceType,
    ImportEvidence,
    require,
)
from agentmine.application.ports.outcome_evidence import (
    OutcomeEvidenceRepository,
    OutcomeEvidenceVerifier,
)
from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.manual_handoff import GetManualHandoff
from agentmine.application.use_cases.submission_context import RecordSubmissionEvidence
from agentmine.domain.opportunity import OpportunityState
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class OutcomeEvidenceWorkflow:
    repository: OutcomeEvidenceRepository
    handoffs: GetManualHandoff
    evidence: RecordSubmissionEvidence
    verifier: OutcomeEvidenceVerifier
    clock: Clock

    def get(self, reference: Reference) -> OutcomeEvent:
        event = self.repository.get(reference)
        require(event is not None)
        assert event is not None
        view = self.handoffs.execute(event.receipt.claim.draft.reference)
        require(view.applied and view.receipt == event.receipt)
        return event

    def record(self, command: ReportOutcomeEvent) -> OutcomeEvent:
        view = self.handoffs.execute(command.handoff)
        require(view.applied and view.receipt is not None)
        assert view.receipt is not None
        require(command.event_at >= view.receipt.submission.submitted_at)
        metadata = self.evidence.import_report(
            ImportEvidence(
                command.reference,
                view.draft.envelope.reference,
                view.draft.submission_reference,
                EvidenceType.OUTCOME_REPORT,
                EvidenceTrust.OPERATOR_REPORTED,
                EvidenceState.UNVERIFIED,
                None,
                command.provider_event,
                command.event_at,
                command.observed_at,
                command.provenance,
                command.capture,
            )
        )
        return self.repository.record(OutcomeEvent(view.receipt, metadata, command.event_type))

    def status(self, reference: Reference) -> OutcomeVerificationView:
        view = self.repository.inspect(reference)
        require(view is not None)
        assert view is not None
        require(self.get(view.request.event.reference) == view.request.event)
        return view

    def verify(self, reference: Reference, event_reference: Reference) -> OutcomeVerificationView:
        event = self.get(event_reference)
        old = self.repository.inspect(reference)
        if old is not None:
            view = self.status(reference)
            if view.request.event != event:
                raise OutcomeEvidenceError(VerificationStatus.CONFLICT)
            request = view.request
        else:
            current = self.handoffs.execute(event.receipt.claim.draft.reference).opportunity
            if current is None or current.value.state != OpportunityState.SUBMITTED:
                raise OutcomeEvidenceError(
                    VerificationStatus.CONFLICT
                    if current is not None and current.value.outcome is not None
                    else VerificationStatus.BLOCKED
                )
            request = self.repository.prepare(OutcomeVerificationRequest(reference, event, current))
            view = self.status(reference)
        if view.applied:
            return view
        if view.decision is None:
            decision = self.verifier.verify(request)
            require(decision.request == request and decision.verified_at <= self.clock.now())
            decision = self.repository.retain(decision)
        else:
            decision = view.decision
        if decision.status == VerificationStatus.VERIFIED and not self.verifier.accepts(decision):
            raise OutcomeEvidenceError(VerificationStatus.BLOCKED)
        self.repository.apply(decision)
        return self.status(reference)
