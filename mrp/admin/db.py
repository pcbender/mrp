from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

_DB_PATH: Path | None = None


def init(db_path: Path | None = None) -> None:
    global _DB_PATH
    if db_path is None:
        db_path = Path.home() / ".mrp" / "admin.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _DB_PATH = db_path
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                started_at TEXT,
                completed_at TEXT,
                output TEXT
            )
        """)
        conn.commit()


def _connect() -> sqlite3.Connection:
    assert _DB_PATH is not None, "db.init() not called"
    return sqlite3.connect(_DB_PATH)


def create_job(job_id: str, command: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, command, status) VALUES (?, ?, 'pending')",
            [job_id, command],
        )
        conn.commit()


def update_job(
    job_id: str,
    status: str,
    *,
    output: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> None:
    fields: list[str] = ["status = ?"]
    params: list[Any] = [status]
    if started_at is not None:
        fields.append("started_at = ?")
        params.append(started_at)
    if completed_at is not None:
        fields.append("completed_at = ?")
        params.append(completed_at)
    if output is not None:
        fields.append("output = ?")
        params.append(output)
    params.append(job_id)
    with _connect() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, command, status, started_at, completed_at, output FROM jobs WHERE id = ?",
            [job_id],
        ).fetchone()
    if row is None:
        return None
    return dict(zip(["id", "command", "status", "started_at", "completed_at", "output"], row))
