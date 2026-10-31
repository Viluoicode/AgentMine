"""Atomic immutable local scope and provisional captures on the authoritative workspace."""

from dataclasses import dataclass, replace

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.contracts.submission_context import (
    SubmissionEnvelope,
    SubmissionEvidence,
    require,
)
from agentmine.application.use_cases.context import content_reference
from agentmine.domain.budget import Budget
from agentmine.domain.opportunity import Opportunity
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.database import IndexValues, SQLiteDatabase, composite_key


@dataclass(frozen=True, slots=True)
class SQLiteSubmissionContextRepository:
    database: SQLiteDatabase

    def get(self, reference: Reference) -> SubmissionEnvelope | None:
        with self.database.transaction() as connection:
            row = self.database.read(
                connection, "submission_envelope", reference.value, SubmissionEnvelope
            )
            if row is None:
                return None
            value = row.value
            for kind, key, expected in (
                ("submission_scope", value.scope.value, value.reference),
                ("submission_account", value.account.reference.value, value.account),
                (
                    "submission_channel",
                    value.request.channel.reference.value,
                    value.request.channel,
                ),
            ):
                stored = self.database.read(connection, kind, key, type(expected))
                require(stored is not None and stored.value == expected)
            return value

    def by_scope(self, reference: Reference) -> SubmissionEnvelope | None:
        row = self.database.get("submission_scope", reference.value, Reference)
        envelope = None if row is None else self.get(row.value)
        require(envelope is None or envelope.scope == reference)
        return envelope

    def prepare(self, envelope: SubmissionEnvelope) -> SubmissionEnvelope:
        envelope = replace(envelope)
        with self.database.transaction(write=True) as connection:
            old = self.database.read(
                connection, "submission_envelope", envelope.reference.value, SubmissionEnvelope
            )
            if old is not None:
                require(old.value == replace(envelope, prepared_at=old.value.prepared_at))
                return old.value
            op = envelope.opportunity_snapshot
            require(
                self.database.read(connection, "opportunity", op.value.reference.value, Opportunity)
                == op
            )

            def matches(kind: str, key: str, value: object) -> bool:
                row = self.database.read(connection, kind, key, type(value))
                return row is not None and row.value == value

            execution = envelope.request.execution.value
            run = envelope.run
            spec = run.specification
            require(
                matches("execution", execution, run.plan.execution)
                and matches("data_plan", execution, run.plan)
                and matches("data_result", execution, envelope.retained.result)
                and matches("observation", op.value.reference.value, envelope.observation)
                and matches(
                    "content",
                    envelope.deliverable.content_reference.value,
                    bundle_content(envelope.retained.result),
                )
                and matches(
                    "deliverable",
                    composite_key(
                        envelope.deliverable.reference.value, envelope.deliverable.version
                    ),
                    envelope.deliverable,
                )
                and matches("qa_inspection", envelope.report.reference.value, envelope.inspection)
                and matches("qa_report", envelope.report.reference.value, envelope.report)
                and matches(
                    "operational_qa_applied",
                    envelope.report.reference.value,
                    envelope.report.reference,
                )
            )
            # Reuse immutable finish identity and retained specification, not a client version.
            marker = "runtime_finish" if envelope.deliverable.version == 1 else "revision_finish"
            spec_kind = (
                "work_specification"
                if envelope.deliverable.version == 1
                else "revision_specification"
            )
            require(
                matches(marker, execution, envelope.deliverable)
                and matches(spec_kind, spec.reference.value, spec)
            )
            budget = self.database.read(connection, "budget", spec.ledger_reference.value, Budget)
            require(budget is not None and envelope.retained.result.cost is not None)
            assert budget is not None
            require(envelope.retained.result.cost in budget.value.records)
            require(
                connection.execute("SELECT count(*) FROM snapshots WHERE kind='budget'").fetchone()[
                    0
                ]
                == 1
            )
            for kind, key, value in (
                ("submission_account", envelope.account.reference.value, envelope.account),
                (
                    "submission_channel",
                    envelope.request.channel.reference.value,
                    envelope.request.channel,
                ),
            ):
                prior = self.database.read(connection, kind, key, type(value))
                require(prior is None or prior.value == value)
                if prior is None:
                    self.database.write(connection, kind, key, value, 1, IndexValues())
            self.database.write(
                connection,
                "submission_envelope",
                envelope.reference.value,
                envelope,
                1,
                IndexValues(parent=op.value.reference.value),
            )
            self.database.write(
                connection,
                "submission_scope",
                envelope.scope.value,
                envelope.reference,
                1,
                IndexValues(),
            )
            return envelope

    def get_evidence(self, reference: Reference) -> SubmissionEvidence | None:
        with self.database.transaction() as connection:
            row = self.database.read(
                connection, "submission_evidence", reference.value, SubmissionEvidence
            )
            if row is None:
                return None
            capture = self.database.read(
                connection, "submission_capture", reference.value, ReferencedText
            )
            require(capture is not None)
            assert capture is not None
            require(
                row.value.content_digest
                == capture.value.reference
                == content_reference(capture.value.text)
            )
            return row.value

    def record_evidence(self, evidence: SubmissionEvidence, capture: ReferencedText) -> None:
        evidence = replace(evidence)
        require(evidence.content_digest == capture.reference == content_reference(capture.text))
        with self.database.transaction(write=True) as connection:
            parent = self.database.read(
                connection, "submission_envelope", evidence.envelope.value, SubmissionEnvelope
            )
            require(parent is not None)
            assert parent is not None
            require(
                evidence.account == parent.value.account.reference
                and evidence.provider == parent.value.account.provider
                and evidence.actor == parent.value.run.specification.actor
            )
            old = self.database.read(
                connection, "submission_evidence", evidence.reference.value, SubmissionEvidence
            )
            stored = self.database.read(
                connection, "submission_capture", evidence.reference.value, ReferencedText
            )
            if old is not None:
                require(
                    old.value == replace(evidence, captured_at=old.value.captured_at)
                    and stored is not None
                    and stored.value == capture
                )
                return
            require(stored is None)
            self.database.write(
                connection,
                "submission_capture",
                evidence.reference.value,
                capture,
                1,
                IndexValues(),
            )
            self.database.write(
                connection,
                "submission_evidence",
                evidence.reference.value,
                evidence,
                1,
                IndexValues(parent=evidence.envelope.value, occurred_at=evidence.captured_at),
            )
