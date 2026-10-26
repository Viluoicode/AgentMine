"""Read exact approved CSV/JSON bytes under an explicit local root; never follow URLs."""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from agentmine.application.contracts.data import DataSource
from agentmine.application.contracts.local_runtime import ApprovedDataInput
from agentmine.application.errors import PortError, PortErrorCode


def reject_links(path: Path) -> None:
    if str(path).startswith(("\\\\", "//")) or path.drive.startswith("\\\\"):
        raise ValueError("Network filesystem paths are unsupported")
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024
        ):
            raise ValueError("Linked filesystem paths are unsupported")


@dataclass(frozen=True, slots=True)
class LocalDataInputReader:
    root: Path | None

    def load(self, inputs: tuple[ApprovedDataInput, ...]) -> tuple[DataSource, ...]:
        try:
            if self.root is None:
                raise ValueError("Explicit input root required")
            root = self.root.absolute()
            reject_links(root)
            if not root.is_dir():
                raise ValueError("Input root must be a directory")
            sources: list[DataSource] = []
            for item in inputs:
                relative = Path(item.relative_path)
                if (
                    relative.is_absolute()
                    or relative.drive
                    or ".." in relative.parts
                    or ":" in item.relative_path
                ):
                    raise ValueError("Relative input paths without traversal required")
                path = root / relative
                reject_links(path)
                if (
                    not path.resolve().is_relative_to(root.resolve())
                    or path.suffix.lower() != "." + item.format.value
                ):
                    raise ValueError("Approved CSV/JSON input required")
                before = path.stat()
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError("Regular input file required")
                with path.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                        raise ValueError("Input identity changed")
                    raw = stream.read(1_000_001)
                if (
                    len(raw) > 1_000_000
                    or "sha256:" + hashlib.sha256(raw).hexdigest() != item.content_reference.value
                ):
                    raise ValueError("Approved input digest/size mismatch")
                if raw.startswith(b"\xef\xbb\xbf"):
                    raise ValueError("Use UTF-8 without BOM to preserve exact input bytes")
                sources.append(
                    DataSource(
                        item.reference,
                        item.locator,
                        item.collected_at,
                        item.format,
                        raw.decode("utf-8"),
                    )
                )
            return tuple(sources)
        except (OSError, ValueError):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE,
                "local_data_inputs",
                "Missing, unsafe, invalid or changed approved local input",
            ) from None
