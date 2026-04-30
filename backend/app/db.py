"""SQLite-backed persistence for jobs / activity log.

Single file at ``<data_work_dir>/connectclips.db``. Lives with the data so it
follows wherever the data dir moves (e.g. /mnt/c → /mnt/d once the SSD lands).

Why SQLite, not Postgres: zero ops, ACID, ships with stdlib, handles thousands
of writes/sec — plenty for a single-process church app with ≤10 users. If
operating scale ever changes, swap-out is straightforward (the only callers
live in this module + services/jobs.py).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings

# Module-level lock so concurrent requests don't trip each other when writing.
# SQLite handles concurrent reads fine but serializing writes through one
# connection avoids "database is locked" surprises during burst activity.
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db_path() -> Path:
    return settings.data_work_dir / "connectclips.db"


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode = WAL")        # better concurrency
        c.execute("PRAGMA synchronous = NORMAL")      # durable enough, fast
        c.execute("PRAGMA foreign_keys = ON")
        _conn = c
    return _conn


def init() -> None:
    """Create tables if missing. Safe to call repeatedly."""
    c = _connect()
    with _lock:
        c.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id                  TEXT PRIMARY KEY,
                kind                TEXT NOT NULL,
                status              TEXT NOT NULL,
                source              TEXT,
                transcript_path     TEXT,
                url                 TEXT,
                ingested_filename   TEXT,
                clips_path          TEXT,
                clip_index          INTEGER,
                start               REAL,
                end                 REAL,
                output_clip_path    TEXT,
                identity_id         INTEGER,
                user_login          TEXT,
                user_name           TEXT,
                progress_percent    REAL,
                progress_message    TEXT,
                clips_version       TEXT,
                created_at          TEXT NOT NULL,
                started_at          TEXT,
                finished_at         TEXT,
                error               TEXT
            )
        """)
        # Migration: add columns if upgrading an older DB
        for col, ddl in (
            ("progress_percent", "ALTER TABLE jobs ADD COLUMN progress_percent REAL"),
            ("progress_message", "ALTER TABLE jobs ADD COLUMN progress_message TEXT"),
            ("clips_version",    "ALTER TABLE jobs ADD COLUMN clips_version TEXT"),
            ("identity_id",      "ALTER TABLE jobs ADD COLUMN identity_id INTEGER"),
        ):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source     ON jobs (source)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_kind_clip  ON jobs (source, clip_index, kind, status)")


@contextmanager
def cursor() -> Iterator[sqlite3.Cursor]:
    c = _connect()
    with _lock:
        cur = c.cursor()
        try:
            yield cur
        finally:
            cur.close()
