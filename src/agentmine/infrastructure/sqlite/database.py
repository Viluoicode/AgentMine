"""SQLite transaction and snapshot mechanics shared by the five repositories."""

import hashlib
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agentmine.application.contracts.records import Versioned
from agentmine.application.errors import PortError, PortErrorCode
from agentmine.infrastructure.sqlite.codec import SnapshotCodec


def composite_key(*parts: str | int) -> str:
    return json.dumps(parts, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class IndexValues:
    parent: str | None = None
    occurred_at: datetime | None = None
    status: str | None = None
    source: str | None = None


class SQLiteDatabase:
    """A file-backed database; connections are owned and closed per operation."""

    def __init__(self, path: Path, *, timeout_seconds: float = 5.0) -> None:
        if str(path) == ":memory:" or timeout_seconds < 0:
            raise ValueError("A file path and nonnegative timeout are required")
        self.path = path.resolve()
        self.timeout_seconds = timeout_seconds
        self.codec = SnapshotCodec()
        self._logger = logging.getLogger(__name__)
        with self.transaction(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise PortError(PortErrorCode.UNSUPPORTED, "open", "Unknown database version")
            if version == 0:
                connection.execute("""
                    CREATE TABLE snapshots (
                        kind TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
                        payload TEXT NOT NULL, digest TEXT NOT NULL,
                        parent TEXT, occurred_at TEXT, status TEXT, source TEXT,
                        PRIMARY KEY(kind, id), CHECK(revision > 0)
                    )
                """)
                connection.execute(
                    "CREATE INDEX by_parent ON snapshots(kind, parent, occurred_at, id)"
                )
                connection.execute("CREATE INDEX by_status ON snapshots(kind, status, id)")
                connection.execute("CREATE INDEX by_source ON snapshots(kind, source, id)")
                connection.execute("PRAGMA user_version = 1")

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self.path, timeout=self.timeout_seconds, isolation_level=None
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            if connection is not None:
                connection.rollback()
            self._logger.error(
                "Local persistence operation failed",
                extra={"operation": "sqlite", "error_code": PortErrorCode.UNAVAILABLE.value},
            )
            raise PortError(
                PortErrorCode.UNAVAILABLE, "sqlite", "Local persistence unavailable"
            ) from error
        except BaseException:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    def decode[T](self, row: sqlite3.Row, expected: type[T]) -> Versioned[T]:
        payload = row["payload"]
        if (
            not isinstance(payload, str)
            or hashlib.sha256(payload.encode()).hexdigest() != row["digest"]
        ):
            raise PortError(PortErrorCode.INVALID_RESPONSE, "read", "Snapshot checksum mismatch")
        revision = row["revision"]
        if type(revision) is not int or revision < 1:
            raise PortError(PortErrorCode.INVALID_RESPONSE, "read", "Invalid snapshot revision")
        return Versioned(self.codec.loads(payload, expected), revision)

    def read[T](
        self, connection: sqlite3.Connection, kind: str, key: str, expected: type[T]
    ) -> Versioned[T] | None:
        row = connection.execute(
            "SELECT * FROM snapshots WHERE kind = ? AND id = ?", (kind, key)
        ).fetchone()
        return None if row is None else self.decode(row, expected)

    def get[T](self, kind: str, key: str, expected: type[T]) -> Versioned[T] | None:
        with self.transaction() as connection:
            return self.read(connection, kind, key, expected)

    def find[T](
        self,
        kind: str,
        expected: type[T],
        *,
        parent: str | None = None,
        status: str | None = None,
        source: str | None = None,
    ) -> tuple[Versioned[T], ...]:
        clauses = ["kind = ?"]
        parameters = [kind]
        for column, value in (("parent", parent), ("status", status), ("source", source)):
            if value is not None:
                clauses.append(f"{column} = ?")  # Column names are adapter constants.
                parameters.append(value)
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM snapshots WHERE "
                + " AND ".join(clauses)
                + " ORDER BY occurred_at, id",
                parameters,
            ).fetchall()
            return tuple(self.decode(row, expected) for row in rows)

    def write(
        self,
        connection: sqlite3.Connection,
        kind: str,
        key: str,
        value: object,
        revision: int,
        indexes: IndexValues,
    ) -> None:
        payload = self.codec.dumps(value)
        timestamp = indexes.occurred_at
        if timestamp is not None and timestamp.utcoffset() is None:
            raise PortError(PortErrorCode.INVALID_RESPONSE, "write", "Aware timestamp required")
        connection.execute(
            """INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(kind, id) DO UPDATE SET revision=excluded.revision,
               payload=excluded.payload, digest=excluded.digest, parent=excluded.parent,
               occurred_at=excluded.occurred_at, status=excluded.status, source=excluded.source""",
            (
                kind,
                key,
                revision,
                payload,
                hashlib.sha256(payload.encode()).hexdigest(),
                indexes.parent,
                None
                if timestamp is None
                else timestamp.astimezone(UTC).isoformat(timespec="microseconds"),
                indexes.status,
                indexes.source,
            ),
        )

    def immutable(
        self, kind: str, key: str, value: object, indexes: IndexValues | None = None
    ) -> bool:
        """Atomic insert: True only for the owner that created the immutable identity."""
        with self.transaction(write=True) as connection:
            old = self.read(connection, kind, key, type(value))
            if old is not None:
                if old.value != value:
                    raise PortError(PortErrorCode.CONFLICT, "save", "Immutable identity reused")
                return False
            self.write(connection, kind, key, value, 1, indexes or IndexValues())
            return True

    def compare_and_swap[T](
        self,
        connection: sqlite3.Connection,
        kind: str,
        key: str,
        value: T,
        expected_revision: int | None,
        indexes: IndexValues | None = None,
    ) -> Versioned[T]:
        old = self.read(connection, kind, key, type(value))
        if (None if old is None else old.revision) != expected_revision:
            raise PortError(PortErrorCode.CONFLICT, "save", "Stale snapshot revision")
        revision = 1 if old is None else old.revision + 1
        self.write(connection, kind, key, value, revision, indexes or IndexValues())
        return Versioned(value, revision)
