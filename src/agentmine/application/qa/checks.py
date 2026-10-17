"""Free checks in strict order; no model or external I/O."""

import csv
import io
from dataclasses import replace
from datetime import datetime

from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.contracts.qa import (
    ArtifactFormat,
    CoverageKind,
    QAInspection,
    bundle_content,
)
from agentmine.application.contracts.research import ResearchResult, TaskPlan, VerificationStatus
from agentmine.application.workers.artifacts import render_artifacts
from agentmine.application.workers.data_artifacts import artifacts as data_artifacts
from agentmine.application.workers.data_transform import normalize, strict_json, transform, validate
from agentmine.domain.qa import QAFinding, QAOutcome, QAStage
from agentmine.domain.values import Reference


def finding(
    inspection: QAInspection,
    stage: QAStage,
    code: str,
    outcome: QAOutcome,
    explanation: str,
    *references: Reference,
) -> QAFinding:
    return QAFinding(
        stage, code, outcome, explanation, (inspection.deliverable.content_reference, *references)
    )


def deterministic(inspection: QAInspection, stored_content: str | None) -> tuple[QAFinding, ...]:
    stage = QAStage.DETERMINISTIC
    if (
        stored_content != bundle_content(inspection.result).text
        or bundle_content(inspection.result).reference != inspection.deliverable.content_reference
    ):
        return (
            finding(
                inspection,
                stage,
                "CONTENT_MISMATCH",
                QAOutcome.FAIL,
                "Stored bytes, bundle or deliverable digest do not agree.",
            ),
        )
    findings = [
        finding(
            inspection,
            stage,
            "CONTENT_BOUND",
            QAOutcome.PASS,
            "Exact stored bundle matches the deliverable content digest.",
        )
    ]
    files = {artifact.name: artifact for artifact in inspection.result.artifacts}
    parsed: dict[str, object] = {}
    for format_requirement in inspection.formats:
        artifact = files.get(format_requirement.name)
        if artifact is None:
            findings.append(
                finding(
                    inspection,
                    stage,
                    "MISSING_ARTIFACT",
                    QAOutcome.NEEDS_REVISION,
                    f"Required artifact missing: {format_requirement.name}",
                )
            )
            continue
        try:
            if (
                artifact.media_type != format_requirement.format.value
                or not artifact.content.strip()
                or len(artifact.content.encode("utf-8")) > 10_000_000
            ):
                raise ValueError("Invalid format")
            if format_requirement.format == ArtifactFormat.JSON:
                parsed[artifact.name] = strict_json(artifact.content, numeric_as_text=False)
            elif format_requirement.format == ArtifactFormat.CSV:
                rows = list(csv.reader(io.StringIO(artifact.content, newline=""), strict=True))
                if (
                    not rows
                    or not rows[0]
                    or len(set(rows[0])) != len(rows[0])
                    or any(not cell.strip() for cell in rows[0])
                    or any(len(row) != len(rows[0]) for row in rows[1:])
                ):
                    raise ValueError("CSV shape")
                parsed[artifact.name] = rows
            elif not any(line.startswith("# ") for line in artifact.content.splitlines()):
                raise ValueError("Markdown title missing")
        except (ValueError, csv.Error, RecursionError):
            findings.append(
                finding(
                    inspection,
                    stage,
                    "INVALID_FORMAT",
                    QAOutcome.NEEDS_REVISION,
                    f"Artifact fails declared format: {format_requirement.name}",
                )
            )
    for requirement in inspection.requirements:
        artifact = files.get(requirement.artifact)
        covered = artifact is not None
        if artifact is not None:
            if requirement.kind == CoverageKind.LITERAL:
                covered = requirement.criterion in artifact.content
            elif requirement.kind == CoverageKind.SECTION:
                headings = {
                    line.lstrip("#").strip()
                    for line in artifact.content.splitlines()
                    if line.startswith("#")
                }
                covered = requirement.criterion in headings
            elif requirement.kind == CoverageKind.COLUMN:
                value = parsed.get(artifact.name)
                if artifact.media_type == ArtifactFormat.JSON:
                    covered = isinstance(value, list) and all(
                        isinstance(row, dict)
                        and requirement.criterion in row
                        and row[requirement.criterion] is not None
                        for row in value
                    )
                else:
                    covered = (
                        isinstance(value, list)
                        and bool(value)
                        and requirement.criterion in value[0]
                    )
        if not covered:
            findings.append(
                finding(
                    inspection,
                    stage,
                    "REQUIREMENT_NOT_COVERED",
                    QAOutcome.NEEDS_REVISION,
                    "Declared task requirement lacks evidence.",
                    requirement.reference,
                )
            )
        else:
            findings.append(
                finding(
                    inspection,
                    stage,
                    "SEMANTIC_CHECK_DEFERRED"
                    if requirement.kind == CoverageKind.SEMANTIC
                    else "REQUIREMENT_COVERED",
                    QAOutcome.PASS,
                    "Criterion located; semantic checks, if any, follow free validation.",
                    requirement.reference,
                )
            )
    return tuple(findings)


