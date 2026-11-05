"""C3 real isolated worker, literal artifact goldens and crash-safe SQLite protocols."""

import csv
import hashlib
import io
import json
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from partition_artifact_fakes import CASES, FIXTURES, ArtifactCase, world

from agentmine.application.budget_manager import BudgetManager
from agentmine.application.contracts.data import DataResult
from agentmine.application.contracts.qa import bundle_content
from agentmine.application.errors import ApplicationError, PortError, PortErrorCode
from agentmine.application.workers.data_partition import partition
from agentmine.domain.budget import BudgetAuthorization, OperatingMode
from agentmine.domain.money import Money
from agentmine.domain.spending import CostRecord
from agentmine.domain.values import Reference
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase
from agentmine.infrastructure.sqlite.ledger import SQLiteCostLedgerRepository


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_exact_worker_artifact_oracles(tmp_path: Path, case: ArtifactCase) -> None:
    w = world(tmp_path, case)
    result = w.worker().execute(w.plan)
    assert result.partition is not None
    assert [a.name for a in result.artifacts] == case["inventory"]
    assert result.valid == (not case["expected"]["issues"])
    for artifact in result.artifacts:
        assert (
            artifact.content.encode("utf-8")
            == (FIXTURES / case["name"] / artifact.name).read_bytes()
        )
        assert artifact.media_type == (
            "text/csv" if artifact.name.endswith(".csv") else "application/json"
        )
        if artifact.name.endswith(".json"):
            json.loads(artifact.content)
    report = json.loads(next(a.content for a in result.artifacts if a.name == "validation.json"))
    assert report["evidence_complete"] == case["expected"]["evidence_complete"]
    assert "client_acceptance" not in report
    assert report["counts"]["parsed"] == len(result.records)
    assert [[c.value for c in r.cells] for r in result.records] == [
        r[2] for r in case["expected"]["records"]
    ]
    snapshot = w.budget.ledger.get(Reference("ledger"))
    assert snapshot is not None
    assert snapshot.value.requested_mode == OperatingMode.SCOUT_ONLY
    assert (
        snapshot.value.policy.monthly_ai_budget.amount
        == snapshot.value.policy.daily_ai_budget.amount
        == 0
    )
    assert len(snapshot.value.records) == 1 and snapshot.value.records[0].actual_cost.amount == 0
    assert "infrastructure_cost_not_measured" in result.warnings
    assert SQLiteDataJournal(w.database).get_result(w.plan.execution.reference) == result


def test_fixture_manifest_not_regenerated_by_worker() -> None:
    for name, digest in json.loads((FIXTURES / "sha256.json").read_text()).items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest


def test_csv_formula_escaping_and_numeric_strings(tmp_path: Path) -> None:
    w = world(tmp_path, next(c for c in CASES if c["name"] == "formula_and_quoting"))
    result = w.worker().execute(w.plan)
    artifacts = {a.name: a.content for a in result.artifacts}
    rows = list(csv.DictReader(io.StringIO(artifacts["clean.csv"], newline="")))
    assert [r["title"] for r in rows][:4] == ["'=cmd()", "'+cmd", "'-x", "'@x"]
    assert [r["title"] for r in rows][4] == 'line,\n"quoted"'
    parsed = json.loads(artifacts["clean.json"])
    assert parsed[0]["title"] == "=cmd()" and parsed[0]["qty"] == "1"
    assert list(parsed[0]) == sorted(parsed[0])


def test_restart_replay_reuses_original_result_and_cost(tmp_path: Path) -> None:
    w = world(tmp_path, CASES[3])
    result = w.worker().execute(w.plan)
    before = w.budget.ledger.get(Reference("ledger"))
    w.clock.instant += timedelta(days=3)
    w.database = SQLiteDatabase(w.database.path)
    w.budget = replace(w.budget, ledger=SQLiteCostLedgerRepository(w.database))
    with patch(
        "agentmine.application.workers.data.partition",
        side_effect=AssertionError("no new computation"),
    ):
        replay = w.worker().execute(w.plan)
    assert replay == result and w.budget.ledger.get(Reference("ledger")) == before
    assert bundle_content(replay) == bundle_content(result)


