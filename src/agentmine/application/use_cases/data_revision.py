"""Explicit deterministic revision preparation and consent; no worker dispatch."""

from dataclasses import dataclass, replace

from agentmine.application.contracts.data_revision import (
    DataRevisionApproval,
    DataRevisionRequest,
    RevisionAllocation,
    RevisionReason,
    RevisionView,
    require,
)
from agentmine.application.contracts.execution_evidence import DataExecutionEvidence
from agentmine.application.contracts.opportunities import same_terms
from agentmine.application.contracts.records import EvaluationRecord
from agentmine.application.contracts.revision_execution import PrepareRevisionRequest
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    InputEvidence,
    WorkSpecification,
)
from agentmine.application.errors import ApplicationError, ApplicationErrorCode
from agentmine.application.ports.data_revision import RevisionRuntimeRepository
from agentmine.application.ports.local_runtime import DataInputReader
from agentmine.application.ports.repositories import EvaluationRepository, OpportunityRepository
from agentmine.application.ports.services import Clock, OpportunitySource
from agentmine.application.use_cases.context import load
from agentmine.application.use_cases.eligibility import CheckEligibility
from agentmine.application.use_cases.revision_preflight import RevisionPreflight
from agentmine.domain.economics import EconomicAssessment
from agentmine.domain.eligibility_rules import EligibilityEngine
from agentmine.domain.scoring import ScoringAssessment
from agentmine.domain.values import Reference
from agentmine.domain.work import EligibilityStatus


@dataclass(frozen=True, slots=True)
class PrepareDataRevision:
    repository: RevisionRuntimeRepository
    opportunities: OpportunityRepository
    source: OpportunitySource
    clock: Clock
    operator: Reference
    ledger_reference: Reference
    reader: DataInputReader

    def execute(self, command: PrepareRevisionRequest) -> DataRevisionRequest:
        parent = self.repository.parent(command.parent_execution)
        require(parent is not None)
        assert parent is not None
        work = command.work
        op = parent.snapshot.value
        require(
            work.opportunity_reference == op.reference
            and parent.run.specification.actor == self.operator
            and parent.run.specification.ledger_reference == self.ledger_reference
        )
        inspection = CheckEligibility(
            self.opportunities, self.source, self.clock, EligibilityEngine(work.policy)
        ).inspect(work.eligibility)
        require(same_terms(parent.run.specification.source_context, inspection.source))
        require(inspection.result.status == EligibilityStatus.ELIGIBLE)
        existing = self.repository.get_request(command.reference)
        now = self.clock.now()
        evaluated_at = (
            now
            if existing is None
            else existing.specification.execution_evidence.evaluation.evaluated_at
            if existing.specification.execution_evidence is not None
            else now
        )
        economics = EconomicAssessment(op.potential_reward, command.economics)
        scoring = ScoringAssessment(economics, command.signals, command.scoring_policy)
        evaluation = EvaluationRecord(
            work.evaluation_reference,
            op.reference,
            inspection.result,
            economics.expected_net_value,
            scoring.score,
            evaluated_at,
            command.forecast_evidence,
            scoring,
        )
        sources = self.reader.load(work.inputs)
        spec = WorkSpecification(
            work.reference,
            parent.run.specification.task,
            self.ledger_reference,
            self.operator,
            now if existing is None else existing.specification.approved_at,
            inspection.source if existing is None else existing.specification.source_context,
            sources,
            tuple(
                InputEvidence(item.reference, Reference("sha256:" + item.digest))
                for item in sources
            ),
            work.columns,
            work.unique_by,
            work.min_records,
            work.max_records,
            work.constraints,
            DataExecutionEvidence(
                work.eligibility, work.policy, evaluation, work.eligibility_review_reference
            ),
            work.acceptance,
        )
        request = DataRevisionRequest(
            command.reference,
            parent.run,
            parent.deliverable,
            parent.snapshot,
            command.trigger,
            command.trigger_reference,
            spec,
            command.reason,
        )
        require(
            load(self.opportunities, op.reference) == parent.snapshot, RevisionReason.STALE_PARENT
        )
        self.repository.prepare(request)
        return request


@dataclass(frozen=True, slots=True)
class GetDataRevision:
    repository: RevisionRuntimeRepository
    operator: Reference
    ledger_reference: Reference

    def execute(self, reference: Reference) -> RevisionView:
        view = self.repository.inspect(reference)
        require(view is not None)
        assert view is not None
        require(
            view.request.specification.actor == self.operator
            and view.request.specification.ledger_reference == self.ledger_reference,
            RevisionReason.APPROVAL_REQUIRED,
        )
        return view


@dataclass(frozen=True, slots=True)
class ApproveDataRevision:
    repository: RevisionRuntimeRepository
    opportunities: OpportunityRepository
    evaluations: EvaluationRepository
    source: OpportunitySource
    clock: Clock
    operator: Reference
    ledger_reference: Reference

    def execute(
        self, reviewed: DataRevisionRequest, binding: ExecutionBinding, *, confirm: bool
    ) -> RevisionAllocation:
        require(confirm is True, RevisionReason.APPROVAL_REQUIRED)
        view = GetDataRevision(self.repository, self.operator, self.ledger_reference).execute(
            reviewed.reference
        )
        require(view.request == replace(reviewed), RevisionReason.IDENTITY_CONFLICT)
        if view.allocation is not None:
            require(
                view.allocation.binding == binding
                and view.allocation.approval.actor == self.operator
                and view.allocation.approval.approved_at <= self.clock.now(),
                RevisionReason.IDENTITY_CONFLICT,
            )
            return view.allocation
        current = load(self.opportunities, reviewed.parent_snapshot.value.reference)
        require(current == reviewed.parent_snapshot, RevisionReason.STALE_PARENT)
        reason = RevisionPreflight(
            self.opportunities,
            self.evaluations,
            self.source,
            self.clock,
            self.operator,
            self.ledger_reference,
        ).check(reviewed, current.value)
        if reason is not None:
            raise ApplicationError(
                ApplicationErrorCode.UNRESOLVED, "revision_approval", reason.value
            )
        return self.repository.approve(
            reviewed.reference,
            DataRevisionApproval(reviewed.reference, self.operator, self.clock.now(), True),
            binding,
        )