def research_checks(
    inspection: QAInspection, plan: TaskPlan, result: ResearchResult, now: datetime
) -> tuple[QAFinding, ...]:
    stage = QAStage.DOMAIN_SPECIFIC
    findings: list[QAFinding] = []
    steps = {step.operation_reference: step for step in plan.sources}
    sources = {source.operation_reference: source for source in result.sources}
    if len(sources) != len(result.sources) or set(sources) != set(steps):
        return (
            finding(
                inspection,
                stage,
                "SOURCE_COVERAGE",
                QAOutcome.FAIL,
                "Source inventory does not match the approved plan.",
            ),
        )
    for reference, source in sources.items():
        step = steps[reference]
        if (
            source.tool != step.tool
            or source.locator != step.locator
            or not plan.execution.started_at <= source.collected_at <= now
        ):
            findings.append(
                finding(
                    inspection,
                    stage,
                    "SOURCE_PROVENANCE",
                    QAOutcome.FAIL,
                    "Source scope or collection time does not match plan.",
                    reference,
                )
            )
    for fact in result.findings.facts:
        fact_source = sources.get(fact.source)
        if (
            fact_source is None
            or not fact.quote.strip()
            or fact.quote not in fact_source.text
            or fact_source.status != VerificationStatus.VERIFIED_CONTENT
            or fact_source.verification_reference is None
        ):
            findings.append(
                finding(
                    inspection,
                    stage,
                    "UNSUPPORTED_CLAIM",
                    QAOutcome.FAIL,
                    "Claim lacks a matching verified source excerpt.",
                    fact.source,
                )
            )
    verified = sum(
        source.status == VerificationStatus.VERIFIED_CONTENT for source in result.sources
    )
    if verified < inspection.min_verified_sources or any(
        source.status == VerificationStatus.UNVERIFIED for source in result.sources
    ):
        findings.append(
            finding(
                inspection,
                stage,
                "EVIDENCE_UNVERIFIED",
                QAOutcome.REQUIRES_HUMAN_REVIEW,
                "Source verification is incomplete; AI cannot authenticate it.",
            )
        )
    if (
        not result.findings.facts
        or not result.findings.analysis.strip()
        or not result.findings.uncertainties
    ):
        findings.append(
            finding(
                inspection,
                stage,
                "MISSING_RESEARCH_FIELDS",
                QAOutcome.NEEDS_REVISION,
                "Facts, analysis and explicit uncertainties are required.",
            )
        )
    expected = render_artifacts(plan, result.findings, result.sources, result.warnings)
    if result.artifacts != expected:
        findings.append(
            finding(
                inspection,
                stage,
                "RESEARCH_ARTIFACT_MISMATCH",
                QAOutcome.FAIL,
                "Rendered report/findings/source inventory disagree with typed evidence.",
            )
        )
    if not findings:
        findings.append(
            finding(
                inspection,
                stage,
                "RESEARCH_EVIDENCE_CHECKED",
                QAOutcome.PASS,
                "Attributed facts match captured evidence; analysis remains labeled unverified.",
            )
        )
    return tuple(findings)


