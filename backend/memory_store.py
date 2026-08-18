from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from threading import Lock


class MemoryStore:
    """Small durable SQLite memory store with WAL and bounded reads."""

    def __init__(self, path=None):
        self.path = Path(path or os.getenv("VENTOR_MEMORY_DB", Path(__file__).resolve().parent / "data" / "memory.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._db_conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._db_conn.row_factory = sqlite3.Row
        self._db_conn.execute("PRAGMA journal_mode=WAL")
        self._db_conn.execute("PRAGMA synchronous=NORMAL")
        self._db_conn.execute("PRAGMA busy_timeout=30000")
        self._db_conn.execute("PRAGMA foreign_keys=ON")
        self._init()

    def close(self) -> None:
        with self._lock:
            if self._db_conn is not None:
                self._db_conn.close()
                self._db_conn = None

    def _init(self) -> None:
        with self._lock:
            self._db_conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY,
                    ts REAL NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    session TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session, id DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts DESC);
                CREATE TABLE IF NOT EXISTS facts(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated REAL NOT NULL
                );
                """
            )
            self._db_conn.commit()

    def add(self, role: str, content: str, session: str = "default") -> None:
        with self._lock:
            self._db_conn.execute(
                "INSERT INTO messages(ts,role,content,session) VALUES(?,?,?,?)",
                (time.time(), role, content, session),
            )
            self._db_conn.commit()

    def add_many(self, rows: list[tuple[str, str, str]]) -> None:
        if not rows:
            return
        now = time.time()
        with self._lock:
            self._db_conn.executemany(
                "INSERT INTO messages(ts,role,content,session) VALUES(?,?,?,?)",
                [(now, role, content, session) for role, content, session in rows],
            )
            self._db_conn.commit()

    def recent(self, limit: int = 20, session: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            if session is None:
                rows = self._db_conn.execute(
                    "SELECT role,content,ts,session FROM messages ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = self._db_conn.execute(
                    "SELECT role,content,ts,session FROM messages WHERE session=? ORDER BY id DESC LIMIT ?",
                    (session, limit),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def search(self, query: str, limit: int = 10) -> list[dict]:
        query = str(query)[:500]
        limit = max(1, min(int(limit), 100))
        with self._lock:
            rows = self._db_conn.execute(
                "SELECT role,content,ts,session FROM messages WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_fact(self, key: str, value: str, confidence: float | None = None, source: str | None = None) -> None:
        # Keep the public schema backwards-compatible while preserving provenance.
        with self._lock:
            columns = {r[1] for r in self._db_conn.execute("PRAGMA table_info(facts)")}
            if "confidence" not in columns:
                self._db_conn.execute("ALTER TABLE facts ADD COLUMN confidence REAL")
            if "source" not in columns:
                self._db_conn.execute("ALTER TABLE facts ADD COLUMN source TEXT")
            self._db_conn.execute(
                "INSERT INTO facts(key,value,updated,confidence,source) VALUES(?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated,"
                "confidence=excluded.confidence,source=excluded.source",
                (key, value, time.time(), confidence, source),
            )
            self._db_conn.commit()

    def facts(self) -> list[dict]:
        with self._lock:
            rows = self._db_conn.execute(
                "SELECT key,value,updated,confidence,source FROM facts ORDER BY updated DESC"
            ).fetchall()
        return [dict(row) for row in rows]
