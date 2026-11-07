import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sign_in_failures (
    key TEXT PRIMARY KEY,
    failures INTEGER NOT NULL,
    first_failure_at REAL NOT NULL,
    locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    quality TEXT NOT NULL,
    created_at REAL NOT NULL,
    cancelled INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    track_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    youtube_id TEXT,
    youtube_title TEXT,
    file_name TEXT,
    file_path TEXT,
    file_bytes INTEGER,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS items_job ON items(job_id);
CREATE INDEX IF NOT EXISTS items_status ON items(status);
"""

ITEM_STATUSES = ("queued", "working", "done", "failed", "cancelled", "expired")
UPDATABLE_ITEM_FIELDS = {"status", "error", "youtube_id", "youtube_title", "file_name", "file_path", "file_bytes", "finished_at"}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            with self._lock:
                yield connection
                connection.commit()
        finally:
            connection.close()

    def update_item(self, item_id: int, **fields) -> None:
        unknown = set(fields) - UPDATABLE_ITEM_FIELDS
        if unknown:
            raise ValueError(f"cannot update unknown item fields: {sorted(unknown)}")
        if "status" in fields and fields["status"] not in ITEM_STATUSES:
            raise ValueError(f"unknown item status {fields['status']!r}")
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self.connect() as connection:
            connection.execute(f"UPDATE items SET {assignments} WHERE id = ?", [*fields.values(), item_id])


def now() -> float:
    return time.time()
