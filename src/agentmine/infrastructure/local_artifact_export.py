"""Local-only, no-clobber artifact publication; a manifest marks completed export."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agentmine.application.contracts.data import DataArtifact
from agentmine.application.contracts.local_runtime import ArtifactExport, ExportedArtifact
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.values import Reference
from agentmine.domain.work import Deliverable
from agentmine.infrastructure.local_data_inputs import reject_links


@dataclass(frozen=True, slots=True)
class LocalArtifactExporter:
    directory: Path | None

    def export(
        self,
        execution: Reference,
        content: Reference,
        artifacts: tuple[DataArtifact, ...],
        *,
        deliverable: Deliverable | None = None,
    ) -> ArtifactExport:
        try:
            if self.directory is None:
                raise ValueError("Explicit export directory required")
            directory = self.directory.absolute()
            reject_links(directory.parent)
            directory.mkdir(exist_ok=True)
            reject_links(directory)
            payloads: dict[str, bytes] = {}
            for artifact in artifacts:
                if (
                    artifact.name not in ("data.csv", "data.json", "validation.json")
                    or artifact.name in payloads
                ):
                    raise ValueError("Unsupported artifact inventory")
                payloads[artifact.name] = artifact.content.encode("utf-8")
            exported = tuple(
                ExportedArtifact(name, hashlib.sha256(raw).hexdigest(), len(raw))
                for name, raw in payloads.items()
            )
            manifest = {
                "execution": execution.value,
                "content_reference": content.value,
                "external_submission": False,
                "artifacts": [
                    {"name": item.name, "sha256": item.digest, "bytes": item.byte_count}
                    for item in exported
                ],
            }
            if deliverable is not None:
                if (
                    deliverable.execution_reference != execution
                    or deliverable.content_reference != content
                ):
                    raise ValueError("Export deliverable binding mismatch")
                manifest["deliverable"] = {
                    "lineage": deliverable.reference.value,
                    "version": deliverable.version,
                    "execution": execution.value,
                    "content_reference": content.value,
                }
            payloads["manifest.json"] = (
                json.dumps(manifest, sort_keys=True, ensure_ascii=True) + "\n"
            ).encode("utf-8")
            if any(item.name not in payloads for item in directory.iterdir()):
                raise ValueError("Export directory contains unrelated files")
            # Preflight all existing files before publishing anything. Never overwrite.
            for name, raw in payloads.items():
                target = directory / name
                if target.exists() or target.is_symlink():
                    reject_links(target)
                    if (
                        not target.is_file()
                        or target.stat().st_size != len(raw)
                        or target.read_bytes() != raw
                    ):
                        raise ValueError("Conflicting export content")
            for name, raw in payloads.items():
                target = directory / name
                if target.exists():
                    continue
                temporary: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=directory, prefix=".agentmine-export-", delete=False
                    ) as stream:
                        temporary = Path(stream.name)
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    # Atomic hard-link create is no-clobber on supported local filesystems.
                    os.link(temporary, target)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            return ArtifactExport(execution, content, exported)
        except (OSError, ValueError):
            raise PortError(
                PortErrorCode.UNAVAILABLE,
                "local_export",
                "Cannot safely export; inspect destination for conflicts or incomplete export",
            ) from None
