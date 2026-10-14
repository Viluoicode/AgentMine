import csv
import io
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from data_fakes import MemoryDataJournal, make_data_world, usd, with_content

from agentmine.application.contracts.data import (
    Comparison,
    DataColumn,
    DataFormat,
    DataIssueCode,
    DataPlan,
    DataResult,
    LookupEntry,
    RowConstraint,
    TextCase,
    ValueKind,
)
from agentmine.application.contracts.records import Versioned
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.ports.workers import Worker
from agentmine.domain.budget import OperatingMode
from agentmine.domain.errors import DomainError
from agentmine.domain.values import Reference
from agentmine.domain.work import TaskType


def test_deterministic_collection_extraction_normalization_provenance() -> None:
    world = make_data_world()
    worker: Worker[DataPlan, DataResult] = world.worker
    result = worker.execute(world.plan)
    assert result.valid and not world.llm.calls
    assert [cell.value for cell in result.records[0].cells] == ["1", "ada", "2"]
    assert result.records[0].source_digest == world.plan.sources[0].digest
    assert result.records[0].row == 1
    assert result.cost is not None and result.cost.actual_cost == usd("0")
    items = {artifact.name: artifact.content for artifact in result.artifacts}
    assert set(items) == {"data.csv", "data.json", "validation.json"}
    data = json.loads(items["data.json"])
    assert data[0]["_provenance"]["fields"]["name"]["path"] == ["profile", "name"]
    csv_rows = list(csv.DictReader(io.StringIO(items["data.csv"])))
    assert csv_rows[0]["name"] == "ada"
    assert json.loads(csv_rows[0]["_provenance"])["source"] == "input"
    revision = world.ledger.snapshots[Reference("ledger")].revision
    assert worker.execute(world.plan) == result
    assert world.ledger.snapshots[Reference("ledger")].revision == revision


def test_free_work_runs_in_scout_only_without_provider() -> None:
    world = make_data_world(scout=True)
    assert replace(world.worker, llm=None).execute(world.plan).valid
    assert not world.llm.calls


def test_csv_collection_and_lookup_categorization_enrichment() -> None:
    world = make_data_world()
    columns = (
        DataColumn("id", ("id",), ValueKind.INTEGER),
        DataColumn(
            "category",
            ("code",),
            case=TextCase.LOWER,
            lookup=(LookupEntry("r", "research"), LookupEntry("d", "data")),
            lookup_evidence=Reference("category-policy"),
        ),
        DataColumn(
            "region",
            ("country",),
            case=TextCase.UPPER,
            lookup=(LookupEntry("VN", "Asia"),),
            lookup_evidence=Reference("region-table"),
        ),
    )
    plan = replace(
        with_content(world.plan, "id,code,country\n1,R,vn\n2,D,VN\n", DataFormat.CSV),
        columns=columns,
    )
    result = world.worker.execute(plan)
    assert result.valid
    assert [cell.value for cell in result.records[0].cells] == ["1", "research", "Asia"]
    assert result.records[0].cells[2].lookup_evidence == Reference("region-table")
    assert not world.llm.calls


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ('[{"id":"1","count":"2"}]', DataIssueCode.MISSING_COLUMN),
        ('[{"id":"1","profile":{"name":" "},"count":"2"}]', DataIssueCode.MISSING_VALUE),
        ('[{"id":"1","profile":{"name":"A"},"count":"bad"}]', DataIssueCode.INVALID_VALUE),
        ('[{"id":"1","profile":{"name":"A"},"count":"11"}]', DataIssueCode.INVALID_VALUE),
        (
            '[{"id":"1","profile":{"name":"A"},"count":"2"},{"id":"01","profile":{"name":"B"},"count":"3"}]',
            DataIssueCode.DUPLICATE,
        ),
        ("[]", DataIssueCode.RECORD_COUNT),
        ('{"id":1}', DataIssueCode.MALFORMED_SOURCE),
        ('[{"id":"1","id":"2"}]', DataIssueCode.MALFORMED_SOURCE),
        ('[{"count":NaN}]', DataIssueCode.MALFORMED_SOURCE),
    ],
)
def test_validation_failures_never_export_success_or_call_ai(
    content: str, code: DataIssueCode
) -> None:
    world = make_data_world(semantic=True)
    result = world.worker.execute(with_content(world.plan, content))
    assert not result.valid and code in {issue.code for issue in result.issues}
    assert [artifact.name for artifact in result.artifacts] == ["validation.json"]
    assert not world.llm.calls
    assert result.cost is not None and result.cost.actual_cost == usd("0")


@pytest.mark.parametrize("content", ["id,id\n1,2", "id,name\n1", "id,name\n1,A,extra", ""])
def test_malformed_csv(content: str) -> None:
    world = make_data_world()
    result = world.worker.execute(with_content(world.plan, content, DataFormat.CSV))
    assert DataIssueCode.MALFORMED_SOURCE in {issue.code for issue in result.issues}


