"""Pre-C1 test snapshots are immutable compatibility evidence, never production history."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_partition_contracts import FIXTURES, acceptance, load, specification

from agentmine.application.contracts.data import (
    DataCell,
    DataPartitionPolicy,
    DataPlan,
    DataResult,
    PartitionAcceptance,
    TextCase,
)
from agentmine.application.contracts.qa import DataAcceptanceCriteria, QAInspection
from agentmine.application.contracts.runtime import WorkerRun, WorkSpecification
from agentmine.application.errors import PortError
from agentmine.infrastructure.snapshots import SnapshotCodec
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.runtime import SQLiteWorkerRuntimeRepository


@pytest.mark.parametrize(
    "filename,model",
    [
        ("data_cell-v1.json", DataCell),
        ("data_plan-v1.json", DataPlan),
        ("data_result-v1.json", DataResult),
        ("work_specification-v1.json", WorkSpecification),
        ("qa_inspection-v1.json", QAInspection),
    ],
)
def test_pre_c1_payloads_decode_without_activation(filename: str, model: type[object]) -> None:
    original = (FIXTURES / filename).read_bytes()
    value = SnapshotCodec().loads(original.decode(), model)
    assert value is not None
    assert (FIXTURES / filename).read_bytes() == original


def test_fixture_digest_manifest() -> None:
    for name, expected in json.loads((FIXTURES / "sha256.json").read_text()).items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("mutation", ["unknown_field", "envelope_version", "missing_required"])
def test_snapshot_strictness(mutation: str) -> None:
    node = json.loads((FIXTURES / "data_cell-v1.json").read_text())
    if mutation == "unknown_field":
        node["value"]["fields"]["allow_anything"] = True
    elif mutation == "envelope_version":
        node["version"] = 2
    else:
        del node["value"]["fields"]["name"]
    with pytest.raises(PortError):
        SnapshotCodec().loads(json.dumps(node), DataCell)


def test_nested_legacy_inspection_and_reconstructed_run() -> None:
    inspection = load("qa_inspection-v1.json", QAInspection)
    assert isinstance(inspection.plan, DataPlan) and isinstance(inspection.result, DataResult)
    assert inspection.partition_acceptance is None
    assert inspection.plan.output_policy is None
    assert all(
        cell.input_presence is None for row in inspection.result.records for cell in row.cells
    )
    # Reconstructed tagged wrapper, NOT an authentic historical WorkerRun payload.
    spec = json.loads((FIXTURES / "work_specification-v1.json").read_text())["value"]
    plan = json.loads((FIXTURES / "data_plan-v1.json").read_text())["value"]

    def ref(value: str) -> dict[str, object]:
        return {"type": "agentmine.domain.values.Reference", "fields": {"value": value}}

    binding = {
        "type": "agentmine.application.contracts.runtime.ExecutionBinding",
        "fields": {
            "specification_reference": ref("cli-spec"),
            "execution_reference": ref("cli-exec"),
            "operation_reference": ref("cli-op"),
            "deliverable_reference": ref("cli-deliverable"),
        },
    }
    payload = {
        "version": 1,
        "value": {
            "type": "agentmine.application.contracts.runtime.WorkerRun",
            "fields": {"binding": binding, "specification": spec, "plan": plan},
        },
    }
    run = SnapshotCodec().loads(json.dumps(payload), WorkerRun)
    assert run.specification.output_policy is None and run.plan.output_policy is None


def test_v2_round_trip_and_unknown_fields() -> None:
    codec = SnapshotCodec()
    spec = specification()
    assert codec.loads(codec.dumps(spec), WorkSpecification) == spec
    plan = spec.plan(load("data_plan-v1.json", DataPlan).execution)
    assert codec.loads(codec.dumps(plan), DataPlan) == plan
    assert codec.loads(codec.dumps(acceptance()), DataAcceptanceCriteria) == acceptance()
    node = json.loads(codec.dumps(spec.output_policy))
    node["value"]["fields"]["unknown"] = True
    with pytest.raises(PortError):
        codec.loads(json.dumps(node), DataPartitionPolicy)


def test_missing_v2_acceptance_does_not_migrate_to_valid() -> None:
    codec = SnapshotCodec()
    node = json.loads(codec.dumps(specification()))
    del node["value"]["fields"]["acceptance"]
    with pytest.raises(PortError):
        codec.loads(json.dumps(node), WorkSpecification)


def test_same_id_policy_or_threshold_conflicts(tmp_path: Path) -> None:
    repo = SQLiteWorkerRuntimeRepository(SQLiteDatabase(tmp_path / "contracts.sqlite3"))
    spec = specification()
    # Immutable database persistence boundary; no fabricated operational Opportunity seeded.
    repo.database.immutable("work_specification", spec.reference.value, spec)
    assert repo.get_specification(spec.reference) == spec
    with pytest.raises(PortError):
        repo.database.immutable(
            "work_specification",
            spec.reference.value,
            replace(
                spec,
                acceptance=replace(acceptance(), partition_acceptance=PartitionAcceptance(2, 1, 1)),
            ),
        )
    with pytest.raises(PortError):
        repo.database.immutable(
            "work_specification",
            spec.reference.value,
            replace(spec, columns=(replace(spec.columns[0], case=TextCase.LOWER),)),
        )
    assert repo.get_specification(spec.reference) == spec


def test_unapproved_v2_runtime_is_blocked_before_authorization_or_dispatch(tmp_path: Path) -> None:
    from test_worker_execution_runtime import build_world

    from agentmine.application.contracts.runtime import ExecutionBinding
    from agentmine.application.contracts.worker_execution import (
        ExecuteWorkerRequest,
        WorkerExecutionReason,
    )
    from agentmine.domain.values import Reference
    from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository

    world = build_world(tmp_path)
    approved = replace(
        specification(),
        reference=Reference("new-v2"),
        task=world.specification.task,
        source_context=world.specification.source_context,
        sources=world.specification.sources,
        input_evidence=world.specification.input_evidence,
        actor=world.specification.actor,
        approved_at=world.specification.approved_at,
        execution_evidence=world.specification.execution_evidence,
    )
    world.runtime().save_specification(approved)
    ledger = SQLiteCostLedgerRepository(world.database)
    before = ledger.get(Reference("ledger"))
    request = ExecuteWorkerRequest(
        ExecutionBinding(
            approved.reference,
            Reference("v2-execution"),
            Reference("v2-operation"),
            Reference("v2-deliverable"),
        ),
        world.request.expected_opportunity_revision,
    )
    outcome = replace(world.use_case(), operator=Reference("unapproved")).execute(request)
    assert outcome.reason == WorkerExecutionReason.APPROVAL_DENIED
    assert world.runtime().get_run(Reference("v2-execution")) is None
    assert ledger.get(Reference("ledger")) == before
    assert world.current().submission is None and world.current().verified_revenue.amount == 0


def test_legacy_optional_null_column_is_still_uncovered() -> None:
    from agentmine.application.contracts.qa import bundle_content
    from agentmine.application.qa.checks import deterministic
    from agentmine.domain.qa import QAOutcome

    inspection = load("optional-null-inspection-v1.json", QAInspection)
    findings = deterministic(inspection, bundle_content(inspection.result).text)
    assert any(
        item.code == "REQUIREMENT_NOT_COVERED" and item.outcome == QAOutcome.NEEDS_REVISION
        for item in findings
    )


def v2_result() -> DataResult:
    from agentmine.application.contracts.data import (
        DataPartitionAssessment,
        DataRowReference,
        DataSourceOutcome,
        InputPresence,
        SourceParseStatus,
    )

    old = load("data_result-v1.json", DataResult)
    records = tuple(
        replace(
            row,
            cells=tuple(replace(cell, input_presence=InputPresence.VALUE) for cell in row.cells),
        )
        for row in old.records
    )
    source = records[0]
    rows = tuple(
        DataRowReference(row.source, row.source_digest, row.row, row.row_id) for row in records
    )
    policy = specification().output_policy
    assert policy is not None
    partition = DataPartitionAssessment(
        2,
        policy,
        rows,
        (),
        (
            DataSourceOutcome(
                source.source, source.source_digest, SourceParseStatus.PARSED, len(rows)
            ),
        ),
        (),
        True,
    )
    return replace(old, records=records, partition=partition)


def test_v2_result_and_inspection_roundtrip_but_no_qa_execution() -> None:
    from agentmine.application.contracts.qa import bundle_content

    codec = SnapshotCodec()
    result = v2_result()
    assert codec.loads(codec.dumps(result), DataResult) == result
    old = load("qa_inspection-v1.json", QAInspection)
    criteria = acceptance()
    inspection = replace(
        old,
        plan=specification().plan(old.plan.execution),
        result=result,
        deliverable=replace(old.deliverable, content_reference=bundle_content(result).reference),
        formats=criteria.formats,
        requirements=criteria.requirements,
        partition_acceptance=criteria.partition_acceptance,
    )
    assert codec.loads(codec.dumps(inspection), QAInspection) == inspection
    with pytest.raises(ValueError):
        replace(inspection, partition_acceptance=PartitionAcceptance(2, 1, 1))
    with pytest.raises(ValueError):
        replace(inspection, result=replace(result, partition=None))


def test_v2_result_requires_origin_and_matching_row_membership() -> None:
    result = v2_result()
    assert result.partition is not None
    with pytest.raises(ValueError):
        replace(
            result,
            records=(
                replace(
                    result.records[0],
                    cells=(replace(result.records[0].cells[0], input_presence=None),),
                ),
                *result.records[1:],
            ),
        )
    with pytest.raises(ValueError):
        replace(
            result, partition=replace(result.partition, clean_rows=result.partition.clean_rows[:1])
        )


def test_assessment_rejects_duplicate_membership_and_unknown_sources() -> None:
    result = v2_result()
    assert result.partition is not None
    partition = result.partition
    with pytest.raises(ValueError):
        replace(partition, clean_rows=(partition.clean_rows[0], partition.clean_rows[0]))
    with pytest.raises(ValueError):
        replace(
            partition,
            source_outcomes=(replace(partition.source_outcomes[0], source_digest="0" * 64),),
        )


def test_explicit_v2_missing_fields_are_not_legacy_migrated() -> None:
    codec = SnapshotCodec()
    policy = json.loads(codec.dumps(specification().output_policy))
    del policy["value"]["fields"]["duplicate_policy"]
    with pytest.raises(PortError):
        codec.loads(json.dumps(policy), DataPartitionPolicy)
    result = json.loads(codec.dumps(v2_result()))
    del result["value"]["fields"]["partition"]["fields"]["source_outcomes"]
    with pytest.raises(PortError):
        codec.loads(json.dumps(result), DataResult)


def test_same_execution_changed_thresholds_cannot_replace_plan(tmp_path: Path) -> None:
    from agentmine.infrastructure.sqlite.data import SQLiteDataJournal

    journal = SQLiteDataJournal(SQLiteDatabase(tmp_path / "journal.sqlite3"))
    plan = specification().plan(load("data_plan-v1.json", DataPlan).execution)
    journal.save_plan(plan)
    journal.save_plan(plan)
    with pytest.raises(PortError):
        journal.save_plan(replace(plan, partition_acceptance=PartitionAcceptance(2, 1, 1)))


def test_reading_legacy_sqlite_payload_does_not_rewrite_it(tmp_path: Path) -> None:
    payload = (FIXTURES / "work_specification-v1.json").read_text(encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    database = SQLiteDatabase(tmp_path / "legacy.sqlite3")
    with database.transaction(write=True) as connection:
        connection.execute(
            "INSERT INTO snapshots(kind,id,revision,payload,digest) VALUES(?,?,?,?,?)",
            ("work_specification", "cli-spec", 1, payload, digest),
        )
    repo = SQLiteWorkerRuntimeRepository(database)
    from agentmine.domain.values import Reference

    loaded = repo.get_specification(Reference("cli-spec"))
    assert loaded is not None and loaded.output_policy is None
    with database.transaction() as connection:
        row = connection.execute("SELECT payload,digest,revision FROM snapshots").fetchone()
        assert tuple(row) == (payload, digest, 1)


def test_same_id_different_identifier_policy_conflicts(tmp_path: Path) -> None:
    from agentmine.application.contracts.data import DataColumn

    database = SQLiteDatabase(tmp_path / "identity.sqlite3")
    spec = specification()
    assert spec.output_policy is not None
    changed = replace(
        spec,
        columns=(DataColumn("other", ("other",)),),
        unique_by=("other",),
        output_policy=replace(spec.output_policy, id_column="other"),
    )
    database.immutable("work_specification", spec.reference.value, spec)
    with pytest.raises(PortError):
        database.immutable("work_specification", spec.reference.value, changed)


def test_legacy_acceptance_payload_is_explicitly_v1() -> None:
    old = json.loads((FIXTURES / "work_specification-v1.json").read_text())
    reconstructed = {"version": 1, "value": old["value"]["fields"]["acceptance"]}
    decoded = SnapshotCodec().loads(json.dumps(reconstructed), DataAcceptanceCriteria)
    assert decoded.partition_acceptance is None
