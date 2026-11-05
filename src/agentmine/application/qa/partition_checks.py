"""V2 checks within DeliverableQA: reproduce frozen inputs before applying approved gates."""

from dataclasses import replace
from datetime import datetime

from agentmine.application.contracts.data import DataPlan, DataResult
from agentmine.application.contracts.qa import QAInspection
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.application.workers.data_partition import partition
from agentmine.application.workers.data_partition_artifacts import render_partition_artifacts
from agentmine.domain.errors import DomainError
from agentmine.domain.qa import QAFinding, QAOutcome, QAStage


def evidence(inspection: QAInspection) -> QAFinding:
    """Do not trust a supplied count, report, membership or self-consistent bundle hash."""
    plan = inspection.plan
    result = inspection.result
    assert isinstance(plan, DataPlan) and isinstance(result, DataResult)
    if any(not isinstance(source.content, str) for source in plan.sources):
        raise PortError(PortErrorCode.UNSUPPORTED, "qa", "Retained replay source bytes unavailable")
    valid = False
    try:
        replace(inspection)
        plan = replace(
            plan,
            sources=tuple(replace(s) for s in plan.sources),
            columns=tuple(replace(c) for c in plan.columns),
        )
        records, issues, assessment = partition(plan)
        valid = (result.records, result.issues, result.partition) == (
            records,
            issues,
            assessment,
        ) and result.artifacts == render_partition_artifacts(plan, records, issues, assessment)
    except (DomainError, ValueError, TypeError, RecursionError):
        # Invalid/unsupported retained contracts are never reinterpreted as legacy data.
        valid = False
    return QAFinding(
        QAStage.DETERMINISTIC,
        "PARTITION_EVIDENCE_CHECKED" if valid else "PARTITION_EVIDENCE_MISMATCH",
        QAOutcome.PASS if valid else QAOutcome.FAIL,
        "Frozen source replay, ordered issues, full duplicate groups, canonical values, "
        "input presence, partition and exact artifact inventory/bytes agree."
        if valid
        else "Retained partition, source evidence or artifacts disagree with frozen replay.",
        (inspection.deliverable.content_reference,),
    )


def acceptance(inspection: QAInspection, now: datetime) -> tuple[QAFinding, ...]:
    """Reached only after evidence integrity; input validity is not acceptance."""
    plan, result = inspection.plan, inspection.result
    assert isinstance(plan, DataPlan) and isinstance(result, DataResult)
    assessment, thresholds = result.partition, inspection.partition_acceptance
    assert assessment is not None and thresholds is not None
    findings: list[QAFinding] = []

    def add(code: str, explanation: str, outcome: QAOutcome = QAOutcome.NEEDS_REVISION) -> None:
        findings.append(
            QAFinding(
                QAStage.DOMAIN_SPECIFIC,
                code,
                outcome,
                explanation,
                (inspection.deliverable.content_reference,),
            )
        )

    if any(source.collected_at > now for source in plan.sources):
        add("DATA_PROVENANCE", "Source observation time is in the future.", QAOutcome.FAIL)
    if not assessment.evidence_complete:
        add(
            "PARTITION_INCOMPLETE",
            "Source coverage is incomplete; partial candidates are not a deliverable.",
        )
    for issue in result.issues:
        if issue.row is None:
            add(
                "PARTITION_GLOBAL_ISSUE",
                f"Unresolved source/batch issue: {issue.code.value}; "
                f"source={issue.source}; column={issue.column}.",
            )
    if len(assessment.clean_rows) < thresholds.min_clean_records:
        add(
            "PARTITION_CLEAN_MINIMUM",
            f"Clean={len(assessment.clean_rows)}; approved minimum={thresholds.min_clean_records}.",
        )
    if len(assessment.rejected_rows) > thresholds.max_rejected_records:
        add(
            "PARTITION_REJECT_LIMIT",
            f"Rejected={len(assessment.rejected_rows)}; "
            f"approved maximum={thresholds.max_rejected_records}.",
        )
    if not findings:
        add(
            "PARTITION_ACCEPTED",
            f"Complete reproduced partition: clean={len(assessment.clean_rows)}, "
            f"rejected={len(assessment.rejected_rows)} within frozen thresholds; "
            "rejected reasons remain retained. Human submission approval remains separate.",
            QAOutcome.PASS,
        )
    return tuple(findings)