def test_empty_csv_still_validates_required_columns() -> None:
    world = make_data_world()
    plan = replace(with_content(world.plan, "wrong\n", DataFormat.CSV), min_records=0)
    assert DataIssueCode.MISSING_COLUMN in {
        issue.code for issue in world.worker.execute(plan).issues
    }


def test_semantics_only_designated_fields_and_measured_cost() -> None:
    world = make_data_world(semantic=True)
    result = world.worker.execute(world.plan)
    assert result.valid and len(world.llm.calls) == 1
    assert [cell.value for cell in result.records[0].cells] == ["1", "ada", "2", "research"]
    sent = json.loads(world.llm.calls[0].inputs[0].text)
    assert set(sent["fields"]) == {"category"}
    assert result.records[0].cells[-1].semantic_evidence == Reference("model-evidence")
    assert "semantic_values_unverified" in result.warnings
    assert result.cost is not None and result.cost.actual_cost == usd("0.25")
    assert result.cost.estimated_cost == usd("1")
    assert world.worker.execute(world.plan) == result
    assert len(world.llm.calls) == 1


@pytest.mark.parametrize(
    "rows",
    [
        [{"row_id": "row-1", "category": "research"}],
        [{"row_id": "row-1", "category": "research"}, {"row_id": "row-1", "category": "data"}],
        [{"row_id": "new", "category": "research"}, {"row_id": "row-2", "category": "data"}],
        [
            {"row_id": "row-1", "category": "research", "id": "99"},
            {"row_id": "row-2", "category": "data"},
        ],
        [{"row_id": "row-1", "category": 12}, {"row_id": "row-2", "category": "data"}],
    ],
)
def test_model_cannot_change_rows_types_or_deterministic_columns(
    rows: list[dict[str, object]],
) -> None:
    world = make_data_world(semantic=True)
    world.llm.payload = json.dumps({"plan": ["Classify"], "rows": rows, "evidence": []})
    with pytest.raises(PortError) as error:
        world.worker.execute(world.plan)
    assert error.value.code == PortErrorCode.INVALID_RESPONSE
    assert len(world.ledger.snapshots[Reference("ledger")].value.records) == 1
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    assert len(world.llm.calls) == 1


def test_semantic_value_constraints_still_apply() -> None:
    world = make_data_world(semantic=True)
    world.llm.payload = world.llm.payload.replace("research", "unsupported")
    result = world.worker.execute(world.plan)
    assert not result.valid
    assert DataIssueCode.INVALID_VALUE in {issue.code for issue in result.issues}


def test_cross_field_constraint_and_record_limit() -> None:
    world = make_data_world()
    plan = replace(
        world.plan,
        constraints=(RowConstraint("count", Comparison.LESS_OR_EQUAL, "id"),),
        max_records=1,
    )
    result = world.worker.execute(plan)
    assert {DataIssueCode.CONSTRAINT, DataIssueCode.RECORD_COUNT} <= {
        issue.code for issue in result.issues
    }


def test_budget_denial_blocks_semantic_execution() -> None:
    world = make_data_world(semantic=True)
    snapshot = world.ledger.snapshots[Reference("ledger")]
    world.ledger.snapshots[Reference("ledger")] = Versioned(
        snapshot.value.with_requested_mode(OperatingMode.SCOUT_ONLY), snapshot.revision + 1
    )
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    assert not world.llm.calls


def test_expired_plan_blocks_work() -> None:
    world = make_data_world()
    world.clock.instant += timedelta(days=1)
    with pytest.raises(ApplicationError):
        world.worker.execute(world.plan)


def test_unknown_cost_and_overrun() -> None:
    for amount, warning in ((None, "actual_ai_cost_unknown"), (usd("2"), "cost_estimate_exceeded")):
        world = make_data_world(semantic=True)
        world.llm.actual = amount
        result = world.worker.execute(world.plan)
        assert warning in result.warnings
        if amount is None:
            assert (
                result.cost is None
                and world.ledger.snapshots[Reference("ledger")].value.outstanding
            )


def test_cost_recording_failure_recovers_without_model_retry() -> None:
    world = make_data_world(semantic=True)
    world.llm.break_ledger = world.ledger
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    world.ledger.fail_commit = False
    assert world.worker.execute(world.plan).valid
    assert len(world.llm.calls) == 1


def test_result_write_failure_reuses_saved_response() -> None:
    journal = MemoryDataJournal(fail_result=True)
    world = make_data_world(semantic=True, journal=journal)
    with pytest.raises(PortError):
        world.worker.execute(world.plan)
    journal.fail_result = False
    assert world.worker.execute(world.plan).valid
    assert len(world.llm.calls) == 1


@pytest.mark.parametrize("failure", ["provider", "checkpoint"])
def test_unknown_dispatch_never_automatically_retries(failure: str) -> None:
    journal = MemoryDataJournal(fail_response=failure == "checkpoint")
    world = make_data_world(semantic=True, journal=journal)
    world.llm.fail = failure == "provider"
    for _ in range(2):
        with pytest.raises(PortError) as error:
            world.worker.execute(world.plan)
        assert "PRIVATE" not in str(error.value)
    assert len(world.llm.calls) == 1


