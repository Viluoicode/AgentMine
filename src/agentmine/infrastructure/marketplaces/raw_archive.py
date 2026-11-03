"""Immutable local source captures, independent of domain snapshot persistence."""

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.errors import DomainError
from agentmine.domain.values import Reference, require_aware_timestamp
from agentmine.infrastructure.local_data_inputs import reject_links


@dataclass(frozen=True, slots=True)
class RawCapture:
    route: str
    observed_at: datetime
    body: bytes

    @property
    def reference(self) -> Reference:
        envelope = self.route.encode() + b"\0" + self.observed_at.isoformat().encode() + b"\0"
        return Reference("raw:sha256:" + hashlib.sha256(envelope + self.body).hexdigest())


@dataclass(frozen=True, slots=True)
class RawArchive:
    path: Path

    def save(self, capture: RawCapture) -> Reference:
        require_aware_timestamp(capture.observed_at)
        try:
            with closing(sqlite3.connect(self.path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS marketplace_captures "
                    "(id TEXT PRIMARY KEY, route TEXT NOT NULL, observed_at TEXT NOT NULL, "
                    "body BLOB NOT NULL)"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO marketplace_captures VALUES (?, ?, ?, ?)",
                    (
                        capture.reference.value,
                        capture.route,
                        capture.observed_at.isoformat(),
                        capture.body,
                    ),
                )
            return capture.reference
        except sqlite3.Error:
            raise PortError(
                PortErrorCode.UNAVAILABLE, "capture", "Source archive unavailable"
            ) from None

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        """One genuinely read-only snapshot; never initialize missing archives/schema."""
        try:
            path = self.path.absolute()
            reject_links(path)
            if not path.is_file():
                raise OSError("Existing local archive required")
            # WAL readers can create sidecars even with mode=ro. Existing RawArchive
            # writers use rollback journals; refuse WAL/hot-journal inspection.
            with path.open("rb") as stream:
                header = stream.read(20)
            if header[18:20] == b"\x02\x02" or any(
                Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
            ):
                raise PortError(
                    PortErrorCode.UNSUPPORTED, "capture", "Archive requires external reconciliation"
                )
            with closing(
                sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as connection:
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2_016_000)
                connection.execute("BEGIN")
                table = connection.execute(
                    "SELECT type FROM sqlite_master WHERE name='marketplace_captures'"
                ).fetchone()
                if table is None or table[0] != "table":
                    raise PortError(
                        PortErrorCode.INVALID_RESPONSE, "capture", "Missing archive schema"
                    )
                try:
                    yield connection
                finally:
                    connection.rollback()
        except (sqlite3.Error, OSError, ValueError):
            raise PortError(
                PortErrorCode.UNAVAILABLE, "capture", "Source archive unavailable"
            ) from None

    def read_capture(
        self, connection: sqlite3.Connection, reference: Reference
    ) -> RawCapture | None:
        """Read one selected row, bounded before loading its body; verify full envelope."""
        row = connection.execute(
            "SELECT route, observed_at, length(body), typeof(body) "
            "FROM marketplace_captures WHERE id = ?",
            (reference.value,),
        ).fetchone()
        if row is None:
            return None
        if (
            not isinstance(row[0], str)
            or len(row[0]) > 2048
            or not isinstance(row[1], str)
            or len(row[1]) > 100
            or type(row[2]) is not int
            or not 0 <= row[2] <= 2_000_000
            or row[3] != "blob"
        ):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "capture", "Invalid capture bounds/types"
            )
        body = connection.execute(
            "SELECT body FROM marketplace_captures WHERE id = ?",
            (reference.value,),
        ).fetchone()
        try:
            capture = RawCapture(row[0], datetime.fromisoformat(row[1]), body[0])
            require_aware_timestamp(capture.observed_at)
            if capture.reference != reference:
                raise ValueError("Capture digest mismatch")
            return capture
        except (ValueError, TypeError, DomainError):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "capture", "Corrupt source capture"
            ) from None

    def get(self, reference: Reference) -> RawCapture | None:
        with self.reading() as connection:
            return self.read_capture(connection, reference)
