"""Canonical v2 artifact projection; no QA, acceptance, external I/O or cost authority."""

import csv
import io
import json

from agentmine.application.contracts.data import (
    DataArtifact,
    DataIssue,
    DataIssueCode,
    DataPartitionAssessment,
    DataPlan,
    DataRecord,
    DataResult,
    DataRowReference,
    invalid,
)


def _json(value: object, *, compact: bool = False) -> str:
    if compact:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(",", ":")
        )
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, indent=2)


def _row(row: DataRowReference) -> dict[str, object]:
    return {
        "row_id": row.row_id,
        "source": row.source.value,
        "sha256": row.source_digest,
        "source_row": row.row,
    }


def _provenance(record: DataRecord) -> dict[str, object]:
    return {
        "row_id": record.row_id,
        "source": record.source.value,
        "locator": record.locator,
        "collected_at": record.collected_at.isoformat(),
        "sha256": record.source_digest,
        "source_row": record.row,
        "source_verification": "caller_supplied_unverified",
        "fields": {
            cell.name: {
                "path": cell.source_path,
                "lookup_evidence": None
                if cell.lookup_evidence is None
                else cell.lookup_evidence.value,
                "semantic_evidence": None,
                "semantic_unverified": False,
                "input_presence": None
                if cell.input_presence is None
                else cell.input_presence.value,
            }
            for cell in record.cells
        },
    }


def render_partition_artifacts(
    plan: DataPlan,
    records: tuple[DataRecord, ...],
    issues: tuple[DataIssue, ...],
    assessment: DataPartitionAssessment,
) -> tuple[DataArtifact, ...]:
    policy = plan.output_policy
    if policy is None or assessment.policy != policy:
        raise invalid("artifact_policy")
    # Reuse existing structural membership validation; this transient object is never persisted.
    DataResult(plan.execution.reference, records, issues, (), None, (), assessment)
    sources = {source.reference: source for source in plan.sources}
    if tuple((o.source, o.source_digest) for o in assessment.source_outcomes) != tuple(
        (source.reference, source.digest) for source in plan.sources
    ):
        raise invalid("artifact_sources")
    for record in records:
        source = sources.get(record.source)
        if (
            source is None
            or (record.locator, record.collected_at, record.source_digest)
            != (source.locator, source.collected_at, source.digest)
            or len(record.cells) != len(plan.columns)
        ):
            raise invalid("artifact_provenance")
        for column, cell in zip(plan.columns, record.cells, strict=True):
            if (
                cell.name != column.name
                or cell.source_path != column.path
                or cell.lookup_evidence != column.lookup_evidence
                or cell.semantic_evidence is not None
                or (cell.value is not None and not isinstance(cell.value, str))
            ):
                raise invalid("artifact_columns")
    by_id = {record.row_id: record for record in records}
    group_by_scope = {
        (item.row.source, item.row.row): item.duplicate_group for item in assessment.rejected_rows
    }

    def issue_json(issue: DataIssue) -> dict[str, object]:
        item: dict[str, object] = {
            "code": issue.code.value,
            "source": None if issue.source is None else issue.source.value,
            "row": issue.row,
            "column": issue.column,
        }
        if issue.code == DataIssueCode.DUPLICATE:
            if issue.source is None or issue.row is None:
                raise invalid("artifact_duplicate_scope")
            group = group_by_scope.get((issue.source, issue.row))
            if group is None:
                raise invalid("artifact_duplicate_scope")
            item["group_id"] = group.value
        return item

    full_issues = [issue_json(issue) for issue in issues]
    outcomes = [
        {
            "source": o.source.value,
            "sha256": o.source_digest,
            "locator": sources[o.source].locator,
            "collected_at": sources[o.source].collected_at.isoformat(),
            "status": o.status.value,
            "parsed_count": o.parsed_count,
        }
        for o in assessment.source_outcomes
    ]
    groups = [
        {
            "group_id": g.reference.value,
            "canonical_id": g.canonical_id,
            "members": [_row(row) for row in g.members],
        }
        for g in assessment.duplicate_groups
    ]
    report = {
        "contract_version": 2,
        "policy": {
            "contract_version": policy.contract_version,
            "duplicate_policy": policy.duplicate_policy.value,
            "id_column": policy.id_column,
        },
        "evidence_complete": assessment.evidence_complete,
        "input_valid": not issues,
        "counts": {
            "parsed": len(records),
            "clean": len(assessment.clean_rows),
            "rejected": len(assessment.rejected_rows),
            "duplicate_groups": len(groups),
        },
        "total_input_records": len(records) if assessment.evidence_complete else None,
        "sources": outcomes,
        "issues": full_issues,
        "duplicate_groups": groups,
        "unresolved": [
            item for issue, item in zip(issues, full_issues, strict=True) if issue.row is None
        ],
    }
    diagnostic = DataArtifact("validation.json", "application/json", _json(report))
    if not assessment.evidence_complete:
        return (diagnostic,)
    clean: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow([column.name for column in plan.columns] + ["_provenance"])
    for reference in assessment.clean_rows:
        record = by_id[reference.row_id]
        provenance = _provenance(record)
        item: dict[str, object] = {cell.name: cell.value for cell in record.cells}
        item["_provenance"] = provenance
        clean.append(item)
        values = [cell.value or "" for cell in record.cells]
        values = [
            "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
            for value in values
        ]
        writer.writerow([*values, _json(provenance, compact=True)])
    for rejection in assessment.rejected_rows:
        record = by_id[rejection.row.row_id]
        reasons: list[dict[str, object]] = []
        for reason in rejection.reasons:
            item = {"code": reason.code.value, "column": reason.column}
            if reason.code == DataIssueCode.DUPLICATE:
                assert rejection.duplicate_group is not None
                item["group_id"] = rejection.duplicate_group.value
            reasons.append(item)
        rejected.append(
            {
                "row_id": record.row_id,
                "values": {cell.name: cell.value for cell in record.cells},
                "reasons": reasons,
                "_provenance": _provenance(record),
            }
        )
    return (
        DataArtifact("clean.csv", "text/csv", stream.getvalue()),
        DataArtifact("clean.json", "application/json", _json(clean)),
        DataArtifact("rejected.json", "application/json", _json(rejected)),
        diagnostic,
    )
