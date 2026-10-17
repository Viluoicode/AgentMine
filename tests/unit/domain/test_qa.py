"""QA report invariants, ordering and conservative aggregation."""

from datetime import UTC, datetime

import pytest

from agentmine.domain.errors import DomainError
from agentmine.domain.qa import QAFinding, QAOutcome, QAReport, QAStage
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable


def finding(stage: QAStage, outcome: QAOutcome) -> QAFinding:
    return QAFinding(stage, "CHECK", outcome, "Checked evidence", (Reference("content"),))


def report(findings: tuple[QAFinding, ...]) -> QAReport:
    return QAReport(
        Reference("report"),
        Deliverable(Reference("deliverable"), Reference("execution"), 1, Reference("content")),
        datetime(2026, 10, 14, tzinfo=UTC),
        findings,
    )


@pytest.mark.parametrize("outcome", list(QAOutcome))
def test_outcomes_and_evidence(outcome: QAOutcome) -> None:
    value = report(
        (finding(QAStage.DETERMINISTIC, QAOutcome.PASS), finding(QAStage.DOMAIN_SPECIFIC, outcome))
    )
    assert value.outcome == outcome


@pytest.mark.parametrize(
    "stages",
    [
        (QAStage.AI,),
        (QAStage.DOMAIN_SPECIFIC, QAStage.DETERMINISTIC),
        (QAStage.DETERMINISTIC, QAStage.AI),
    ],
)
def test_invalid_order(stages: tuple[QAStage, ...]) -> None:
    with pytest.raises(DomainError):
        report(tuple(finding(stage, QAOutcome.PASS) for stage in stages))


@pytest.mark.parametrize(
    "outcome", [QAOutcome.FAIL, QAOutcome.NEEDS_REVISION, QAOutcome.REQUIRES_HUMAN_REVIEW]
)
def test_ai_cannot_override_free_check(outcome: QAOutcome) -> None:
    with pytest.raises(DomainError):
        report(
            (
                finding(QAStage.DETERMINISTIC, QAOutcome.PASS),
                finding(QAStage.DOMAIN_SPECIFIC, outcome),
                finding(QAStage.AI, QAOutcome.PASS),
            )
        )


def test_explanation_and_evidence_required() -> None:
    with pytest.raises(DomainError):
        QAFinding(QAStage.DETERMINISTIC, "CHECK", QAOutcome.PASS, "Explanation", ())
    with pytest.raises(DomainError):
        QAFinding(QAStage.DETERMINISTIC, "CHECK", QAOutcome.PASS, "", (Reference("content"),))
    assert (
        report(
            (
                finding(QAStage.DETERMINISTIC, QAOutcome.REQUIRES_HUMAN_REVIEW),
                finding(QAStage.DOMAIN_SPECIFIC, QAOutcome.FAIL),
            )
        ).outcome
        == QAOutcome.FAIL
    )
