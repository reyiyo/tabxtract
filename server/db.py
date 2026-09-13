# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Job history in SQLite.

There is no concurrency between users or separate processes here: one
process, a thread pool, one user. One connection
is opened per operation (SQLite does not share connections across threads)
with WAL enabled, which is what makes that pattern tolerable.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,      -- local path or URL, depending on source_kind
    source_kind TEXT NOT NULL,      -- 'file' | 'url'
    title       TEXT NOT NULL,      -- display name (file name or video title)
    status      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    error       TEXT,
    analysis    TEXT,               -- JSON
    render      TEXT,               -- JSON
    overrides   TEXT,               -- JSON
    output_dir  TEXT,
    local_path  TEXT                -- source video on disk, if it still exists
);
"""

_JSON_COLUMNS = ("analysis", "render", "overrides")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def new_job_id() -> str:
    return uuid.uuid4().hex


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    for col in _JSON_COLUMNS:
        job[col] = json.loads(job[col]) if job[col] else None
    return job


def create_job(job_id: str, source: str, source_kind: str, title: str,
               status: str = "new", local_path: str | None = None) -> dict[str, Any]:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, source, source_kind, title, status, created_at, "
            "updated_at, local_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, source, source_kind, title, status, now, now, local_path),
        )
    return get_job(job_id)  # type: ignore[return-value]


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    if not fields:
        return get_job(job_id)
    payload = {
        k: (json.dumps(v) if k in _JSON_COLUMNS and v is not None else v)
        for k, v in fields.items()
    }
    payload["updated_at"] = time.time()
    assignments = ", ".join(f"{k} = ?" for k in payload)
    with _connect() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?",
                     (*payload.values(), job_id))
    return get_job(job_id)


def delete_job(job_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
