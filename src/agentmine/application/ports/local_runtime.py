"""Bounded approved input reads and local-only artifact export."""

from typing import Protocol

from agentmine.application.contracts.data import DataArtifact, DataPartitionPolicy, DataSource
from agentmine.application.contracts.local_runtime import ApprovedDataInput, ArtifactExport
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable


class DataInputReader(Protocol):
    def load(self, inputs: tuple[ApprovedDataInput, ...]) -> tuple[DataSource, ...]: ...


class ArtifactExporter(Protocol):
    def export(
        self,
        execution: Reference,
        content: Reference,
        artifacts: tuple[DataArtifact, ...],
        *,
        deliverable: Deliverable | None = None,
        output_policy: DataPartitionPolicy | None = None,
        evidence_complete: bool | None = None,
    ) -> ArtifactExport: ...
