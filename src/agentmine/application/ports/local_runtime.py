"""Bounded approved input reads and local-only artifact export."""

from typing import Protocol

from agentmine.application.contracts.data import DataArtifact, DataSource
from agentmine.application.contracts.local_runtime import ApprovedDataInput, ArtifactExport
from agentmine.domain.values import Reference


class DataInputReader(Protocol):
    def load(self, inputs: tuple[ApprovedDataInput, ...]) -> tuple[DataSource, ...]: ...


class ArtifactExporter(Protocol):
    def export(
        self, execution: Reference, content: Reference, artifacts: tuple[DataArtifact, ...]
    ) -> ArtifactExport: ...
