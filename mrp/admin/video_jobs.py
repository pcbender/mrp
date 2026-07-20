"""Persistent process-backed jobs for the MRP music-video workspace.

The generic admin runner intentionally remains thread based. Video preparation,
analysis, and rendering run in a separate Python process and communicate through
an append-only JSONL event log so an admin restart can recover their state.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.admin import db

ACTIVE_STATUSES = {"pending", "running"}
TERMINAL_STATUSES = {"done", "error", "cancelled", "interrupted"}
JOB_KINDS = {"prepare", "analyze", "render"}
POLL_SECONDS = 0.2
CANCEL_GRACE_SECONDS = 5.0


class VideoJobConflict(Exception):
    """Raised when a track already has an active full render."""


class VideoJobError(Exception):
    """Raised when a video child process cannot be launched or controlled."""


_LOCK = threading.Lock()
_MONITORS: dict[str, threading.Thread] = {}
_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _job_path(job: dict[str, Any], field: str) -> Path:
    root = Path(str(job["repo_root"])).resolve()
    path = (root / str(job[field])).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise VideoJobError(f"video job {field} escapes the repository") from exc
    return path


def _process_matches(pid: int | None, job_id: str) -> bool:
    if not pid or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    command_path = Path("/proc") / str(pid) / "cmdline"
    if not command_path.is_file():
        return True
    try:
        command = command_path.read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return False
    return "mrp.video.worker" in command and job_id in command


def _read_events(job: dict[str, Any], offset: int) -> tuple[list[dict[str, Any]], int]:
    path = _job_path(job, "events_path")
    if not path.is_file():
        return [], offset
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        stream.seek(offset)
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line:
                return events, stream.tell()
            if not line.endswith("\n"):
                return events, start
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)


def _apply_event(job_id: str, event: dict[str, Any]) -> None:
    kind = str(event.get("event") or "")
    timestamp = str(event.get("timestamp") or _now())
    if kind in {"started", "progress", "heartbeat"}:
        values: dict[str, Any] = {
            "status": "running",
            "heartbeat_at": timestamp,
        }
        if event.get("progress") is not None:
            values["progress"] = max(0.0, min(100.0, float(event["progress"])))
        if event.get("phase") is not None:
            values["phase"] = str(event["phase"])
        if event.get("message") is not None:
            values["message"] = str(event["message"])
        if kind == "started":
            values["started_at"] = timestamp
        db.update_video_job(job_id, **values)
        return
    if kind == "result":
        db.update_video_job(
            job_id,
            status="done",
            progress=100.0,
            phase=str(event.get("phase") or "complete"),
            message=str(event.get("message") or "Completed"),
            heartbeat_at=timestamp,
            completed_at=timestamp,
            output=json.dumps(event.get("result"), default=str),
            artifact_path=event.get("artifact_path"),
        )
        return
    if kind in {"error", "cancelled"}:
        status = "cancelled" if kind == "cancelled" else "error"
        db.update_video_job(
            job_id,
            status=status,
            phase=status,
            message=str(event.get("message") or status.title()),
            heartbeat_at=timestamp,
            completed_at=timestamp,
            output=json.dumps(event.get("errors") or event.get("message"), default=str),
        )


def _consume_events(job_id: str, offset: int) -> int:
    job = db.get_video_job(job_id)
    if job is None:
        return offset
    events, offset = _read_events(job, offset)
    for event in events:
        _apply_event(job_id, event)
    return offset


def _cancel_deadline_passed(job: dict[str, Any]) -> bool:
    requested = job.get("cancel_requested_at")
    if not requested:
        return False
    try:
        started = datetime.fromisoformat(str(requested))
    except ValueError:
        return True
    return (datetime.now(UTC) - started).total_seconds() >= CANCEL_GRACE_SECONDS


def _finish_without_event(job: dict[str, Any]) -> None:
    if job.get("cancel_requested_at"):
        status = "cancelled"
        message = "Cancelled"
    else:
        status = "interrupted"
        message = "Worker exited without a terminal event"
    db.update_video_job(
        str(job["id"]),
        status=status,
        phase=status,
        message=message,
        completed_at=_now(),
    )


def _monitor(job_id: str, process: subprocess.Popen[bytes] | None = None) -> None:
    offset = 0
    try:
        while True:
            offset = _consume_events(job_id, offset)
            job = db.get_video_job(job_id)
            if job is None:
                return
            if job["status"] in TERMINAL_STATUSES:
                if process is not None:
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                return

            if process is not None:
                alive = process.poll() is None
            else:
                alive = _process_matches(job.get("pid"), job_id)

            if job.get("cancel_requested_at") and alive and _cancel_deadline_passed(job):
                try:
                    if process is not None:
                        os.killpg(process.pid, signal.SIGKILL)
                    elif _process_matches(job.get("pid"), job_id):
                        os.killpg(int(job["pid"]), signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass

            if not alive:
                offset = _consume_events(job_id, offset)
                refreshed = db.get_video_job(job_id)
                if refreshed is not None and refreshed["status"] not in TERMINAL_STATUSES:
                    _finish_without_event(refreshed)
                return
            time.sleep(POLL_SECONDS)
    finally:
        with _LOCK:
            _MONITORS.pop(job_id, None)
            _PROCESSES.pop(job_id, None)


def _start_monitor(job_id: str, process: subprocess.Popen[bytes] | None = None) -> None:
    with _LOCK:
        current = _MONITORS.get(job_id)
        if current is not None and current.is_alive():
            return
        if process is not None:
            _PROCESSES[job_id] = process
        thread = threading.Thread(
            target=_monitor,
            args=(job_id, process),
            name=f"mrp-video-{job_id}",
            daemon=True,
        )
        _MONITORS[job_id] = thread
        thread.start()


def launch(
    root: Path,
    release_slug: str,
    track_slug: str,
    track_key: str,
    kind: str,
) -> str:
    """Launch one video operation in an isolated Python child process."""
    if kind not in JOB_KINDS:
        raise VideoJobError(f"unknown video job kind: {kind}")
    repo = root.resolve()
    job_id = uuid.uuid4().hex[:12]
    job_dir = repo / "assets" / "processed" / "video" / track_key / "logs" / "jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    log_path = job_dir / f"{job_id}.log"
    events_path = job_dir / f"{job_id}.events.jsonl"
    log_relative = log_path.relative_to(repo).as_posix()
    events_relative = events_path.relative_to(repo).as_posix()
    command_name = f"video/{release_slug}/{track_slug}/{kind}"
    try:
        db.create_video_job(
            job_id=job_id,
            command=command_name,
            repo_root=str(repo),
            release_slug=release_slug,
            track_slug=track_slug,
            track_key=track_key,
            kind=kind,
            created_at=_now(),
            log_path=log_relative,
            events_path=events_relative,
        )
    except sqlite3.IntegrityError as exc:
        raise VideoJobConflict(
            f"{track_slug} already has an active full render"
        ) from exc

    command = [
        sys.executable,
        "-m",
        "mrp.video.worker",
        kind,
        "--repo",
        str(repo),
        "--release",
        release_slug,
        "--track",
        track_slug,
        "--job-id",
        job_id,
        "--events",
        str(events_path),
    ]
    try:
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                command,
                cwd=str(repo),
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        db.update_video_job(
            job_id,
            status="error",
            phase="launch",
            message=str(exc),
            completed_at=_now(),
        )
        raise VideoJobError(f"could not launch video worker: {exc}") from exc

    db.update_video_job(
        job_id,
        status="running",
        phase="launch",
        message="Worker process started",
        pid=process.pid,
        started_at=_now(),
        heartbeat_at=_now(),
    )
    _start_monitor(job_id, process)
    return job_id


def request_cancel(job_id: str) -> dict[str, Any]:
    job = db.get_video_job(job_id)
    if job is None:
        raise VideoJobError(f"video job not found: {job_id}")
    if job["status"] not in ACTIVE_STATUSES:
        return job
    requested_at = _now()
    db.update_video_job(
        job_id,
        cancel_requested_at=requested_at,
        phase="cancelling",
        message="Cancellation requested",
    )
    with _LOCK:
        process = _PROCESSES.get(job_id)
    try:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        elif _process_matches(job.get("pid"), job_id):
            os.killpg(int(job["pid"]), signal.SIGTERM)
        else:
            db.update_video_job(
                job_id,
                status="cancelled",
                phase="cancelled",
                message="Cancelled; worker was no longer running",
                completed_at=_now(),
            )
    except (OSError, ProcessLookupError) as exc:
        raise VideoJobError(f"could not cancel video job {job_id}: {exc}") from exc
    return db.get_video_job(job_id) or job


def recover() -> list[str]:
    """Recover live children and mark missing workers interrupted after restart."""
    recovered: list[str] = []
    for job in db.list_video_jobs(active_only=True):
        job_id = str(job["id"])
        _consume_events(job_id, 0)
        refreshed = db.get_video_job(job_id)
        if refreshed is None or refreshed["status"] in TERMINAL_STATUSES:
            continue
        if _process_matches(refreshed.get("pid"), job_id):
            _start_monitor(job_id)
            recovered.append(job_id)
            continue
        cancelled = bool(refreshed.get("cancel_requested_at"))
        status = "cancelled" if cancelled else "interrupted"
        db.update_video_job(
            job_id,
            status=status,
            phase=status,
            message=(
                "Cancellation completed while MRP Admin was offline"
                if cancelled
                else "Worker was not running when MRP Admin restarted"
            ),
            completed_at=_now(),
        )
    return recovered
