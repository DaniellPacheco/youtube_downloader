from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
                    duration REAL NOT NULL, thumbnail TEXT, path TEXT,
                    status TEXT NOT NULL DEFAULT 'metadata', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT NOT NULL,
                    status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '', error_code TEXT, error_detail TEXT,
                    resolution INTEGER, start_time REAL, end_time REAL, audio_format TEXT,
                    result_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES sources(id),
                    FOREIGN KEY(result_id) REFERENCES results(id)
                );
                CREATE TABLE IF NOT EXISTS results (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, job_id TEXT NOT NULL,
                    kind TEXT NOT NULL, filename TEXT NOT NULL, path TEXT NOT NULL,
                    mime_type TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_results_source ON results(source_id);
            """)
            db.execute(
                "UPDATE jobs SET status='failed', error_code='interrupted', "
                "error_detail='A aplicação foi encerrada durante o processamento.', updated_at=? "
                "WHERE status IN ('queued','analyzing','downloading','processing')",
                (now(),),
            )

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self.connect() as db:
            db.execute(sql, params)

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

