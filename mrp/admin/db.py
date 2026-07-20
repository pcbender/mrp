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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_jobs (
                id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                repo_root TEXT NOT NULL,
                release_slug TEXT NOT NULL,
                track_slug TEXT NOT NULL,
                track_key TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                progress REAL NOT NULL DEFAULT 0,
                phase TEXT,
                message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                heartbeat_at TEXT,
                completed_at TEXT,
                cancel_requested_at TEXT,
                pid INTEGER,
                output TEXT,
                artifact_path TEXT,
                log_path TEXT NOT NULL,
                events_path TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_video_render_per_track
            ON video_jobs(track_key)
            WHERE kind = 'render' AND status IN ('pending', 'running')
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


def get_latest_job_by_command(command: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, command, status, started_at, completed_at, output "
            "FROM jobs WHERE command = ? ORDER BY rowid DESC LIMIT 1",
            [command],
        ).fetchone()
    if row is None:
        return None
    return dict(zip(["id", "command", "status", "started_at", "completed_at", "output"], row))


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, command, status, started_at, completed_at, output FROM jobs WHERE id = ?",
            [job_id],
        ).fetchone()
    if row is None:
        return None
    return dict(zip(["id", "command", "status", "started_at", "completed_at", "output"], row))


_VIDEO_JOB_FIELDS = [
    "id",
    "command",
    "repo_root",
    "release_slug",
    "track_slug",
    "track_key",
    "kind",
    "status",
    "progress",
    "phase",
    "message",
    "created_at",
    "started_at",
    "heartbeat_at",
    "completed_at",
    "cancel_requested_at",
    "pid",
    "output",
    "artifact_path",
    "log_path",
    "events_path",
]


def _video_job(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(zip(_VIDEO_JOB_FIELDS, row))


def create_video_job(
    *,
    job_id: str,
    command: str,
    repo_root: str,
    release_slug: str,
    track_slug: str,
    track_key: str,
    kind: str,
    created_at: str,
    log_path: str,
    events_path: str,
) -> None:
    """Persist a video job before its child process is started."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO video_jobs (
                id, command, repo_root, release_slug, track_slug, track_key,
                kind, created_at, log_path, events_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                job_id,
                command,
                repo_root,
                release_slug,
                track_slug,
                track_key,
                kind,
                created_at,
                log_path,
                events_path,
            ],
        )
        conn.commit()


def update_video_job(job_id: str, **values: Any) -> None:
    allowed = set(_VIDEO_JOB_FIELDS) - {
        "id",
        "command",
        "repo_root",
        "release_slug",
        "track_slug",
        "track_key",
        "kind",
        "created_at",
        "log_path",
        "events_path",
    }
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"unsupported video job fields: {', '.join(sorted(unknown))}")
    if not values:
        return
    fields = [f"{name} = ?" for name in values]
    params = [*values.values(), job_id]
    with _connect() as conn:
        conn.execute(
            f"UPDATE video_jobs SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()


def get_video_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_VIDEO_JOB_FIELDS)} FROM video_jobs WHERE id = ?",
            [job_id],
        ).fetchone()
    return _video_job(row)


def get_latest_video_job(
    track_key: str,
    kind: str | None = None,
) -> dict[str, Any] | None:
    where = "track_key = ?"
    params: list[Any] = [track_key]
    if kind is not None:
        where += " AND kind = ?"
        params.append(kind)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT {', '.join(_VIDEO_JOB_FIELDS)} FROM video_jobs "
            f"WHERE {where} ORDER BY rowid DESC LIMIT 1",
            params,
        ).fetchone()
    return _video_job(row)


def list_video_jobs(
    *,
    release_slug: str | None = None,
    track_key: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if release_slug is not None:
        clauses.append("release_slug = ?")
        params.append(release_slug)
    if track_key is not None:
        clauses.append("track_key = ?")
        params.append(track_key)
    if active_only:
        clauses.append("status IN ('pending', 'running')")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_VIDEO_JOB_FIELDS)} FROM video_jobs "
            f"{where} ORDER BY rowid DESC",
            params,
        ).fetchall()
    return [_video_job(row) for row in rows if row is not None]
