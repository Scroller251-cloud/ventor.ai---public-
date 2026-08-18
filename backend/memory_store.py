from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path


class MemoryStore:
    """Persistent SQLite memory with principal/session isolation and bounded retrieval."""
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("VENTOR_MEMORY_DB", Path(__file__).resolve().parent / "data" / "memory.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False
        self._init()

    def _db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=True)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _init(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            c = self._db()
            c.executescript("""
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY,
                    ts REAL NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    session TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session, id DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session_ts ON messages(session, ts DESC);
                CREATE TABLE IF NOT EXISTS facts(
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated REAL NOT NULL,
                    session TEXT NOT NULL DEFAULT 'global',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    source TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(key, session)
                );
                CREATE INDEX IF NOT EXISTS idx_facts_session ON facts(session, updated DESC);
            """)
            columns = {row[1] for row in c.execute("PRAGMA table_info(facts)").fetchall()}
            if "confidence" not in columns:
                c.execute("ALTER TABLE facts ADD COLUMN confidence REAL NOT NULL DEFAULT 0.5")
            if "source" not in columns:
                c.execute("ALTER TABLE facts ADD COLUMN source TEXT NOT NULL DEFAULT ''")
            c.commit()
            self._initialized = True

    @staticmethod
    def namespace(principal_id: str | None, session: str = "default") -> str | None:
        if not principal_id:
            return None
        clean_principal = str(principal_id).replace("/", "_")[:160]
        clean_session = str(session or "default").replace("/", "_")[:160]
        return f"principal:{clean_principal}:session:{clean_session}"

    @staticmethod
    def _importance(value) -> float:
        return max(0.0, min(1.0, float(value)))

    def add(self, role, content, session="default", importance=0.5):
        self.add_many([(role, content, session, importance)])

    def add_many(self, rows):
        prepared = []
        now = time.time()
        for role, content, session, importance in rows:
            if not session:
                raise ValueError("memory session is required")
            text = str(content).strip()
            if text:
                prepared.append((now, str(role), text, str(session), self._importance(importance)))
        if not prepared:
            return
        c = self._db()
        c.executemany("INSERT INTO messages(ts,role,content,session,importance) VALUES(?,?,?,?,?)", prepared)
        c.commit()

    def recent(self, limit=20, session=None):
        limit = max(1, min(int(limit), 200))
        c = self._db()
        if session:
            rows = c.execute("SELECT role,content,ts,session,importance FROM messages WHERE session=? ORDER BY id DESC LIMIT ?", (session, limit)).fetchall()
        else:
            rows = c.execute("SELECT role,content,ts,session,importance FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(x) for x in reversed(rows)]

    def search(self, q, limit=10, session=None):
        query = str(q or "").strip()
        if not query:
            return self.recent(limit, session)
        terms = [x for x in query.lower().split() if len(x) > 1][:8]
        if not terms:
            return self.recent(limit, session)
        limit = max(1, min(int(limit), 100))
        clauses = " OR ".join("LOWER(content) LIKE ?" for _ in terms)
        params = [f"%{x}%" for x in terms]
        if session:
            sql = f"SELECT role,content,ts,session,importance FROM messages WHERE session=? AND ({clauses}) ORDER BY importance DESC,id DESC LIMIT ?"
            params = [session, *params, limit]
        else:
            sql = f"SELECT role,content,ts,session,importance FROM messages WHERE ({clauses}) ORDER BY importance DESC,id DESC LIMIT ?"
            params.append(limit)
        return [dict(x) for x in self._db().execute(sql, params).fetchall()]

    def set_fact(self, key, value, session="global", confidence=0.5, source=""):
        c = self._db()
        c.execute("INSERT INTO facts(key,value,updated,session,confidence,source) VALUES(?,?,?,?,?,?) ON CONFLICT(key,session) DO UPDATE SET value=excluded.value,updated=excluded.updated,confidence=excluded.confidence,source=excluded.source", (str(key), str(value), time.time(), str(session), self._importance(confidence), str(source)))
        c.commit()

    def facts(self, session=None):
        c = self._db()
        if session:
            rows = c.execute("SELECT key,value,updated,session,confidence,source FROM facts WHERE session=? ORDER BY updated DESC", (session,)).fetchall()
        else:
            rows = c.execute("SELECT key,value,updated,session,confidence,source FROM facts ORDER BY updated DESC").fetchall()
        return [dict(x) for x in rows]

    def retrieve_context(self, query, session, limit=12):
        limit = max(1, min(int(limit), 50))
        rows = self.search(query, limit=max(limit * 3, 24), session=session)
        now = time.time()
        query_terms = set(str(query).lower().split())
        scored = []
        for row in rows:
            age_days = max(0.0, (now - float(row["ts"])) / 86400.0)
            recency = 1.0 / (1.0 + age_days)
            words = set(str(row["content"]).lower().split())
            overlap = len(query_terms & words) / max(1, len(query_terms))
            score = 0.50 * overlap + 0.30 * float(row.get("importance", 0.5)) + 0.20 * recency
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [row for _, row in scored[:limit]]
