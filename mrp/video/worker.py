"""Child-process entry point for persistent MRP Admin video jobs."""
from __future__ import annotations

import argparse
import json
import re
import signal
import threading
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ENCODED_PERCENT = re.compile(r"\((?P<percent>\d+(?:\.\d+)?)%")


class WorkerCancelled(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class EventWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.progress = 0.0
        self.phase = "launch"
        self.message = "Starting video worker"

    def emit(self, event: str, **values: Any) -> None:
        with self._lock:
            if values.get("progress") is not None:
                self.progress = float(values["progress"])
            if values.get("phase") is not None:
                self.phase = str(values["phase"])
            if values.get("message") is not None:
                self.message = str(values["message"])
            payload = {
                "event": event,
                "timestamp": _now(),
                **values,
            }
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, default=str, sort_keys=True) + "\n")
                stream.flush()

    def heartbeat(self) -> None:
        self.emit(
            "heartbeat",
            progress=self.progress,
            phase=self.phase,
            message=self.message,
        )


class ProgressMapper:
    def __init__(
        self,
        action: str,
        writer: EventWriter,
        cancelled: threading.Event,
    ) -> None:
        self.action = action
        self.writer = writer
        self.cancelled = cancelled
        self.analysis_step = 0

    def __call__(self, message: str) -> None:
        if self.cancelled.is_set():
            raise WorkerCancelled("Cancellation requested")
        lower = message.casefold()
        phase = {
            "analyze": "analysis",
            "align": "alignment",
            "render": "render",
        }.get(self.action, "preflight")
        percent = self.writer.progress
        if "validating" in lower:
            phase, percent = "preflight", 5.0
        elif "hashing" in lower:
            phase, percent = "analysis", 12.0
        elif "decoding" in lower:
            self.analysis_step += 1
            phase, percent = "analysis", min(35.0, 16.0 + self.analysis_step * 4.0)
        elif "extracting" in lower:
            self.analysis_step += 1
            phase, percent = "analysis", min(88.0, 38.0 + self.analysis_step * 8.0)
        elif "cached analysis" in lower:
            phase, percent = "analysis", 90.0
        elif "whisper" in lower or "transcription" in lower:
            phase, percent = "transcription", max(percent, 55.0)
        elif "matching canonical" in lower:
            phase, percent = "alignment", 82.0
        elif "writing editable" in lower:
            phase, percent = "alignment", 97.0
        elif "render plan" in lower:
            phase, percent = "planning", 18.0
        elif "streaming" in lower:
            phase, percent = "rendering", 20.0
        elif match := _ENCODED_PERCENT.search(message):
            phase = "rendering"
            percent = 20.0 + float(match.group("percent")) * 0.7
        elif "verifying" in lower:
            phase, percent = "verification", 95.0
        elif "publishing" in lower:
            phase, percent = "publishing", 99.0
        else:
            percent = min(94.0, max(percent, percent + 1.0))
        self.writer.emit(
            "progress",
            progress=percent,
            phase=phase,
            message=message,
        )


def _relative_artifact(root: Path, result: dict[str, Any], action: str) -> str | None:
    if action == "prepare":
        value = result.get("project")
    elif action == "analyze":
        value = (result.get("analysis") or {}).get("cache_path")
    elif action == "align":
        value = (result.get("alignment") or {}).get("output_path")
    else:
        value = (result.get("render") or {}).get("output_path")
    if not value:
        return None
    path = Path(str(value))
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one MRP track-video worker job.")
    parser.add_argument("action", choices=("prepare", "analyze", "align", "render"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--track", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--events", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.repo.resolve()
    writer = EventWriter(args.events.resolve())
    cancelled = threading.Event()
    stopped = threading.Event()

    def request_cancel(_signum: int, _frame: object) -> None:
        cancelled.set()

    signal.signal(signal.SIGTERM, request_cancel)
    signal.signal(signal.SIGINT, request_cancel)

    def heartbeat() -> None:
        while not stopped.wait(2.0):
            writer.heartbeat()

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    writer.emit(
        "started",
        progress=1.0,
        phase="launch",
        message=f"Running {args.action} for {args.track}",
        job_id=args.job_id,
    )

    try:
        from mrp.video.workspace import (
            align_track,
            analyze_track,
            prepare_track,
            render_track,
        )

        progress = ProgressMapper(args.action, writer, cancelled)
        if args.action == "prepare":
            writer.emit(
                "progress",
                progress=5.0,
                phase="preflight",
                message="Preparing and validating track assets",
            )
            result = prepare_track(root, args.release, args.track).summary()
        elif args.action == "analyze":
            result = analyze_track(
                root,
                args.release,
                args.track,
                progress=progress,
            )
        elif args.action == "align":
            result = align_track(
                root,
                args.release,
                args.track,
                force=True,
                progress=progress,
            )
        else:
            result = render_track(
                root,
                args.release,
                args.track,
                progress=progress,
                cancel_check=cancelled.is_set,
            )
        if cancelled.is_set():
            raise WorkerCancelled("Cancellation requested")
        stopped.set()
        writer.emit(
            "result",
            progress=100.0,
            phase="complete",
            message=f"{args.action.title()} completed",
            result=result,
            artifact_path=_relative_artifact(root, result, args.action),
        )
        return 0
    except WorkerCancelled as exc:
        stopped.set()
        writer.emit("cancelled", phase="cancelled", message=str(exc))
        return 130
    except Exception as exc:  # noqa: BLE001
        stopped.set()
        traceback.print_exc()
        if cancelled.is_set():
            writer.emit("cancelled", phase="cancelled", message="Cancellation requested")
            return 130
        problems = getattr(exc, "problems", None)
        writer.emit(
            "error",
            phase="error",
            message=str(exc),
            errors=list(problems) if problems else [str(exc)],
        )
        return 1
    finally:
        stopped.set()
        heartbeat_thread.join(timeout=0.2)


if __name__ == "__main__":
    raise SystemExit(main())
