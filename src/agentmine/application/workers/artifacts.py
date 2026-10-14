"""Deterministic portable artifacts; source inventory never comes from a model."""

import json

from agentmine.application.contracts.research import (
    ResearchArtifact,
    ResearchFindings,
    ResearchWarning,
    SourceEvidence,
    TaskPlan,
)


def literal(text: str) -> str:
    # Indented code blocks prevent source/model text from creating active links or HTML.
    return "\n".join("    " + line for line in text.splitlines())


def render_artifacts(
    plan: TaskPlan,
    findings: ResearchFindings,
    sources: tuple[SourceEvidence, ...],
    warnings: tuple[ResearchWarning, ...],
) -> tuple[ResearchArtifact, ...]:
    inventory = [
        {
            "source_id": source.operation_reference.value,
            "tool": source.tool.value,
            "locator": source.locator,
            "title": source.title,
            "collected_at": source.collected_at.isoformat(),
            "sha256": source.content_digest,
            "text": source.text,
            "verification_status": source.status.value,
            "verification_note": source.verification_note,
            "verification_reference": None
            if source.verification_reference is None
            else source.verification_reference.value,
        }
        for source in sources
    ]
    structured = {
        "execution": plan.execution.reference.value,
        "questions": plan.questions,
        "facts": [{"source_id": fact.source.value, "quote": fact.quote} for fact in findings.facts],
        "analysis": findings.analysis,
        "uncertainties": findings.uncertainties,
        "warnings": [warning.value for warning in warnings],
    }
    report = "# Research report\n\n## Questions\n\n" + literal("\n".join(plan.questions))
    report += "\n\n## Facts — verified source excerpts\n\n"
    report += (
        "These are quotations from verified captures, not independent proof of their claims.\n\n"
    )
    report += "\n\n".join(
        literal(f"[{fact.source.value}]\n{fact.quote}") for fact in findings.facts
    )
    report += "\n\n## Analysis — unverified model draft\n\n" + literal(findings.analysis)
    report += "\n\n## Uncertainties\n\n" + literal("\n".join(findings.uncertainties))
    report += "\n\n## Sources\n\nSee sources.json for exact captured text and provenance.\n"
    return (
        ResearchArtifact("report.md", "text/markdown", report),
        ResearchArtifact(
            "sources.json", "application/json", json.dumps(inventory, ensure_ascii=True, indent=2)
        ),
        ResearchArtifact(
            "findings.json", "application/json", json.dumps(structured, ensure_ascii=True, indent=2)
        ),
    )
