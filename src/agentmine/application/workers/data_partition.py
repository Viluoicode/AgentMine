"""Pure opt-in v2 partition computation; no execution, acceptance, cost or export authority."""

import json
from dataclasses import replace
from hashlib import sha256

from agentmine.application.contracts.data import (
    DataIssue,
    DataIssueCode,
    DataPartitionAssessment,
    DataPlan,
    DataRecord,
    DataRowReference,
    DataSourceOutcome,
    DuplicateIDGroup,
    PartitionRejection,
    SourceParseStatus,
    invalid,
    text,
)
from agentmine.application.workers.data_transform import transform, validate
from agentmine.domain.values import Reference


def duplicate_group_payload(plan: DataPlan, canonical_id: str) -> bytes:
    """Canonical UTF-8 JSON array; exact settings are part of group identity v2."""
    policy = plan.output_policy
    if policy is None:
        raise invalid("partition_policy")
    text(canonical_id, "canonical_id", 32_000)
    return json.dumps(
        [
            "agentmine-data-duplicate-v2",
            {
                "contract_version": policy.contract_version,
                "duplicate_policy": policy.duplicate_policy.value,
                "id_column": policy.id_column,
            },
            canonical_id,
            [
                {"reference": source.reference.value, "sha256": source.digest}
                for source in plan.sources
            ],
        ],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def row_reference(record: DataRecord) -> DataRowReference:
    return DataRowReference(record.source, record.source_digest, record.row, record.row_id)


def partition(
    plan: DataPlan,
) -> tuple[tuple[DataRecord, ...], tuple[DataIssue, ...], DataPartitionAssessment]:
    """Reproduce approved inputs, preserve evidence and reject every valid-ID duplicate.

    With incomplete source parsing, clean refs are only provisional candidates.
    Neither complete evidence nor a nonempty clean tuple authorizes acceptance.
    """
    plan = replace(plan)  # Revalidate immutable contracts, including policy/threshold pairing.
    policy = plan.output_policy
    if policy is None:
        raise invalid("partition_policy")
    records, transformed_issues = transform(plan)
    issues = list(transformed_issues + validate(plan, records))
    invalid_ids = {
        (issue.source, issue.row)
        for issue in issues
        if issue.column == policy.id_column
        and issue.code
        in (
            DataIssueCode.MISSING_COLUMN,
            DataIssueCode.MISSING_VALUE,
            DataIssueCode.INVALID_VALUE,
        )
    }
    by_id: dict[str, list[DataRecord]] = {}
    for record in records:
        identifier = next(cell.value for cell in record.cells if cell.name == policy.id_column)
        if identifier is not None and (record.source, record.row) not in invalid_ids:
            by_id.setdefault(identifier, []).append(record)

    groups: list[DuplicateIDGroup] = []
    group_for_row: dict[str, Reference] = {}
    for identifier, members in by_id.items():
        if len(members) < 2:
            continue
        reference = Reference(
            "sha256:" + sha256(duplicate_group_payload(plan, identifier)).hexdigest()
        )
        groups.append(
            DuplicateIDGroup(reference, identifier, tuple(row_reference(row) for row in members))
        )
        for member in members:
            issues.append(
                DataIssue(DataIssueCode.DUPLICATE, member.source, member.row, policy.id_column)
            )
            group_for_row[member.row_id] = reference

    source_order = {source.reference: index for index, source in enumerate(plan.sources)}
    column_order = {column.name: index for index, column in enumerate(plan.columns)}
    ordered_issues = tuple(
        sorted(
            dict.fromkeys(issues),
            key=lambda issue: (
                -1 if issue.source is None else source_order[issue.source],
                0 if issue.row is None else issue.row,
                -1 if issue.column is None else column_order[issue.column],
                issue.code.value,
            ),
        )
    )
    row_issues: dict[tuple[Reference, int], list[DataIssue]] = {}
    for issue in ordered_issues:
        if issue.source is not None and issue.row is not None:
            row_issues.setdefault((issue.source, issue.row), []).append(issue)
    clean: list[DataRowReference] = []
    rejected: list[PartitionRejection] = []
    for record in records:
        reasons = tuple(row_issues.get((record.source, record.row), ()))
        if reasons:
            rejected.append(
                PartitionRejection(row_reference(record), reasons, group_for_row.get(record.row_id))
            )
        else:
            clean.append(row_reference(record))

    malformed = {
        issue.source for issue in ordered_issues if issue.code == DataIssueCode.MALFORMED_SOURCE
    }
    outcomes = tuple(
        DataSourceOutcome(
            source.reference,
            source.digest,
            SourceParseStatus.MALFORMED
            if source.reference in malformed
            else SourceParseStatus.PARSED,
            None
            if source.reference in malformed
            else sum(record.source == source.reference for record in records),
        )
        for source in plan.sources
    )
    assessment = DataPartitionAssessment(
        2, policy, tuple(clean), tuple(rejected), outcomes, tuple(groups), not malformed
    )
    return records, ordered_issues, assessment