@pytest.mark.parametrize(
    "stage", ["before_result", "after_result", "before_cost", "after_cost", "render"]
)
def test_failure_and_restart_preserve_result_before_cost(tmp_path: Path, stage: str) -> None:
    w = world(tmp_path, CASES[3])
    journal = SQLiteDataJournal(w.database)
    original_save = SQLiteDataJournal.save_result
    original_record = BudgetManager.record

    def save(self: SQLiteDataJournal, result: DataResult) -> None:
        if stage == "before_result":
            raise PortError(PortErrorCode.UNAVAILABLE, "test", "before result")
        original_save(self, result)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "test", "after result")

    def record(
        self: BudgetManager, auth: BudgetAuthorization, actual: Money, at: datetime
    ) -> CostRecord:
        assert journal.get_result(w.plan.execution.reference) is not None
        if stage == "after_cost":
            original_record(self, auth, actual, at)
        raise PortError(PortErrorCode.OUTCOME_UNKNOWN, "test", "cost acknowledgement")

    target: AbstractContextManager[object]
    if stage in ("before_result", "after_result"):
        target = patch.object(SQLiteDataJournal, "save_result", save)
    elif stage in ("before_cost", "after_cost"):
        target = patch.object(BudgetManager, "record", record)
    else:
        target = patch(
            "agentmine.application.workers.data.render_partition_artifacts",
            side_effect=PortError(PortErrorCode.UNAVAILABLE, "test", "render"),
        )
    with target, pytest.raises(PortError):
        w.worker().execute(w.plan)
    before = w.budget.ledger.get(Reference("ledger"))
    assert before is not None
    assert len(before.value.records) == int(stage == "after_cost")
    retained = journal.get_result(w.plan.execution.reference)
    assert (retained is not None) == (stage in ("after_result", "before_cost", "after_cost"))
    w.database = SQLiteDatabase(w.database.path)
    w.budget = replace(w.budget, ledger=SQLiteCostLedgerRepository(w.database))
    recovered = w.worker().execute(w.plan)
    assert recovered.partition is not None
    after = w.budget.ledger.get(Reference("ledger"))
    assert after is not None and len(after.value.records) == 1
    if retained is not None:
        assert recovered == retained


@pytest.mark.parametrize("changed", ["threshold", "policy", "source"])
def test_same_id_changes_are_conflicts(tmp_path: Path, changed: str) -> None:
    w = world(tmp_path, CASES[0])
    result = w.worker().execute(w.plan)
    before = w.budget.ledger.get(Reference("ledger"))
    if changed == "threshold":
        assert w.plan.partition_acceptance is not None
        plan = replace(
            w.plan,
            partition_acceptance=replace(w.plan.partition_acceptance, max_rejected_records=2),
        )
    elif changed == "source":
        plan = replace(w.plan, sources=(replace(w.plan.sources[0], content="[]"),))
    else:
        assert w.plan.output_policy is not None
        plan = replace(
            w.plan,
            columns=(replace(w.plan.columns[0], name="sku"), *w.plan.columns[1:]),
            unique_by=("sku",),
            output_policy=replace(w.plan.output_policy, id_column="sku"),
        )
    with pytest.raises(PortError):
        w.worker().execute(plan)
    assert SQLiteDataJournal(w.database).get_result(w.plan.execution.reference) == result
    assert w.budget.ledger.get(Reference("ledger")) == before


def test_unknown_core_only_cost_is_never_converted_to_zero(tmp_path: Path) -> None:
    w = world(tmp_path, CASES[0])
    records, issues, assessment = partition(w.plan)
    SQLiteDataJournal(w.database).save_plan(w.plan)
    SQLiteDataJournal(w.database).save_result(
        DataResult(w.plan.execution.reference, records, issues, (), None, (), assessment)
    )
    before = w.budget.ledger.get(Reference("ledger"))
    with pytest.raises(PortError):
        w.worker().execute(w.plan)
    assert w.budget.ledger.get(Reference("ledger")) == before


def test_unapproved_or_expired_work_stays_blocked(tmp_path: Path) -> None:
    w = world(tmp_path, CASES[0])
    w.clock.instant += timedelta(days=3)
    with pytest.raises(ApplicationError):
        w.worker().execute(w.plan)
    assert SQLiteDataJournal(w.database).get_result(w.plan.execution.reference) is None
    snapshot = w.budget.ledger.get(Reference("ledger"))
    assert snapshot is not None and snapshot.value.records == ()


def test_missing_authorization_never_creates_result_or_cost(tmp_path: Path) -> None:
    w = world(tmp_path, CASES[0])
    assert w.plan.partition_acceptance is not None
    # A foreign operation authorization is not in this authoritative ledger.
    request = w.plan.execution.authorization.request
    foreign = replace(
        w.plan.execution.authorization,
        request=replace(
            request, context=replace(request.context, operation_reference=Reference("foreign"))
        ),
    )
    plan = replace(w.plan, execution=replace(w.plan.execution, authorization=foreign))
    before = w.budget.ledger.get(Reference("ledger"))
    with pytest.raises(PortError):
        w.worker().execute(plan)
    assert SQLiteDataJournal(w.database).get_result(plan.execution.reference) is None
    assert w.budget.ledger.get(Reference("ledger")) == before


def test_corrupt_cached_artifact_is_not_repaired_or_charged(tmp_path: Path) -> None:
    w = world(tmp_path, CASES[0])
    result = w.worker().execute(w.plan)
    # Test-only misbehaving journal return, never mutate an authoritative production row.
    bad = replace(
        result, artifacts=(replace(result.artifacts[0], content="tampered"), *result.artifacts[1:])
    )
    before = w.budget.ledger.get(Reference("ledger"))
    with patch.object(SQLiteDataJournal, "get_result", return_value=bad), pytest.raises(PortError):
        w.worker().execute(w.plan)
    assert w.budget.ledger.get(Reference("ledger")) == before
    assert SQLiteDataJournal(w.database).get_result(w.plan.execution.reference) == result
