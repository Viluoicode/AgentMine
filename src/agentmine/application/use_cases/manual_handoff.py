"""Offline manual intent coordination; no external send or financial provider."""

from dataclasses import dataclass

from agentmine.application.contracts.manual_handoff import (
    HandoffError,
    HandoffReadiness,
    HandoffReason,
    ManualHandoffClaim,
    ManualHandoffDraft,
    ManualHandoffView,
    ManualReceipt,
    PermissionStatus,
    ReportManualReceipt,
)
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.submission import SubmissionMode
from agentmine.application.contracts.submission_context import (
    EffectKnowledge,
    EvidenceState,
    EvidenceTrust,
    EvidenceType,
    ImportEvidence,
    require,
)
from agentmine.application.contracts.worker_execution import WorkerExecutionReason
from agentmine.application.ports.manual_handoff import (
    ManualChannelPermission,
    ManualHandoffRepository,
)
from agentmine.application.ports.operational_qa import OperationalQARepository
from agentmine.application.ports.qa import QAJournal
from agentmine.application.ports.repositories import (
    CostLedgerRepository,
    ExecutionRepository,
    OpportunityRepository,
)
from agentmine.application.ports.runtime import WorkerRunReader
from agentmine.application.ports.services import Clock
from agentmine.application.use_cases.context import load
from agentmine.application.use_cases.submission_context import (
    GetSubmissionConsent,
    GetSubmissionEnvelope,
    RecordSubmissionEvidence,
)
from agentmine.application.use_cases.worker_preflight import WorkerPreflight
from agentmine.domain.values import Reference


@dataclass(frozen=True, slots=True)
class InspectManualReadiness:
    envelopes: GetSubmissionEnvelope
    consent: GetSubmissionConsent
    opportunities: OpportunityRepository
    ledger: CostLedgerRepository
    permission: ManualChannelPermission
    worker_preflight: WorkerPreflight
    runtime: WorkerRunReader
    executions: ExecutionRepository
    qa: OperationalQARepository
    journal: QAJournal
    clock: Clock

    def execute(self, envelope_reference: Reference, review: Reference) -> HandoffReadiness:
        envelope = self.envelopes.execute(envelope_reference)
        reason = HandoffReason.NONE
        if envelope.mode != SubmissionMode.MANUAL:
            reason = HandoffReason.CONTEXT_UNSUPPORTED
        elif envelope.request.channel.effects != EffectKnowledge.NONE_DECLARED:
            reason = HandoffReason.ACCOUNT_EFFECTS_UNSUPPORTED
        if reason != HandoffReason.NONE:
            return HandoffReadiness(envelope_reference, reason, None)
        consent = self.consent.execute(review)
        if not consent.applied or consent.envelope != envelope:
            return HandoffReadiness(envelope_reference, HandoffReason.CONSENT_NOT_APPLIED, None)
        started = self.clock.now()
        permission = self.permission.inspect(envelope)
        if (
            permission.status != PermissionStatus.OFFLINE_TEST_ONLY
            or permission.scope != envelope.scope
            or not started <= permission.observed_at <= self.clock.now()
        ):
            return HandoffReadiness(
                envelope_reference, HandoffReason.CHANNEL_UNVERIFIED, permission
            )
        view = self.runtime.inspect(envelope.request.execution)
        binding = self.qa.for_execution(envelope.request.execution)
        if (
            view is None
            or not view.finished
            or view.ai_evidence_present
            or view.run != envelope.run
            or view.result != envelope.retained.result
            or view.deliverable != envelope.deliverable
            or binding is None
            or binding.reference != envelope.report.reference
            or not self.qa.applied(binding.reference)
            or self.qa.get_inspection(binding.reference) != envelope.inspection
            or self.journal.get_report(binding.reference) != envelope.report
            or self.executions.get_content(envelope.deliverable.content_reference)
            != bundle_content(envelope.retained.result)
        ):
            return HandoffReadiness(envelope_reference, HandoffReason.EVIDENCE_INVALID, permission)
        current = load(self.opportunities, envelope.run.specification.task.opportunity_reference)
        reason_from_worker = self.worker_preflight.check(envelope.run.specification, current.value)
        if reason_from_worker is not None:
            mapping = {
                WorkerExecutionReason.SOURCE_UNAVAILABLE: HandoffReason.SOURCE_UNAVAILABLE,
                WorkerExecutionReason.SOURCE_CHANGED: HandoffReason.SOURCE_CHANGED,
                WorkerExecutionReason.ELIGIBILITY_BLOCKED: HandoffReason.ELIGIBILITY_BLOCKED,
            }
            reason = mapping.get(reason_from_worker, HandoffReason.EVIDENCE_INVALID)
        elif load(self.opportunities, current.value.reference) != current:
            reason = HandoffReason.STALE_STATE
        if reason == HandoffReason.NONE and not self.consent.execute(review).applied:
            reason = HandoffReason.CONSENT_NOT_APPLIED
        return HandoffReadiness(envelope_reference, reason, permission)


