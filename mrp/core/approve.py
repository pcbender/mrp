from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def approve(
    repo: str | Path,
    release: str | None = None,
    build: str | None = None,
    mode: str = "human",
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "approve",
        "repo": str(root),
        "generated_at": generated_at,
        "release": release,
        "build_id": build,
        "mode": mode,
        "errors": [],
    }

    verification = latest_verification(root)
    if not verification:
        add_error(result, "verification", "No verification report found.")
        return finish(root, generated_at, result)
    if verification.get("status") != "passed":
        add_error(result, "verification", f"Latest verification did not pass: {verification.get('report_path')}")
        return finish(root, generated_at, result)

    verified_build = verification.get("build_id")
    if build and verified_build and build != verified_build:
        add_error(result, "build", f"Build {build} is not the latest verified build: {verified_build}")
    if build and not verified_build:
        add_error(result, "build", "Latest verification does not identify a build.")
    if release and verification.get("release") not in {None, release}:
        add_error(result, "release", f"Release {release} is not covered by latest verification.")

    if result["errors"]:
        return finish(root, generated_at, result)

    result["build_id"] = build or verified_build
    result["verification_report_path"] = verification["report_path"]
    result["target"] = verification.get("target")
    result["status"] = "approved"
    result["approval_id"] = approval_id(result, generated_at)
    result["report_path"] = write_approval(root, result)
    return result


def latest_verification(root: Path) -> dict[str, Any] | None:
    reports = sorted((root / "reports" / "verification").glob("*.json"))
    if not reports:
        return None
    report_path = reports[-1]
    data = json.loads(report_path.read_text())
    data["report_path"] = str(report_path.relative_to(root))
    return data


def add_error(result: dict[str, Any], field: str, message: str) -> None:
    result["errors"].append({"field": field, "message": message, "severity": "error"})


def finish(root: Path, generated_at: str, result: dict[str, Any]) -> dict[str, Any]:
    result["status"] = "failed"
    result["summary"] = {"errors": len(result["errors"])}
    result["approval_id"] = approval_id(result, generated_at)
    result["report_path"] = write_approval(root, result)
    return result


def approval_id(result: dict[str, Any], generated_at: str) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    subject = result.get("release") or result.get("build_id") or "unapproved"
    return f"{subject}-{timestamp}"


def write_approval(root: Path, result: dict[str, Any]) -> str:
    report_path = root / "reports" / "approval" / f"{result['approval_id']}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_approval(result: dict[str, Any]) -> str:
    lines = [
        f"Approval {result['status']}",
        f"Approval ID: {result['approval_id']}",
        f"Report: {result['report_path']}",
    ]
    if result.get("build_id"):
        lines.append(f"Build ID: {result['build_id']}")
    if result.get("release"):
        lines.append(f"Release: {result['release']}")
    for error in result.get("errors", []):
        lines.append(f"- {error['field']}: {error['message']}")
    return "\n".join(lines)
