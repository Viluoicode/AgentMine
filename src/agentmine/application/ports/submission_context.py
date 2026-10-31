"""Local immutable context/evidence storage; no external actions or approval policy."""

from typing import Protocol

from agentmine.application.contracts.ai import ReferencedText
from agentmine.application.contracts.submission_context import (
    SubmissionEnvelope,
    SubmissionEvidence,
)
from agentmine.domain.values import Reference


class SubmissionContextRepository(Protocol):
    def prepare(self, envelope: SubmissionEnvelope) -> SubmissionEnvelope:
        """Atomic exact-evidence/current-snapshot check and immutable insert; no claim/send."""
        ...

    def get(self, reference: Reference) -> SubmissionEnvelope | None: ...

    def by_scope(self, reference: Reference) -> SubmissionEnvelope | None: ...

    def record_evidence(self, evidence: SubmissionEvidence, capture: ReferencedText) -> None:
        """Atomically retain provisional metadata/capture; never apply a final outcome."""
        ...

    def get_evidence(self, reference: Reference) -> SubmissionEvidence | None: ...