@dataclass(frozen=True, slots=True)
class GetManualHandoff:
    repository: ManualHandoffRepository
    envelopes: GetSubmissionEnvelope

    def execute(self, reference: Reference) -> ManualHandoffView:
        view = self.repository.inspect(reference)
        if view is None:
            raise HandoffError(HandoffReason.NOT_FOUND)
        require(self.envelopes.execute(view.draft.envelope.reference) == view.draft.envelope)
        return view


@dataclass(frozen=True, slots=True)
class PrepareManualHandoff:
    repository: ManualHandoffRepository
    get: GetManualHandoff
    readiness: InspectManualReadiness

    def execute(
        self, reference: Reference, submission: Reference, envelope: Reference, review: Reference
    ) -> ManualHandoffView:
        existing = self.repository.inspect(reference)
        if existing is not None:
            view = self.get.execute(reference)
            require(
                view.draft.submission_reference == submission
                and view.draft.envelope.reference == envelope
                and view.draft.review_reference == review
            )
            return view
        result = self.readiness.execute(envelope, review)
        if result.reason != HandoffReason.NONE:
            raise HandoffError(result.reason)
        assert result.permission is not None
        context = self.readiness.envelopes.execute(envelope)
        snapshot = load(self.readiness.opportunities, context.opportunity_snapshot.value.reference)
        ledger = self.readiness.ledger.get(self.readiness.envelopes.ledger_reference)
        require(ledger is not None)
        assert ledger is not None
        draft = ManualHandoffDraft(
            reference,
            submission,
            context,
            review,
            snapshot,
            ledger.revision,
            self.readiness.clock.now(),
            result.permission,
        )
        self.repository.prepare(draft)
        return self.get.execute(reference)


@dataclass(frozen=True, slots=True)
class ConfirmManualHandoff:
    repository: ManualHandoffRepository
    get: GetManualHandoff
    readiness: InspectManualReadiness

    def execute(self, reference: Reference, *, confirm: bool) -> ManualHandoffView:
        if confirm is not True:
            raise HandoffError(HandoffReason.CONFIRMATION_REQUIRED)
        view = self.get.execute(reference)
        if view.claim is not None:
            return view  # Historical readback, never renewed authority.
        if view.reason != HandoffReason.NONE:
            raise HandoffError(view.reason)
        result = self.readiness.execute(view.draft.envelope.reference, view.draft.review_reference)
        if result.reason != HandoffReason.NONE:
            raise HandoffError(result.reason)
        assert result.permission is not None
        self.repository.claim(
            ManualHandoffClaim(view.draft, self.readiness.clock.now(), result.permission)
        )
        return self.get.execute(reference)


@dataclass(frozen=True, slots=True)
class RecordManualHandoffReceipt:
    repository: ManualHandoffRepository
    get: GetManualHandoff
    evidence: RecordSubmissionEvidence
    clock: Clock

    def execute(self, command: ReportManualReceipt) -> ManualHandoffView:
        view = self.get.execute(command.handoff)
        if view.claim is None:
            raise HandoffError(HandoffReason.CONFIRMATION_REQUIRED)
        # No source refresh or renewed permission is appropriate for historical evidence.
        meta = self.evidence.import_report(
            ImportEvidence(
                command.evidence_reference,
                view.draft.envelope.reference,
                view.draft.submission_reference,
                EvidenceType.RECEIPT_REPORT,
                EvidenceTrust.OPERATOR_REPORTED,
                EvidenceState.UNVERIFIED,
                None,
                None if command.external_id is None else Reference(command.external_id),
                command.reported_at,
                command.observed_at,
                command.provenance,
                command.capture,
            )
        )
        receipt = ManualReceipt(
            view.claim, meta, command.capture, command.external_id, command.external_url
        )
        self.repository.retain_receipt(receipt)
        self.repository.complete_receipt(receipt)
        return self.get.execute(command.handoff)
