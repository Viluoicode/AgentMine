"""Single-file policy consent transactions and consistent budget recovery reads."""

import sqlite3
from dataclasses import dataclass

from agentmine.application.contracts.ai import AIResponse
from agentmine.application.contracts.budget_control import (
    BudgetControlError,
    BudgetControlSnapshot,
    BudgetPolicyApplication,
    BudgetPolicyChange,
    BudgetPolicyChangeReceipt,
    BudgetPolicyDecision,
    PolicyConflictReason,
)
from agentmine.application.contracts.data import DataPlan
from agentmine.application.contracts.qa import QAInspection
from agentmine.application.contracts.records import BudgetCommit, Versioned
from agentmine.application.contracts.research import ResearchClaim
from agentmine.application.contracts.workflow import ExecuteTaskRequest
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.budget import Budget
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository


@dataclass(frozen=True, slots=True)
class SQLiteBudgetControlRepository:
    database: SQLiteDatabase

    def _ledger(self, connection: sqlite3.Connection, reference: Reference) -> Versioned[Budget]:
        count = connection.execute("SELECT COUNT(*) FROM snapshots WHERE kind='budget'").fetchone()[
            0
        ]
        if count != 1:
            raise PortError(
                PortErrorCode.UNSUPPORTED, "budget_control", "Exactly one ledger required"
            )
        ledger = self.database.read(connection, "budget", reference.value, Budget)
        if ledger is None:
            raise BudgetControlError(PolicyConflictReason.NOT_FOUND)
        audit = self.database.read(
            connection,
            "budget_audit",
            composite_key(reference.value, ledger.revision),
            BudgetCommit,
        )
        if (
            audit is None
            or audit.revision != ledger.revision
            or audit.value.ledger_reference != reference
            or audit.value.budget != ledger.value
            or audit.value.expected_revision
            != (None if ledger.revision == 1 else ledger.revision - 1)
        ):
            raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
        return ledger

    def read(self, ledger: Reference) -> BudgetControlSnapshot:
        with self.database.transaction() as connection:
            snapshot = self._ledger(connection, ledger)
            opportunities = tuple(
                self.database.decode(row, Opportunity).value
                for row in connection.execute(
                    "SELECT * FROM snapshots WHERE kind='opportunity' ORDER BY id"
                )
            )
            # Reuse the existing same-connection runtime integrity inspection.
            runtime = SQLiteWorkerRuntimeRepository(self.database)
            runs = []
            for row in connection.execute(
                "SELECT id FROM snapshots WHERE kind='runtime_run' ORDER BY id"
            ):
                run = runtime._inspect(connection, Reference(row["id"]))
                if run is None or run.run.specification.ledger_reference != ledger:
                    raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
                runs.append(run)
            operations: set[Reference] = set()
            for row in connection.execute(
                "SELECT * FROM snapshots WHERE kind IN ('data_ai_claim','research_claim',"
                "'qa_ai_claim','data_response','research_response','qa_ai_response',"
                "'work_request','work_response') ORDER BY kind,id"
            ):
                kind = row["kind"]
                if kind == "data_ai_claim":
                    plan = self.database.decode(row, DataPlan).value
                    operation = plan.execution.authorization.request.context.operation_reference
                elif kind == "research_claim":
                    operation = self.database.decode(row, ResearchClaim).value.operation_reference
                elif kind == "qa_ai_claim":
                    inspection = self.database.decode(row, QAInspection).value
                    if inspection.ai_authorization is None:
                        raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
                    operation = inspection.ai_authorization.request.context.operation_reference
                elif kind == "work_request":
                    operation = self.database.decode(
                        row, ExecuteTaskRequest
                    ).value.operation_reference
                else:
                    operation = self.database.decode(row, AIResponse).value.operation_reference
                if kind.endswith("claim") and row["id"] != operation.value:
                    raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
                operations.add(operation)
            return BudgetControlSnapshot(
                snapshot,
                opportunities,
                tuple(runs),
                tuple(sorted(operations, key=lambda ref: ref.value)),
            )

    def get_change(self, reference: Reference) -> BudgetPolicyChange | None:
        row = self.database.get("budget_policy_change", reference.value, BudgetPolicyChange)
        if row is not None and row.value.reference != reference:
            raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
        return None if row is None else row.value

    def _receipt(
        self, connection: sqlite3.Connection, reference: Reference
    ) -> BudgetPolicyChangeReceipt | None:
        row = self.database.read(
            connection, "budget_policy_receipt", reference.value, BudgetPolicyChangeReceipt
        )
        decision = self.database.read(
            connection, "budget_policy_decision", reference.value, BudgetPolicyDecision
        )
        if row is None:
            if decision is not None:
                raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
            return None
        receipt = row.value
        change = self.database.read(
            connection, "budget_policy_change", reference.value, BudgetPolicyChange
        )
        if (
            change is None
            or change.value != receipt.change
            or receipt.change.reference != reference
            or decision is None
            or decision.value != receipt.decision
        ):
            raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
        self._ledger(connection, receipt.change.ledger_reference)
        audit = self.database.read(
            connection,
            "budget_audit",
            composite_key(receipt.change.ledger_reference.value, receipt.resulting_revision),
            BudgetCommit,
        )
        before = self.database.read(
            connection,
            "budget_audit",
            composite_key(receipt.change.ledger_reference.value, receipt.change.expected_revision),
            BudgetCommit,
        )
        if (
            before is None
            or audit is None
            or before.revision != receipt.change.expected_revision
            or audit.revision != receipt.resulting_revision
            or before.value.ledger_reference != receipt.change.ledger_reference
        ):
            raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
        expected = BudgetCommit(
            receipt.change.ledger_reference,
            receipt.change.update(Versioned(before.value.budget, receipt.change.expected_revision)),
            receipt.change.expected_revision,
            None,
        )
        if audit.value != expected:
            raise BudgetControlError(PolicyConflictReason.EVIDENCE_INVALID)
        return receipt

    def get_receipt(self, reference: Reference) -> BudgetPolicyChangeReceipt | None:
        with self.database.transaction() as connection:
            return self._receipt(connection, reference)

    def prepare(self, change: BudgetPolicyChange) -> BudgetPolicyChange:
        with self.database.transaction(write=True) as connection:
            snapshot = self._ledger(connection, change.ledger_reference)
            old = self.database.read(
                connection, "budget_policy_change", change.reference.value, BudgetPolicyChange
            )
            if old is not None:
                if old.value != change:
                    raise BudgetControlError(PolicyConflictReason.IDENTITY_CONFLICT)
                return old.value
            change.update(snapshot)
            self.database.write(
                connection,
                "budget_policy_change",
                change.reference.value,
                change,
                1,
                IndexValues(parent=change.ledger_reference.value, occurred_at=change.prepared_at),
            )
            return change

    def apply(self, command: BudgetPolicyApplication) -> BudgetPolicyChangeReceipt:
        change = command.change
        with self.database.transaction(write=True) as connection:
            old = self.database.read(
                connection, "budget_policy_change", change.reference.value, BudgetPolicyChange
            )
            if old is None or old.value != change:
                raise BudgetControlError(PolicyConflictReason.IDENTITY_CONFLICT)
            receipt = self._receipt(connection, change.reference)
            if receipt is not None:
                return receipt
            snapshot = self._ledger(connection, change.ledger_reference)
            if snapshot != command.snapshot:
                raise BudgetControlError(PolicyConflictReason.STALE_REVISION)
            updated = command.updated
            receipt = command.receipt
            self.database.compare_and_swap(
                connection, "budget", change.ledger_reference.value, updated, snapshot.revision
            )
            self.database.write(
                connection,
                "budget_audit",
                composite_key(change.ledger_reference.value, receipt.resulting_revision),
                BudgetCommit(change.ledger_reference, updated, snapshot.revision, None),
                receipt.resulting_revision,
                IndexValues(parent=change.ledger_reference.value),
            )
            self.database.write(
                connection,
                "budget_policy_decision",
                change.reference.value,
                command.decision,
                1,
                IndexValues(
                    parent=change.ledger_reference.value, occurred_at=command.decision.approved_at
                ),
            )
            self.database.write(
                connection,
                "budget_policy_receipt",
                change.reference.value,
                receipt,
                1,
                IndexValues(
                    parent=change.ledger_reference.value, occurred_at=command.decision.approved_at
                ),
            )
            return receipt
