"""C1 literal policy/acceptance oracles; no worker/partition/encoder-generated expected values."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from agentmine.application.contracts.data import (
    DataCell,
    DataColumn,
    DataPartitionPolicy,
    DataPlan,
    DataResult,
    DuplicatePolicy,
    InputPresence,
    PartitionAcceptance,
    TextCase,
    ValueKind,
)
from agentmine.application.contracts.qa import (
    ArtifactFormat,
    CoverageKind,
    DataAcceptanceCriteria,
    QARequirement,
    RequiredArtifact,
)
from agentmine.application.contracts.runtime import WorkSpecification
from agentmine.domain.errors import DomainError
from agentmine.domain.values import Reference
from agentmine.infrastructure.snapshots import SnapshotCodec

FIXTURES = Path(__file__).resolve().parents[2] / "contract/fixtures/data_partition"


def load[T](name: str, expected: type[T]) -> T:
    return SnapshotCodec().loads((FIXTURES / name).read_text(encoding="utf-8"), expected)


def acceptance() -> DataAcceptanceCriteria:
    return DataAcceptanceCriteria(
        tuple(
            RequiredArtifact(n, f)
            for n, f in (
                ("clean.csv", ArtifactFormat.CSV),
                ("clean.json", ArtifactFormat.JSON),
                ("rejected.json", ArtifactFormat.JSON),
                ("validation.json", ArtifactFormat.JSON),
            )
        ),
        (QARequirement(Reference("id-present"), "clean.json", CoverageKind.FIELD_PRESENT, "id"),),
        partition_acceptance=PartitionAcceptance(2, 1, 2),
    )


def specification() -> WorkSpecification:
    old = load("work_specification-v1.json", WorkSpecification)
    return replace(
        old,
        columns=(DataColumn("id", ("id",), case=TextCase.UPPER),),
        unique_by=("id",),
        acceptance=acceptance(),
        output_policy=DataPartitionPolicy(2, "id", DuplicatePolicy.REJECT_ALL),
    )


def test_literal_policy_and_threshold_oracle() -> None:
    expected = json.loads((FIXTURES / "independent-oracles.json").read_text())
    spec = specification()
    assert spec.output_policy is not None
    assert spec.output_policy.contract_version == expected["policy"]["contract_version"]
    assert spec.output_policy.id_column == expected["policy"]["id_column"]
    assert spec.output_policy.duplicate_policy.value == expected["policy"]["duplicate_policy"]
    assert spec.acceptance == acceptance()
    with pytest.raises(FrozenInstanceError):
        spec.output_policy.id_column = "other"  # type: ignore[misc]


@pytest.mark.parametrize("version", [1, 3, True, "2", 2.0])
def test_strict_policy_versions(version: object) -> None:
    with pytest.raises(DomainError):
        DataPartitionPolicy(version, "id", DuplicatePolicy.REJECT_ALL)  # type: ignore[arg-type]


@pytest.mark.parametrize("policy", ["REJECT_ALL", "FIRST_WINS", None])
def test_policy_requires_explicit_supported_enum(policy: object) -> None:
    with pytest.raises(DomainError):
        DataPartitionPolicy(2, "id", policy)  # type: ignore[arg-type]


def test_policy_unknown_fields_rejected() -> None:
    with pytest.raises(TypeError):
        DataPartitionPolicy(2, "id", DuplicatePolicy.REJECT_ALL, ignore_errors=True)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "column",
    [
        DataColumn("other", ("id",)),
        DataColumn("id", ("id",), required=False),
        DataColumn("id", ("id",), ValueKind.INTEGER),
        DataColumn("id", ("id",), semantic_reason="Guess identifier"),
    ],
)
def test_invalid_identifier_schema(column: DataColumn) -> None:
    with pytest.raises(DomainError):
        replace(specification(), columns=(column,))


@pytest.mark.parametrize("unique", [(), ("id", "other")])
def test_no_composite_or_missing_unique_by(unique: tuple[str, ...]) -> None:
    with pytest.raises(DomainError):
        replace(
            specification(),
            columns=(DataColumn("id", ("id",)), DataColumn("other", ("other",))),
            unique_by=unique,
        )


@pytest.mark.parametrize(
    "minimum,maximum", [(0, 0), (-1, 0), (1001, 0), (1, -1), (1, 1001), (True, 0), (1, False)]
)
def test_threshold_bounds_and_types(minimum: int, maximum: int) -> None:
    with pytest.raises(DomainError):
        PartitionAcceptance(2, minimum, maximum)


def test_thresholds_required_and_versioned() -> None:
    with pytest.raises(TypeError):
        PartitionAcceptance(2)  # type: ignore[call-arg]
    with pytest.raises(DomainError):
        PartitionAcceptance(1, 1, 0)


def test_policy_acceptance_pair_required() -> None:
    old = load("work_specification-v1.json", WorkSpecification)
    with pytest.raises(DomainError):
        replace(old, output_policy=DataPartitionPolicy(2, "id", DuplicatePolicy.REJECT_ALL))
    with pytest.raises(DomainError):
        replace(specification(), output_policy=None)
    with pytest.raises(DomainError):
        replace(specification(), acceptance=None)


def test_thresholds_cannot_exceed_approved_record_bound() -> None:
    with pytest.raises(DomainError):
        replace(specification(), max_records=1)


def test_plan_preserves_frozen_policy_and_acceptance() -> None:
    spec = specification()
    plan = spec.plan(load("data_plan-v1.json", DataPlan).execution)
    assert plan.output_policy == spec.output_policy
    assert plan.partition_acceptance == PartitionAcceptance(2, 1, 2)
    with pytest.raises(DomainError):
        replace(plan, partition_acceptance=None)
    with pytest.raises(DomainError):
        replace(plan, output_policy=None)


def test_legacy_construction_and_valid_unchanged() -> None:
    spec = load("work_specification-v1.json", WorkSpecification)
    plan = load("data_plan-v1.json", DataPlan)
    cell = load("data_cell-v1.json", DataCell)
    result = load("data_result-v1.json", DataResult)
    assert spec.output_policy is None and plan.output_policy is None
    assert plan.partition_acceptance is None and result.partition is None
    assert cell.input_presence is None and result.valid
    assert len({InputPresence.MISSING, InputPresence.NULL}) == 2


def test_field_present_requires_opt_in() -> None:
    with pytest.raises(DomainError):
        replace(acceptance(), partition_acceptance=None)


def test_explicit_input_presence_and_assessment_are_typed() -> None:
    from agentmine.application.contracts.data import (
        DataPartitionAssessment,
        DataRowReference,
        DataSourceOutcome,
        SourceParseStatus,
    )

    source = load("data_plan-v1.json", DataPlan).sources[0]
    row = DataRowReference(source.reference, source.digest, 1, "row-1")
    assessment = DataPartitionAssessment(
        2,
        DataPartitionPolicy(2, "id", DuplicatePolicy.REJECT_ALL),
        (row,),
        (),
        (DataSourceOutcome(source.reference, source.digest, SourceParseStatus.PARSED, 1),),
        (),
        True,
    )
    assert assessment.clean_rows == (row,) and assessment.rejected_rows == ()
    with pytest.raises(DomainError):
        replace(assessment, contract_version=3)
    with pytest.raises(DomainError):
        replace(row, row=True)
    with pytest.raises(DomainError):
        replace(source, content=123)  # type: ignore[arg-type]
    cell = DataCell("brand", None, ("brand",), input_presence=InputPresence.NULL)
    assert cell.input_presence == InputPresence.NULL
    with pytest.raises(DomainError):
        replace(cell, input_presence="NULL")  # type: ignore[arg-type]


def test_legacy_issues_still_mean_invalid() -> None:
    from agentmine.application.contracts.data import DataIssue, DataIssueCode

    result = load("data_result-v1.json", DataResult)
    assert not replace(result, issues=(DataIssue(DataIssueCode.INVALID_VALUE),)).valid