def test_plan_invariants() -> None:
    world = make_data_world()
    with pytest.raises(DomainError):
        replace(
            world.plan,
            execution=replace(
                world.plan.execution,
                task=replace(world.plan.execution.task, task_type=TaskType.RESEARCH),
            ),
        )
    with pytest.raises(DomainError):
        replace(world.plan, columns=world.plan.columns * 2)
    with pytest.raises(DomainError):
        DataColumn("region", ("country",), lookup=(LookupEntry("VN", "Asia"),))
    with pytest.raises(DomainError):
        DataColumn("x", ("x",), minimum=Decimal(0))


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        (ValueKind.DECIMAL, "0012.3400", "12.34"),
        (ValueKind.DECIMAL, "-0.00", "0"),
        (ValueKind.INTEGER, "0002", "2"),
        (ValueKind.BOOLEAN, "TRUE", "true"),
        (ValueKind.DATE, "2024-02-29", "2024-02-29"),
    ],
)
def test_typed_normalization(kind: ValueKind, raw: str, expected: str) -> None:
    world = make_data_world()
    plan = replace(
        with_content(world.plan, json.dumps([{"value": raw}])),
        columns=(DataColumn("value", ("value",), kind),),
        unique_by=(),
    )
    result = world.worker.execute(plan)
    assert result.valid and result.records[0].cells[0].value == expected


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        (ValueKind.DECIMAL, "NaN"),
        (ValueKind.DECIMAL, "1e999999"),
        (ValueKind.INTEGER, "1.5"),
        (ValueKind.BOOLEAN, "yes"),
        (ValueKind.DATE, "2023-02-29"),
        (ValueKind.TEXT, "\ud800"),
    ],
)
def test_invalid_typed_values(kind: ValueKind, raw: str) -> None:
    world = make_data_world()
    plan = replace(
        with_content(world.plan, json.dumps([{"value": raw}])),
        columns=(DataColumn("value", ("value",), kind),),
        unique_by=(),
    )
    result = world.worker.execute(plan)
    assert DataIssueCode.INVALID_VALUE in {issue.code for issue in result.issues}


def test_multiple_sources_and_duplicate_values_keep_all_rows() -> None:
    world = make_data_world()
    source = replace(world.plan.sources[0], reference=Reference("second"), locator="fixture:second")
    result = world.worker.execute(replace(world.plan, sources=(*world.plan.sources, source)))
    assert len(result.records) == 4 and not result.valid
    assert result.records[2].source == Reference("second")
    assert DataIssueCode.DUPLICATE in {issue.code for issue in result.issues}


def test_unknown_lookup_value_is_invalid_not_guessed() -> None:
    world = make_data_world()
    column = DataColumn(
        "region", ("code",), lookup=(LookupEntry("VN", "Asia"),), lookup_evidence=Reference("table")
    )
    plan = replace(
        with_content(world.plan, '[{"code":"unknown"}]'), columns=(column,), unique_by=()
    )
    assert not world.worker.execute(plan).valid


def test_csv_formula_safety_json_preserves_original() -> None:
    world = make_data_world()
    plan = replace(
        with_content(world.plan, json.dumps([{"value": "=1+1"}])),
        columns=(DataColumn("value", ("value",)),),
        unique_by=(),
    )
    result = world.worker.execute(plan)
    items = {artifact.name: artifact.content for artifact in result.artifacts}
    assert json.loads(items["data.json"])[0]["value"] == "=1+1"
    assert list(csv.DictReader(io.StringIO(items["data.csv"])))[0]["value"] == "'=1+1"


def test_optional_missing_semantic_fields_do_not_call_model() -> None:
    world = make_data_world(semantic=True)
    column = DataColumn(
        "label", ("absent",), required=False, semantic_reason="Interpret supplied text"
    )
    plan = replace(world.plan, columns=(*world.plan.columns[:3], column))
    result = world.worker.execute(plan)
    assert result.valid and not world.llm.calls
    assert result.records[0].cells[-1].value is None


def test_oversized_collection_is_not_silently_truncated() -> None:
    world = make_data_world()
    content = json.dumps(
        [{"id": str(index), "profile": {"name": "A"}, "count": "1"} for index in range(1001)]
    )
    result = world.worker.execute(with_content(world.plan, content))
    assert not result.valid and DataIssueCode.RECORD_COUNT in {
        issue.code for issue in result.issues
    }
    assert [artifact.name for artifact in result.artifacts] == ["validation.json"]


def test_expiration_during_processing_prevents_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentmine.application.contracts.data import DataIssue, DataRecord
    from agentmine.application.workers.data_transform import transform

    world = make_data_world(semantic=True)

    def slow_transform(plan: DataPlan) -> tuple[tuple[DataRecord, ...], tuple[DataIssue, ...]]:
        world.clock.instant += timedelta(days=1)
        return transform(plan)

    monkeypatch.setattr("agentmine.application.workers.data.transform", slow_transform)
    with pytest.raises(ApplicationError):
        world.worker.execute(world.plan)
    assert not world.llm.calls
