from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

from mrp.admin import db


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def launch(command: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, command)
    thread = threading.Thread(target=_run, args=(job_id, fn, args, kwargs), daemon=True)
    thread.start()
    return job_id


def _run(job_id: str, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
    db.update_job(job_id, "running", started_at=_now())
    try:
        result = fn(*args, **kwargs)
        db.update_job(job_id, "done", output=json.dumps(result, default=str), completed_at=_now())
    except Exception as exc:  # noqa: BLE001
        db.update_job(job_id, "error", output=str(exc), completed_at=_now())
