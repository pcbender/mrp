from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mrp.core.deploy import load_targets, stage_build, validate_target
from mrp.core.verify import verify_target


CONTENT_EXTENSIONS = {".yaml", ".yml", ".json"}


def publish(
    repo: str | Path,
    release: str | None = None,
    build: str | None = None,
    auto_approve: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "publish",
        "repo": str(root),
        "generated_at": generated_at,
        "release": release,
        "build_id": build,
        "auto_approve": auto_approve,
        "errors": [],
    }

    approval = matching_approval(root, release=release, build=build)
    if not approval:
        if auto_approve:
            add_error(result, "approval", "Auto-approval policy is not enabled for v0.1 publish.")
        else:
            add_error(result, "approval", "No matching approved build or release found.")
        return finish(root, generated_at, result)

    build_id = build or approval.get("build_id")
    if not build_id:
        add_error(result, "build", "Approval does not identify a build.")
        return finish(root, generated_at, result)
    result["build_id"] = build_id
    result["approval_report_path"] = approval["report_path"]
    result["release"] = release or approval.get("release")

    safety = production_safety(root)
    result["target"] = "local-production"
    result["target_path"] = safety.get("target_path")
    if safety["status"] != "passed":
        add_error(result, "safety", safety["message"])
        return finish(root, generated_at, result)

    archive_path = archive_production(root, Path(root / safety["target_path"]), generated_at)
    result["archive_path"] = archive_path

    deployment = stage_build(root, build=build_id, target="local-production")
    result["deployment_report_path"] = deployment.get("report_path")
    if deployment["status"] != "passed":
        add_error(result, "deployment", deployment["message"])
        return finish(root, generated_at, result)

    verification = verify_target(root, target="production", release=result["release"])
    result["verification_report_path"] = verification.get("report_path")
    if verification["status"] != "passed":
        add_error(result, "verification", "Production verification failed.")
        result["verification_errors"] = verification.get("errors", [])
        return finish(root, generated_at, result)

    if result["release"]:
        update_release_status(root, result["release"], "live")

    result["status"] = "published"
    result["report_path"] = write_publish_report(root, generated_at, result)
    return result


def matching_approval(root: Path, release: str | None, build: str | None) -> dict[str, Any] | None:
    reports = sorted((root / "reports" / "approval").glob("*.json"))
    for report_path in reversed(reports):
        data = json.loads(report_path.read_text())
        if data.get("status") != "approved":
            continue
        if release and data.get("release") not in {None, release}:
            continue
        if build and data.get("build_id") != build:
            continue
        data["report_path"] = str(report_path.relative_to(root))
        return data
    return None


def production_safety(root: Path) -> dict[str, Any]:
    targets, errors = load_targets(root)
    if errors:
        return {"status": "failed", "message": "; ".join(errors)}
    target = targets.get("local-production")
    if not target:
        return {"status": "failed", "message": "No local-production target configured."}
    return validate_target(root, "local-production", target)


def archive_production(root: Path, target_path: Path, generated_at: str) -> str | None:
    if not target_path.exists() or not any(target_path.iterdir()):
        return None
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    archive = root / "builds" / "archive" / f"production-{timestamp}"
    shutil.copytree(target_path, archive)
    return str(archive.relative_to(root))


def update_release_status(root: Path, release_id: str, status: str) -> None:
    for path in sorted((root / "content" / "releases").iterdir()):
        if not path.is_file() or path.suffix not in CONTENT_EXTENSIONS:
            continue
        data = json.loads(path.read_text()) if path.suffix == ".json" else yaml.safe_load(path.read_text())
        release = data.get("release", {})
        if release.get("id") != release_id:
            continue
        release["status"] = status
        if path.suffix == ".json":
            path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
        else:
            path.write_text(yaml.safe_dump(data, sort_keys=False))
        return


def add_error(result: dict[str, Any], field: str, message: str) -> None:
    result["errors"].append({"field": field, "message": message, "severity": "error"})


def finish(root: Path, generated_at: str, result: dict[str, Any]) -> dict[str, Any]:
    result["status"] = "failed"
    result["summary"] = {"errors": len(result["errors"])}
    result["report_path"] = write_publish_report(root, generated_at, result)
    return result


def write_publish_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    build_id = result.get("build_id") or "no-build"
    report_path = root / "reports" / "deployment" / f"{timestamp}-publish-{build_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_publish(result: dict[str, Any]) -> str:
    lines = [
        f"Publish {result['status']}",
        f"Build ID: {result.get('build_id') or 'none'}",
        f"Report: {result['report_path']}",
    ]
    if result.get("release"):
        lines.append(f"Release: {result['release']}")
    for error in result.get("errors", []):
        lines.append(f"- {error['field']}: {error['message']}")
    return "\n".join(lines)
