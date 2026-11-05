"""C2 independent literal oracles; no runtime, providers or generated expected values."""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import TypedDict, cast

import pytest
from test_partition_contracts import load

from agentmine.application.contracts.data import (
    DataColumn,
    DataFormat,
    DataPartitionPolicy,
    DataPlan,
    DataResult,
    DataSource,
    DuplicatePolicy,
    PartitionAcceptance,
    TextCase,
    ValueKind,
)
from agentmine.application.workers.data_artifacts import artifacts
from agentmine.application.workers.data_partition import duplicate_group_payload, partition
from agentmine.application.workers.data_transform import transform, validate
from agentmine.domain.errors import DomainError
from agentmine.domain.values import Reference


class SourceFixture(TypedDict):
    reference: str
    content: str
    format: str
    sha256: str


class GroupFixture(TypedDict):
    canonical_id: str
    members: list[int]
    canonical_json: str
    group_id: str


class ExpectedFixture(TypedDict):
    records: list[list[object]]
    issues: list[list[object]]
    clean: list[int]
    rejected: list[int]
    groups: list[GroupFixture]
    evidence_complete: bool


class CaseFixture(TypedDict):
    name: str
    sources: list[SourceFixture]
    min_records: int
    max_records: int
    expected: ExpectedFixture


FIXTURES = Path(__file__).resolve().parents[2] / "contract/fixtures/data_partition_c2"
CASES = cast(list[CaseFixture], json.loads((FIXTURES / "oracles.json").read_text()))


def plan_for(case: CaseFixture) -> DataPlan:
    original = load("data_plan-v1.json", DataPlan)
    return replace(
        original,
        sources=tuple(
            DataSource(
                Reference(source["reference"]),
                "fixture:" + source["reference"],
                original.execution.started_at,
                DataFormat(source["format"]),
                source["content"],
            )
            for source in case["sources"]
        ),
        columns=(
            DataColumn("id", ("id",), case=TextCase.UPPER, max_length=4),
            DataColumn("title", ("title",), required=False, case=TextCase.LOWER),
            DataColumn("qty", ("qty",), ValueKind.INTEGER, minimum=Decimal(0)),
            DataColumn("price", ("price",), ValueKind.DECIMAL, required=False, minimum=Decimal(0)),
        ),
        unique_by=("id",),
        min_records=case["min_records"],
        max_records=case["max_records"],
        output_policy=DataPartitionPolicy(2, "id", DuplicatePolicy.REJECT_ALL),
        partition_acceptance=PartitionAcceptance(2, 1, 1000),
    )


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_exact_independent_oracle(case: CaseFixture) -> None:
    plan = plan_for(case)
    records, issues, assessment = partition(plan)
    expected = case["expected"]
    actual = [
        [
            r.source.value,
            r.row,
            [c.value for c in r.cells],
            [None if c.input_presence is None else c.input_presence.value for c in r.cells],
        ]
        for r in records
    ]
    assert actual == expected["records"]
    assert [
        [i.code.value, None if i.source is None else i.source.value, i.row, i.column]
        for i in issues
    ] == expected["issues"]
    assert [row.row_id for row in assessment.clean_rows] == [
        "row-" + str(i) for i in expected["clean"]
    ]
    assert [item.row.row_id for item in assessment.rejected_rows] == [
        "row-" + str(i) for i in expected["rejected"]
    ]
    assert assessment.evidence_complete == expected["evidence_complete"]
    assert [
        (g.canonical_id, g.reference.value, [m.row_id for m in g.members])
        for g in assessment.duplicate_groups
    ] == [
        (g["canonical_id"], g["group_id"], ["row-" + str(i) for i in g["members"]])
        for g in expected["groups"]
    ]
    assert len(records) == len(assessment.clean_rows) + len(assessment.rejected_rows)
    assert len({(r.source, r.source_digest, r.row) for r in records}) == len(records)
    for record in records:
        source = next(
            source for source in case["sources"] if source["reference"] == record.source.value
        )
        assert record.source_digest == source["sha256"]
        assert record.locator == "fixture:" + record.source.value
        assert record.collected_at == plan.execution.started_at
        assert tuple(c.source_path for c in record.cells) == tuple(c.path for c in plan.columns)
    for rejected in assessment.rejected_rows:
        assert rejected.reasons == tuple(
            i for i in issues if i.source == rejected.row.source and i.row == rejected.row.row
        )
        assert rejected.reasons
    for outcome in assessment.source_outcomes:
        malformed = any(
            i[0] == "malformed_source" and i[1] == outcome.source.value for i in expected["issues"]
        )
        assert outcome.parsed_count == (
            None if malformed else sum(r[0] == outcome.source.value for r in expected["records"])
        )
        assert outcome.status.value == ("MALFORMED" if malformed else "PARSED")
    assert partition(plan) == (records, issues, assessment)
    assert plan == plan_for(case)


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c["expected"]["groups"]],
    ids=[c["name"] for c in CASES if c["expected"]["groups"]],
)
def test_golden_canonical_payload_bytes(case: CaseFixture) -> None:
    plan = plan_for(case)
    for golden in case["expected"]["groups"]:
        assert duplicate_group_payload(plan, golden["canonical_id"]) == golden[
            "canonical_json"
        ].encode("utf-8")


