"""Offline preparation and evidence inspection; no handoff, gateway or verifier."""

from dataclasses import dataclass, replace

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.operator import OperatorReview
from agentmine.application.contracts.submission_context import (
    ImportEvidence,
    PrepareEnvelope,
    SubmissionConsent,
    SubmissionEnvelope,
    SubmissionEvidence,
    bounded,
    require,
)
from agentmine.application.ports.approval import ApprovalRepository
from agentmine.application.ports.operational_qa import OperationalQARepository
from agentmine.application.ports.qa import QAJournal
from agentmine.application.ports.repositories import OpportunityRepository
from agentmine.application.ports.runtime import WorkerRunReader
from agentmine.application.ports.services import Clock
from agentmine.application.ports.submission_context import SubmissionContextRepository
from agentmine.application.use_cases.context import content_reference, load
from agentmine.domain.approval import ApprovalAction, OperatorDecision
from agentmine.domain.values import Reference
from agentmine.domain.work import HumanApproval


def require_owner(envelope: SubmissionEnvelope, operator: Reference, ledger: Reference) -> None:
    require(
        envelope.run.specification.actor == operator
        and envelope.run.specification.ledger_reference == ledger
    )


def review_envelope(
    repository: SubmissionContextRepository | None,
    review: OperatorReview,
    operator: Reference | None,
    ledger_reference: Reference | None = None,
) -> SubmissionEnvelope | None:
    if not review.scope.destination.value.startswith("submission-context:"):
        return None
    require(
        repository is not None
        and operator is not None
        and ledger_reference == review.ledger_reference
    )
    assert repository is not None and operator is not None
    envelope = repository.by_scope(review.scope.destination)
    require(envelope is not None)
    assert envelope is not None
    require_owner(envelope, operator, review.ledger_reference)
    require(
        review.scope.action == ApprovalAction.EXTERNAL_SUBMISSION
        and review.scope.deliverable == envelope.deliverable
        and review.opportunity_snapshot == envelope.opportunity_snapshot
        and review.content is not None
        and review.content.reference == envelope.deliverable.content_reference
        and review.requested_at >= envelope.prepared_at
    )
    return envelope


@dataclass(frozen=True, slots=True)
class GetSubmissionEnvelope:
    repository: SubmissionContextRepository
    operator: Reference
    ledger_reference: Reference

    def execute(self, reference: Reference) -> SubmissionEnvelope:
        envelope = self.repository.get(reference)
        require(envelope is not None)
        assert envelope is not None
        require_owner(envelope, self.operator, self.ledger_reference)
        return envelope


@dataclass(frozen=True, slots=True)
class PrepareSubmissionEnvelope:
    repository: SubmissionContextRepository
    runtime: WorkerRunReader
    opportunities: OpportunityRepository
    qa: OperationalQARepository
    journal: QAJournal
    clock: Clock
    operator: Reference
    ledger_reference: Reference

    def execute(self, command: PrepareEnvelope) -> SubmissionEnvelope:
        existing = self.repository.get(command.reference)
        if existing is not None:
            require_owner(existing, self.operator, self.ledger_reference)
            require(existing.request == command)
            return existing
        view = self.runtime.inspect(command.execution)
        require(
            view is not None
            and view.finished
            and view.result is not None
            and view.deliverable is not None
            and not view.ai_evidence_present
        )
        assert view is not None and view.result is not None and view.deliverable is not None
        spec = view.run.specification
        require(spec.actor == self.operator and spec.ledger_reference == self.ledger_reference)
        binding = self.qa.for_execution(command.execution)
        require(binding is not None)
        assert binding is not None
        inspection = self.qa.get_inspection(binding.reference)
        report = self.journal.get_report(binding.reference)
        require(
            inspection is not None and report is not None and self.qa.applied(binding.reference)
        )
        assert inspection is not None and report is not None
        observation = self.opportunities.get_observation(spec.task.opportunity_reference)
        require(observation is not None)
        assert observation is not None
        from agentmine.application.contracts.runtime import WorkerResult

        envelope = SubmissionEnvelope(
            command,
            view.opportunity_snapshot,
            view.run,
            WorkerResult(view.run, view.result),
            view.deliverable,
            inspection,
            report,
            observation,
            self.clock.now(),
        )
        require(
            load(self.opportunities, observation.opportunity.reference) == view.opportunity_snapshot
        )
        return self.repository.prepare(envelope)


@dataclass(frozen=True, slots=True)
class RecordSubmissionEvidence:
    repository: SubmissionContextRepository
    get: GetSubmissionEnvelope
    clock: Clock

    def import_report(self, command: ImportEvidence) -> SubmissionEvidence:
        envelope = self.get.execute(command.envelope)
        old = self.repository.get_evidence(command.reference)
        evidence = SubmissionEvidence(
            command.reference,
            command.envelope,
            command.submission,
            command.kind,
            command.trust,
            command.state,
            self.get.operator,
            command.observing_source,
            envelope.account.provider,
            envelope.account.reference,
            command.event,
            command.event_at,
            command.observed_at,
            self.clock.now() if old is None else old.captured_at,
            command.capture.reference,
            command.provenance,
        )
        return self.execute(evidence, command.capture)

    def execute(self, evidence: SubmissionEvidence, capture: ReferencedText) -> SubmissionEvidence:
        envelope = self.get.execute(evidence.envelope)
        bounded(capture.text, 64000)
        require(
            evidence.actor == self.get.operator
            and evidence.provider == envelope.account.provider
            and evidence.account == envelope.account.reference
            and evidence.captured_at <= self.clock.now()
            and evidence.content_digest == capture.reference == content_reference(capture.text)
        )
        self.repository.record_evidence(evidence, capture)
        retained = self.repository.get_evidence(evidence.reference)
        require(retained is not None)
        assert retained is not None
        require(retained == replace(evidence, captured_at=retained.captured_at))
        return retained


@dataclass(frozen=True, slots=True)
class GetSubmissionEvidence:
    repository: SubmissionContextRepository
    get: GetSubmissionEnvelope

    def execute(self, reference: Reference) -> SubmissionEvidence:
        evidence = self.repository.get_evidence(reference)
        require(evidence is not None)
        assert evidence is not None
        self.get.execute(evidence.envelope)
        return evidence


@dataclass(frozen=True, slots=True)
class GetSubmissionConsent:
    repository: SubmissionContextRepository
    approvals: ApprovalRepository
    opportunities: OpportunityRepository
    operator: Reference
    ledger_reference: Reference

    def execute(self, review_reference: Reference) -> SubmissionConsent:
        review = self.approvals.get_review(review_reference)
        require(review is not None)
        assert review is not None
        envelope = review_envelope(self.repository, review, self.operator, self.ledger_reference)
        require(envelope is not None)
        assert envelope is not None
        decision = self.approvals.get_decision(review_reference)
        applied = False
        if decision is not None and decision.decision == OperatorDecision.APPROVE:
            require(decision.actor == self.operator and decision.decided_at >= review.requested_at)
            expected = review.opportunity.approve(
                HumanApproval(
                    envelope.deliverable, envelope.scope, self.operator, decision.decided_at
                )
            )
            current = load(self.opportunities, expected.reference)
            applied = (
                current.value == expected
                and current.revision == review.opportunity_snapshot.revision + 1
            )
        return SubmissionConsent(
            envelope,
            review_reference,
            applied,
            "Applied local scope consent; B1 grants no handoff/send authority"
            if applied
            else "Pending, unapplied or stale scope consent; no action authority",
        )