def data_checks(
    inspection: QAInspection, plan: DataPlan, result: DataResult, now: datetime
) -> tuple[QAFinding, ...]:
    stage = QAStage.DOMAIN_SPECIFIC
    baseline, input_issues = transform(plan)
    if len(baseline) != len(result.records) or any(
        source.collected_at > now for source in plan.sources
    ):
        return (
            finding(
                inspection,
                stage,
                "DATA_PROVENANCE",
                QAOutcome.FAIL,
                "Record count or source time cannot be reproduced.",
            ),
        )
    semantic = {column.name for column in plan.semantic_columns}
    for original, record in zip(baseline, result.records, strict=True):
        if replace(record, cells=original.cells) != original or len(record.cells) != len(
            original.cells
        ):
            return (
                finding(
                    inspection,
                    stage,
                    "DATA_PROVENANCE",
                    QAOutcome.FAIL,
                    "Record identity/provenance was changed.",
                ),
            )
        for expected, cell, column in zip(original.cells, record.cells, plan.columns, strict=True):
            if cell.name not in semantic:
                valid = cell == expected
            else:
                valid = (
                    replace(cell, value=expected.value, semantic_evidence=None) == expected
                    and (expected.value is not None or cell.value is None)
                    and (cell.value is None or isinstance(cell.value, str))
                    and (expected.value is None or cell.semantic_evidence is not None)
                )
            if not valid:
                return (
                    finding(
                        inspection,
                        stage,
                        "UNSUPPORTED_DATA_CHANGE",
                        QAOutcome.FAIL,
                        "Field change lacks source or semantic provenance.",
                    ),
                )
            try:
                if normalize(cell.value, column, lookup=False) != cell.value:
                    raise ValueError("Noncanonical value")
            except ValueError:
                return (
                    finding(
                        inspection,
                        stage,
                        "INVALID_DATA_VALUE",
                        QAOutcome.NEEDS_REVISION,
                        "A value is not valid/canonical for its type.",
                    ),
                )
    issues = input_issues + validate(plan, result.records)
    findings: list[QAFinding] = []
    for issue in issues:
        findings.append(
            finding(
                inspection,
                stage,
                "DATA_" + issue.code.value.upper(),
                QAOutcome.NEEDS_REVISION,
                f"Data constraint failed at row {issue.row}, column {issue.column}.",
                *(() if issue.source is None else (issue.source,)),
            )
        )
    if not issues and result.issues:
        findings.append(
            finding(
                inspection,
                stage,
                "VALIDATION_REPORT_MISMATCH",
                QAOutcome.FAIL,
                "Worker issues disagree with recomputed validation.",
            )
        )
    if not issues and result.artifacts != data_artifacts(plan, result.records, ()):
        findings.append(
            finding(
                inspection,
                stage,
                "DATA_ARTIFACT_MISMATCH",
                QAOutcome.FAIL,
                "CSV/JSON/provenance disagree with validated records.",
            )
        )
    if not findings:
        findings.append(
            finding(
                inspection,
                stage,
                "DATA_CONSTRAINTS_CHECKED",
                QAOutcome.PASS,
                "Required values, duplicates, bounds, counts and task constraints checked.",
            )
        )
    return tuple(findings)


def domain_specific(inspection: QAInspection, now: datetime) -> tuple[QAFinding, ...]:
    if isinstance(inspection.plan, DataPlan) and isinstance(inspection.result, DataResult):
        return data_checks(inspection, inspection.plan, inspection.result, now)
    assert isinstance(inspection.plan, TaskPlan) and isinstance(inspection.result, ResearchResult)
    return research_checks(inspection, inspection.plan, inspection.result, now)