def test_v1_artifact_bytes_and_presence_are_unchanged() -> None:
    plan = load("data_plan-v1.json", DataPlan)
    expected = load("data_result-v1.json", DataResult)
    records, issues = transform(plan)
    issues += validate(plan, records)
    assert records == expected.records and issues == expected.issues
    assert artifacts(plan, records, issues) == expected.artifacts
    assert all(cell.input_presence is None for row in records for cell in row.cells)
    with pytest.raises(DomainError):
        partition(plan)


def test_v1_duplicate_policy_only_flags_later_row() -> None:
    plan = replace(
        plan_for(next(c for c in CASES if c["name"] == "two_duplicates")),
        output_policy=None,
        partition_acceptance=None,
    )
    records, issues = transform(plan)
    issues += validate(plan, records)
    assert [(i.code.value, i.row, i.column) for i in issues] == [("duplicate", 2, None)]
    assert len(records) == 3 and all(c.input_presence is None for r in records for c in r.cells)
    assert [a.name for a in artifacts(plan, records, issues)] == ["validation.json"]


def test_input_limit_fails_explicitly_without_truncated_result() -> None:
    plan = plan_for(CASES[0])
    source = replace(plan.sources[0], content=json.dumps([{"id": "A1", "qty": "1"}] * 1001))
    plan = replace(plan, sources=(source,))
    with pytest.raises(DomainError) as error:
        partition(plan)
    assert error.value.field == "partition_record_limit"
    assert len(json.loads(plan.sources[0].content)) == 1001


def test_approved_source_order_is_part_of_group_identity() -> None:
    plan = plan_for(next(c for c in CASES if c["name"] == "cross_source"))
    a = partition(plan)[2]
    b = partition(replace(plan, sources=tuple(reversed(plan.sources))))[2]
    assert a.duplicate_groups[0].reference != b.duplicate_groups[0].reference


def test_legacy_null_keys_are_not_changed_by_v2_policy() -> None:
    plan = replace(
        plan_for(next(c for c in CASES if c["name"] == "missing_null_blank_ids")),
        output_policy=None,
        partition_acceptance=None,
    )
    records, issues = transform(plan)
    issues += validate(plan, records)
    assert [i.row for i in issues if i.code.value == "duplicate"] == [2, 3]


def test_direct_worker_cannot_render_v2_with_legacy_artifacts() -> None:
    from data_fakes import MemoryDataJournal, make_data_world

    from agentmine.application.workers.data import DataWorker

    world = make_data_world(scout=True)
    plan = plan_for(CASES[0])
    plan = replace(
        plan,
        execution=world.plan.execution,
        sources=tuple(replace(source, collected_at=world.clock.now()) for source in plan.sources),
    )
    journal = MemoryDataJournal()
    worker = DataWorker(world.worker.budget, journal, llm=None)
    # C3 replaces the temporary UNSUPPORTED guard only with a complete v2 worker path.
    result = worker.execute(plan)
    assert result.partition is not None
    assert [item.name for item in result.artifacts] == [
        "clean.csv",
        "clean.json",
        "rejected.json",
        "validation.json",
    ]
    assert journal.get_result(plan.execution.reference) == result
    assert result.cost is not None and result.cost.actual_cost.amount == 0
