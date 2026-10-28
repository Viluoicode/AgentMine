"""Atomic immutable revision ownership in the authoritative local SQLite workspace."""

import sqlite3
from dataclasses import dataclass, replace

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.contracts.data_revision import (
    DataRevisionApproval,
    DataRevisionRequest,
    RevisionAllocation,
    RevisionFinish,
    RevisionReason,
    RevisionRun,
    RevisionStart,
    RevisionTrigger,
    RevisionView,
    require,
)
from agentmine.application.contracts.operational_qa import QAApplicationBinding, QACompletion
from agentmine.application.contracts.operator import OperatorReview
from agentmine.application.contracts.qa import QAInspection, bundle_content, lifecycle_qa_result
from agentmine.application.contracts.records import EvaluationRecord
from agentmine.application.contracts.runtime import (
    ExecutionBinding,
    WorkerResult,
    WorkSpecification,
)
from agentmine.domain.approval import ApprovalAction, ApprovalDecision, OperatorDecision
from agentmine.domain.budget import Budget
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.qa import QAOutcome, QAReport
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable, Execution, QAResult
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository


@dataclass(frozen=True, slots=True)
class SQLiteRevisionRuntimeRepository:
    database: SQLiteDatabase

    def _value[T](
        self, connection: sqlite3.Connection, kind: str, key: str, cls: type[T]
    ) -> T | None:
        row = self.database.read(connection, kind, key, cls)
        return None if row is None else row.value

    def _keep(
        self,
        connection: sqlite3.Connection,
        kind: str,
        key: str,
        value: object,
        indexes: IndexValues | None = None,
    ) -> bool:
        old = self._value(connection, kind, key, type(value))
        if old is not None:
            require(old == value, RevisionReason.IDENTITY_CONFLICT)
            return False
        self.database.write(connection, kind, key, value, 1, indexes or IndexValues())
        return True

    def _parent(self, connection: sqlite3.Connection, request: DataRevisionRequest) -> None:
        req = replace(request)
        run = req.parent_run
        parent_id = run.binding.execution_reference.value
        # First-version authority stays permanent. Later parents require their own allocation.
        original = self._value(
            connection, "runtime_owner", run.specification.task.reference.value, ExecutionBinding
        )
        require(original is not None)
        if req.parent_deliverable.version == 1:
            stored_run = SQLiteWorkerRuntimeRepository(self.database)._run(
                connection, run.binding.execution_reference
            )
            require(original == run.binding and stored_run == run)
            finished = self._value(connection, "runtime_finish", parent_id, Deliverable)
        else:
            parent_revision = self._value(connection, "revision_run", parent_id, RevisionRun)
            require(parent_revision is not None and parent_revision.worker == run)
            assert parent_revision is not None
            require(
                self._allocation(connection, parent_revision.allocation.reference)
                == parent_revision.allocation
            )
            finished = self._value(connection, "revision_finish", parent_id, Deliverable)
        require(finished == req.parent_deliverable)
        require(self._value(connection, "execution", parent_id, Execution) == run.plan.execution)
        require(self._value(connection, "data_plan", parent_id, DataPlan) == run.plan)
        result = self._value(connection, "data_result", parent_id, DataResult)
        require(result is not None)
        assert result is not None
        WorkerResult(run, result)
        content = bundle_content(result)
        require(
            content.reference == req.parent_deliverable.content_reference
            and self._value(connection, "content", content.reference.value, ReferencedText)
            == content
        )
        key = composite_key(req.parent_deliverable.reference.value, req.parent_deliverable.version)
        require(self._value(connection, "deliverable", key, Deliverable) == req.parent_deliverable)
        require(self._value(connection, "qa", key, QAResult) == req.parent_snapshot.value.qa)
        bindings = connection.execute(
            "SELECT * FROM snapshots WHERE kind='operational_qa_binding' AND parent=?",
            (parent_id,),
        ).fetchall()
        require(len(bindings) == 1, RevisionReason.TRIGGER_INCOMPLETE)
        qa_binding = self.database.decode(bindings[0], QAApplicationBinding).value
        qa_inspection = self._value(
            connection, "qa_inspection", qa_binding.reference.value, QAInspection
        )
        qa_report = self._value(connection, "qa_report", qa_binding.reference.value, QAReport)
        criteria = run.specification.acceptance
        require(qa_inspection is not None and qa_report is not None and criteria is not None)
        assert qa_inspection is not None and qa_report is not None and criteria is not None
        require(
            qa_binding.deliverable == req.parent_deliverable
            and qa_inspection.plan == run.plan
            and qa_inspection.result == result
            and qa_inspection.formats == criteria.formats
            and qa_inspection.requirements == criteria.requirements
            and qa_report.deliverable == req.parent_deliverable
            and lifecycle_qa_result(qa_report) == req.parent_snapshot.value.qa
            and self._value(
                connection, "operational_qa_applied", qa_binding.reference.value, Reference
            )
            == qa_binding.reference,
            RevisionReason.TRIGGER_INCOMPLETE,
        )
        current = self.database.read(
            connection, "opportunity", req.parent_snapshot.value.reference.value, Opportunity
        )
        require(current == req.parent_snapshot, RevisionReason.STALE_PARENT)
        ledger = self._value(connection, "budget", req.specification.ledger_reference.value, Budget)
        require(ledger is not None)
        assert ledger is not None
        require(result.cost is not None and result.cost in ledger.records)
        require(
            connection.execute("SELECT count(*) FROM snapshots WHERE kind='budget'").fetchone()[0]
            == 1
        )
        require(
            not SQLiteWorkerRuntimeRepository(self.database)._has_ai_evidence(
                connection, run.binding
            ),
            RevisionReason.UNKNOWN_EFFECT,
        )
        trigger = req.trigger_reference.value
        if req.trigger == RevisionTrigger.QA:
            binding = self._value(
                connection, "operational_qa_binding", trigger, QAApplicationBinding
            )
            inspection = self._value(connection, "qa_inspection", trigger, QAInspection)
            report = self._value(connection, "qa_report", trigger, QAReport)
            require(
                binding is not None and inspection is not None and report is not None,
                RevisionReason.TRIGGER_INCOMPLETE,
            )
            assert binding is not None and inspection is not None and report is not None
            require(
                report.outcome in (QAOutcome.FAIL, QAOutcome.NEEDS_REVISION)
                and binding.deliverable == req.parent_deliverable
                and inspection.plan == run.plan
                and inspection.result == result
                and self._value(connection, "operational_qa_applied", trigger, Reference)
                == req.trigger_reference
                and lifecycle_qa_result(report) == req.parent_snapshot.value.qa
                and QACompletion(binding, inspection, report).opportunity
                == req.parent_snapshot.value
                and req.parent_snapshot.revision == binding.opportunity_snapshot.revision + 1
                and report.checked_at <= req.specification.approved_at,
                RevisionReason.TRIGGER_INCOMPLETE,
            )
        else:
            review = self._value(connection, "operator_review", trigger, OperatorReview)
            decision = self._value(connection, "operator_decision", trigger, ApprovalDecision)
            require(review is not None and decision is not None, RevisionReason.TRIGGER_INCOMPLETE)
            assert review is not None and decision is not None
            require(
                decision.decision == OperatorDecision.REQUEST_REVISION
                and decision.actor == req.specification.actor
                and review.scope.action == ApprovalAction.EXTERNAL_SUBMISSION
                and review.scope.deliverable == req.parent_deliverable
                and review.ledger_reference == req.specification.ledger_reference
                and review.content == content
                and review.opportunity.request_revision() == req.parent_snapshot.value
                and req.parent_snapshot.revision == review.opportunity_snapshot.revision + 1
                and decision.decided_at <= req.specification.approved_at,
                RevisionReason.TRIGGER_INCOMPLETE,
            )
            require(
                qa_report.outcome == QAOutcome.PASS
                and QACompletion(qa_binding, qa_inspection, qa_report).opportunity
                == review.opportunity,
                RevisionReason.TRIGGER_INCOMPLETE,
            )

    def get_request(self, reference: Reference) -> DataRevisionRequest | None:
        row = self.database.get("revision_request", reference.value, DataRevisionRequest)
        return None if row is None else row.value

    def prepare(self, request: DataRevisionRequest) -> bool:
        with self.database.transaction(write=True) as connection:
            old = self._value(
                connection, "revision_request", request.reference.value, DataRevisionRequest
            )
            if old is not None:
                require(old == request, RevisionReason.IDENTITY_CONFLICT)
                return False
            self._parent(connection, request)
            require(
                self._value(
                    connection,
                    "revision_successor",
                    request.parent_run.binding.execution_reference.value,
                    Reference,
                )
                is None,
                RevisionReason.SUCCESSOR_OWNED,
            )
            self._keep(
                connection,
                "revision_specification",
                request.specification.reference.value,
                request.specification,
            )
            evidence = request.specification.execution_evidence
            assert evidence is not None
            self._keep(
                connection,
                "evaluation",
                evidence.evaluation.reference.value,
                evidence.evaluation,
                IndexValues(
                    parent=evidence.evaluation.opportunity_reference.value,
                    occurred_at=evidence.evaluation.evaluated_at,
                ),
            )
            return self._keep(connection, "revision_request", request.reference.value, request)

    def _allocation(
        self, connection: sqlite3.Connection, reference: Reference
    ) -> RevisionAllocation | None:
        allocation = self._value(
            connection, "revision_allocation", reference.value, RevisionAllocation
        )
        if allocation is not None:
            require(
                self._value(connection, "revision_request", reference.value, DataRevisionRequest)
                == allocation.request
                and self._value(
                    connection, "revision_approval", reference.value, DataRevisionApproval
                )
                == allocation.approval
                and self._value(
                    connection,
                    "revision_successor",
                    allocation.request.parent_run.binding.execution_reference.value,
                    Reference,
                )
                == reference
                and self._value(
                    connection,
                    "revision_version",
                    composite_key(
                        allocation.binding.deliverable_reference.value, allocation.version
                    ),
                    Reference,
                )
                == reference
            )
            spec = allocation.request.specification
            evidence = spec.execution_evidence
            assert evidence is not None
            require(
                self._value(
                    connection, "revision_specification", spec.reference.value, WorkSpecification
                )
                == spec
                and self._value(
                    connection, "evaluation", evidence.evaluation.reference.value, EvaluationRecord
                )
                == evidence.evaluation
            )
        return allocation

    def get_allocation(self, reference: Reference) -> RevisionAllocation | None:
        with self.database.transaction() as connection:
            return self._allocation(connection, reference)

    def approve(
        self, reference: Reference, approval: DataRevisionApproval, binding: ExecutionBinding
    ) -> RevisionAllocation:
        with self.database.transaction(write=True) as connection:
            request = self._value(
                connection, "revision_request", reference.value, DataRevisionRequest
            )
            require(request is not None)
            assert request is not None
            allocation = RevisionAllocation(request, approval, binding)
            old = self._allocation(connection, reference)
            if old is not None:
                require(old == allocation, RevisionReason.IDENTITY_CONFLICT)
                return old
            self._parent(connection, request)
            parent_id = request.parent_run.binding.execution_reference.value
            require(
                self._value(connection, "revision_successor", parent_id, Reference) is None,
                RevisionReason.SUCCESSOR_OWNED,
            )
            key = composite_key(binding.deliverable_reference.value, allocation.version)
            require(
                self._value(connection, "revision_version", key, Reference) is None
                and self._value(connection, "deliverable", key, Deliverable) is None,
                RevisionReason.IDENTITY_CONFLICT,
            )
            self._unused(connection, allocation)
            ledger = self._value(
                connection, "budget", request.specification.ledger_reference.value, Budget
            )
            assert ledger is not None
            operation = binding.operation_reference
            require(
                operation not in ledger.released_operations
                and all(
                    item.request.context.operation_reference != operation
                    for item in ledger.authorizations
                )
                and all(item.context.operation_reference != operation for item in ledger.records),
                RevisionReason.IDENTITY_CONFLICT,
            )
            self._keep(connection, "revision_approval", reference.value, approval)
            self._keep(connection, "revision_successor", parent_id, reference)
            self._keep(connection, "revision_version", key, reference)
            self._keep(connection, "revision_allocation", reference.value, allocation)
            return allocation

    def _unused(self, connection: sqlite3.Connection, allocation: RevisionAllocation) -> None:
        binding = allocation.binding
        collision = connection.execute(
            "SELECT 1 FROM snapshots WHERE kind IN "
            "('execution','data_plan','data_result','work_request','work_response','revision_run') "
            "AND id=? LIMIT 1",
            (binding.execution_reference.value,),
        ).fetchone()
        require(collision is None, RevisionReason.IDENTITY_CONFLICT)
        for row in connection.execute(
            "SELECT * FROM snapshots WHERE kind='revision_allocation'"
        ).fetchall():
            other = self.database.decode(row, RevisionAllocation).value
            if other.reference != allocation.reference:
                require(
                    other.binding.execution_reference != binding.execution_reference
                    and other.binding.operation_reference != binding.operation_reference
                    and other.binding.specification_reference != binding.specification_reference,
                    RevisionReason.IDENTITY_CONFLICT,
                )
        require(
            not SQLiteWorkerRuntimeRepository(self.database)._has_ai_evidence(connection, binding),
            RevisionReason.UNKNOWN_EFFECT,
        )

    def start(self, command: RevisionStart) -> bool:
        run = command.run
        allocation = run.allocation
        binding = allocation.binding
        with self.database.transaction(write=True) as connection:
            require(
                self._allocation(connection, allocation.reference) == allocation,
                RevisionReason.APPROVAL_REQUIRED,
            )
            old = self._value(
                connection, "revision_run", binding.execution_reference.value, RevisionRun
            )
            if old is not None:
                require(old == run, RevisionReason.IDENTITY_CONFLICT)
                return False
            self._parent(connection, allocation.request)
            self._unused(connection, allocation)
            require(
                self.database.read(
                    connection,
                    "budget",
                    allocation.request.specification.ledger_reference.value,
                    Budget,
                )
                == command.ledger_snapshot,
                RevisionReason.STALE_PARENT,
            )
            self._keep(connection, "revision_run", binding.execution_reference.value, run)
            self._keep(
                connection,
                "execution",
                binding.execution_reference.value,
                run.worker.plan.execution,
                IndexValues(
                    parent=command.opportunity.reference.value, occurred_at=command.started_at
                ),
            )
            self._keep(connection, "data_plan", binding.execution_reference.value, run.worker.plan)
            self.database.compare_and_swap(
                connection,
                "opportunity",
                command.opportunity.reference.value,
                command.opportunity,
                command.opportunity_snapshot.revision,
                IndexValues(status=command.opportunity.state.value),
            )
            return True

    def save_result(self, reference: Reference, result: WorkerResult) -> bool:
        with self.database.transaction(write=True) as connection:
            allocation = self._allocation(connection, reference)
            require(allocation is not None)
            run = self._value(
                connection,
                "revision_run",
                result.run.binding.execution_reference.value,
                RevisionRun,
            )
            require(run is not None and run.allocation == allocation and run.worker == result.run)
            require(
                not SQLiteWorkerRuntimeRepository(self.database)._has_ai_evidence(
                    connection, result.run.binding
                ),
                RevisionReason.UNKNOWN_EFFECT,
            )
            replace(result)
            return self._keep(
                connection,
                "data_result",
                result.run.binding.execution_reference.value,
                result.result,
            )

    def finish(self, command: RevisionFinish) -> bool:
        run = command.run
        binding = run.worker.binding
        with self.database.transaction(write=True) as connection:
            require(self._allocation(connection, run.allocation.reference) == run.allocation)
            require(
                self._value(
                    connection, "revision_run", binding.execution_reference.value, RevisionRun
                )
                == run
                and self._value(
                    connection, "data_result", binding.execution_reference.value, DataResult
                )
                == command.retained.result
            )
            old = self._value(
                connection, "revision_finish", binding.execution_reference.value, Deliverable
            )
            if old is not None:
                require(old == command.deliverable, RevisionReason.IDENTITY_CONFLICT)
                return False
            require(
                not SQLiteWorkerRuntimeRepository(self.database)._has_ai_evidence(
                    connection, binding
                ),
                RevisionReason.UNKNOWN_EFFECT,
            )
            ledger = self._value(
                connection, "budget", run.worker.specification.ledger_reference.value, Budget
            )
            cost = command.retained.result.cost
            require(ledger is not None and cost is not None and cost in ledger.records)
            require(
                self.database.read(
                    connection, "opportunity", command.opportunity.reference.value, Opportunity
                )
                == command.opportunity_snapshot,
                RevisionReason.STALE_PARENT,
            )
            content = bundle_content(command.retained.result)
            self._keep(connection, "content", content.reference.value, content)
            self._keep(
                connection,
                "deliverable",
                composite_key(binding.deliverable_reference.value, run.allocation.version),
                command.deliverable,
            )
            self.database.compare_and_swap(
                connection,
                "opportunity",
                command.opportunity.reference.value,
                command.opportunity,
                command.opportunity_snapshot.revision,
                IndexValues(status=command.opportunity.state.value),
            )
            self._keep(
                connection,
                "revision_finish",
                binding.execution_reference.value,
                command.deliverable,
            )
            return True

    def inspect(self, reference: Reference) -> RevisionView | None:
        with self.database.transaction() as connection:
            request = self._value(
                connection, "revision_request", reference.value, DataRevisionRequest
            )
            if request is None:
                return None
            allocation = self._allocation(connection, reference)
            if allocation is None:
                return RevisionView(request, None, None, None, None)
            run = self._value(
                connection,
                "revision_run",
                allocation.binding.execution_reference.value,
                RevisionRun,
            )
            result = self._value(
                connection, "data_result", allocation.binding.execution_reference.value, DataResult
            )
            finished = self._value(
                connection,
                "revision_finish",
                allocation.binding.execution_reference.value,
                Deliverable,
            )
            require((result is None and finished is None) or run is not None)
            if run is not None:
                require(
                    run.allocation == allocation
                    and self._value(
                        connection,
                        "data_plan",
                        allocation.binding.execution_reference.value,
                        DataPlan,
                    )
                    == run.worker.plan
                    and self._value(
                        connection,
                        "execution",
                        allocation.binding.execution_reference.value,
                        Execution,
                    )
                    == run.worker.plan.execution
                )
            if finished is not None:
                require(result is not None)
                assert result is not None
                content = bundle_content(result)
                expected = Deliverable(
                    allocation.binding.deliverable_reference,
                    allocation.binding.execution_reference,
                    allocation.version,
                    content.reference,
                )
                require(
                    finished == expected
                    and self._value(
                        connection,
                        "deliverable",
                        composite_key(expected.reference.value, expected.version),
                        Deliverable,
                    )
                    == expected
                    and self._value(connection, "content", content.reference.value, ReferencedText)
                    == content
                )
            reason = RevisionReason.NONE
            if finished is None:
                op = self.database.read(
                    connection,
                    "opportunity",
                    request.parent_snapshot.value.reference.value,
                    Opportunity,
                )
                if SQLiteWorkerRuntimeRepository(self.database)._has_ai_evidence(
                    connection, allocation.binding
                ):
                    reason = RevisionReason.UNKNOWN_EFFECT
                elif (run is None and op != request.parent_snapshot) or (
                    run is not None
                    and (op is None or op.value.execution != run.worker.plan.execution)
                ):
                    reason = RevisionReason.STALE_PARENT
            return RevisionView(
                request,
                allocation,
                run,
                None if result is None or run is None else WorkerResult(run.worker, result),
                finished,
                reason,
            )
