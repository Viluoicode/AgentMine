"""Immutable local source captures, independent of domain snapshot persistence."""

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from agentmine.application.errors import PortError, PortErrorCode
from agentmine.domain.values import Reference, require_aware_timestamp


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

    def get(self, reference: Reference) -> RawCapture | None:
        try:
            with closing(sqlite3.connect(self.path)) as connection:
                row = connection.execute(
                    "SELECT route, observed_at, body FROM marketplace_captures WHERE id = ?",
                    (reference.value,),
                ).fetchone()
            if row is None:
                return None
            capture = RawCapture(str(row[0]), datetime.fromisoformat(row[1]), bytes(row[2]))
            require_aware_timestamp(capture.observed_at)
            if capture.reference != reference:
                raise ValueError
            return capture
        except sqlite3.Error:
            raise PortError(
                PortErrorCode.UNAVAILABLE, "capture", "Source archive unavailable"
            ) from None
        except (ValueError, TypeError):
            raise PortError(
                PortErrorCode.INVALID_RESPONSE, "capture", "Corrupt source capture"
            ) from None
