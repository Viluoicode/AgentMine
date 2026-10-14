"""Durable dispatch ownership and usage metadata; never store model text or prompts."""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from agentmine.application.errors import PortError, PortErrorCode


@dataclass(frozen=True, slots=True)
class LLMJournal:
    path: Path

    def claim(self, operation: str, fingerprint: str) -> None:
        try:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS llm_calls "
                    "(operation TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, metadata TEXT)"
                )
                db.execute("BEGIN IMMEDIATE")
                old = db.execute(
                    "SELECT fingerprint FROM llm_calls WHERE operation=?", (operation,)
                ).fetchone()
                if old is not None:
                    code = (
                        PortErrorCode.OUTCOME_UNKNOWN
                        if old[0] == fingerprint
                        else PortErrorCode.CONFLICT
                    )
                    raise PortError(
                        code, "llm_dispatch", "Operation already dispatched; reconcile evidence"
                    )
                db.execute("INSERT INTO llm_calls VALUES (?, ?, NULL)", (operation, fingerprint))
        except sqlite3.Error:
            raise PortError(
                PortErrorCode.UNAVAILABLE, "llm_journal", "Dispatch journal unavailable"
            ) from None

    def record(self, operation: str, metadata: dict[str, object]) -> None:
        try:
            with closing(sqlite3.connect(self.path)) as db, db:
                cursor = db.execute(
                    "UPDATE llm_calls SET metadata=? WHERE operation=? AND metadata IS NULL",
                    (json.dumps(metadata, sort_keys=True), operation),
                )
                if cursor.rowcount != 1:
                    raise PortError(PortErrorCode.CONFLICT, "llm_journal", "Usage journal conflict")
        except sqlite3.Error:
            raise PortError(
                PortErrorCode.UNAVAILABLE, "llm_journal", "Usage journal unavailable"
            ) from None
