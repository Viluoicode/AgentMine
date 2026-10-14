"""CSV/JSON artifacts with record and field provenance plus a validation report."""

import csv
import io
import json

from agentmine.application.contracts.data import DataArtifact, DataIssue, DataPlan, DataRecord


def artifacts(
    plan: DataPlan, records: tuple[DataRecord, ...], issues: tuple[DataIssue, ...]
) -> tuple[DataArtifact, ...]:
    report = {
        "valid": not issues,
        "record_count": len(records),
        "issues": [
            {
                "code": issue.code.value,
                "source": None if issue.source is None else issue.source.value,
                "row": issue.row,
                "column": issue.column,
            }
            for issue in issues
        ],
    }
    validation = DataArtifact("validation.json", "application/json", json.dumps(report, indent=2))
    if issues:
        return (validation,)
    items: list[dict[str, object]] = []
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow([column.name for column in plan.columns] + ["_provenance"])
    for record in records:
        provenance = {
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
                    "semantic_evidence": None
                    if cell.semantic_evidence is None
                    else cell.semantic_evidence.value,
                    "semantic_unverified": cell.semantic_evidence is not None,
                }
                for cell in record.cells
            },
        }
        item: dict[str, object] = {cell.name: cell.value for cell in record.cells}
        item["_provenance"] = provenance
        items.append(item)
        # Prefix spreadsheet formula-looking data on CSV export only. JSON preserves exact values.
        values = [cell.value or "" for cell in record.cells]
        values = [
            "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
            for value in values
        ]
        writer.writerow([*values, json.dumps(provenance, ensure_ascii=True)])
    return (
        DataArtifact("data.csv", "text/csv", stream.getvalue()),
        DataArtifact(
            "data.json", "application/json", json.dumps(items, ensure_ascii=True, indent=2)
        ),
        validation,
    )
