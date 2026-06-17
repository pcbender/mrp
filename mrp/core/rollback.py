from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.core.publish import production_safety
from mrp.core.verify import verify_target


MARKER_FILE = ".allow-deploy"


def rollback(repo: str | Path, to: str | None = None, yes: bool = False) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "rollback",
        "repo": str(root),
        "generated_at": generated_at,
        "to": to,
        "confirmed": yes,
        "errors": [],
    }

    safety = production_safety(root)
    result["target"] = "local-production"
    result["target_path"] = safety.get("target_path")
    if safety["status"] != "passed":
        add_error(result, "safety", safety["message"])
        return finish(root, generated_at, result)

    candidate = rollback_candidate(root, to)
    result["candidate"] = candidate
    if candidate["status"] != "passed":
        add_error(result, "candidate", candidate["message"])
        return finish(root, generated_at, result)

    if not yes:
        result["status"] = "confirmation_required"
        result["message"] = "Rollback candidate selected; rerun with --yes to restore it."
        result["report_path"] = write_rollback_report(root, generated_at, result)
        return result

    destination = root / safety["target_path"]
    source = root / candidate["path"]
    clear_target(destination)
    copied = copy_tree(source, destination)
    result["copied_files"] = copied

    verification = verify_target(root, target="production")
    result["verification_report_path"] = verification.get("report_path")
    if verification["status"] != "passed":
        add_error(result, "verification", "Production verification failed after rollback.")
        result["verification_errors"] = verification.get("errors", [])
        return finish(root, generated_at, result)

    result["status"] = "rolled_back"
    result["report_path"] = write_rollback_report(root, generated_at, result)
    return result


def rollback_candidate(root: Path, to: str | None) -> dict[str, Any]:
    if to:
        build_path = root / "builds" / "staging" / to
        if not build_path.is_dir():
            return {"status": "failed", "message": f"Unknown rollback build: {to}"}
        return {
            "status": "passed",
            "kind": "build",
            "build_id": to,
            "path": str(build_path.relative_to(root)),
        }

    archives = sorted(path for path in (root / "builds" / "archive").glob("production-*") if path.is_dir())
    if not archives:
        return {"status": "failed", "message": "No production archive available for rollback."}
    archive = archives[-1]
    return {
        "status": "passed",
        "kind": "archive",
        "path": str(archive.relative_to(root)),
    }


def clear_target(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in destination.iterdir():
        if child.name == MARKER_FILE:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_tree(source: Path, destination: Path) -> int:
    copied = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, output)
        copied += 1
    return copied


def add_error(result: dict[str, Any], field: str, message: str) -> None:
    result["errors"].append({"field": field, "message": message, "severity": "error"})


def finish(root: Path, generated_at: str, result: dict[str, Any]) -> dict[str, Any]:
    result["status"] = "failed"
    result["summary"] = {"errors": len(result["errors"])}
    result["report_path"] = write_rollback_report(root, generated_at, result)
    return result


def write_rollback_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    report_path = root / "reports" / "rollback" / f"{timestamp}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_rollback(result: dict[str, Any]) -> str:
    lines = [
        f"Rollback {result['status']}",
        f"Target: {result['target']}",
        f"Report: {result['report_path']}",
    ]
    if result.get("candidate"):
        lines.append(f"Candidate: {result['candidate'].get('path')}")
    for error in result.get("errors", []):
        lines.append(f"- {error['field']}: {error['message']}")
    if result.get("message"):
        lines.append(result["message"])
    return "\n".join(lines)
