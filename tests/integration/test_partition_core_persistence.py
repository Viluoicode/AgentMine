"""Core-only SQLite evidence; NOT worker execution, QA, export or budget settlement."""

from pathlib import Path

import pytest
from test_data_partition import CASES, plan_for

from agentmine.application.contracts.data import DataResult
from agentmine.application.errors import PortError
from agentmine.application.workers.data_partition import partition
from agentmine.infrastructure.sqlite.data import SQLiteDataJournal
from agentmine.infrastructure.sqlite.database import SQLiteDatabase


def test_core_evidence_roundtrip_and_immutable_retry(tmp_path: Path) -> None:
    plan = plan_for(next(c for c in CASES if c["name"] == "cross_source"))
    records, issues, assessment = partition(plan)
    # No fabricated actual cost: a pure computation does not represent worker settlement.
    result = DataResult(
        plan.execution.reference,
        records,
        issues,
        (),
        None,
        ("partition_artifacts_unavailable",),
        assessment,
    )
    database = SQLiteDatabase(tmp_path / "core.sqlite3")
    journal = SQLiteDataJournal(database)
    journal.save_plan(plan)
    journal.save_result(result)
    reopened = SQLiteDataJournal(SQLiteDatabase(database.path))
    assert reopened.get_result(plan.execution.reference) == result
    reopened.save_plan(plan)
    reopened.save_result(result)
    assert not result.valid
    with database.transaction() as connection:
        assert [
            (r[0], r[1])
            for r in connection.execute(
                "SELECT kind,count(*) FROM snapshots GROUP BY kind ORDER BY kind"
            )
        ] == [("data_plan", 1), ("data_result", 1)]
    # Same-ID altered source bytes cannot silently replace the original plan.
    from dataclasses import replace

    with pytest.raises(PortError):
        reopened.save_plan(
            replace(plan, sources=(replace(plan.sources[0], content="[]"), *plan.sources[1:]))
        )
