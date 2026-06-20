from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from mrp.core.output import archive_root

CONTENT_EXTENSIONS = {".yaml", ".yml", ".json"}


def status(repo: str | Path, release: str | None = None) -> dict[str, Any]:
    root = Path(repo).resolve()
    release_record = find_release(root, release) if release else None
    if release and not release_record:
        return {
            "command": "status",
            "status": "failed",
            "repo": str(root),
            "release": release,
            "errors": [{"field": "release", "message": f"Unknown release: {release}", "severity": "error"}],
        }

    latest = {
        "validation": latest_report(root, "validation", release=release),
        "build": latest_report(root, "build", release=release),
        "staging_deployment": latest_report(root, "deployment", release=release, target="local-staging"),
        "production_deployment": latest_report(root, "deployment", release=release, target="local-production"),
        "verification": latest_report(root, "verification", release=release),
        "approval": latest_report(root, "approval", release=release),
        "publish": latest_report(root, "deployment", release=release, command="publish"),
        "rollback": latest_report(root, "rollback"),
    }
    return {
        "command": "status",
        "status": "ok",
        "repo": str(root),
        "release": release_summary(release_record) if release_record else None,
        "latest": latest,
        "rollback_available": rollback_available(root),
    }


def latest_report(
    root: Path,
    name: str,
    release: str | None = None,
    target: str | None = None,
    command: str | None = None,
) -> dict[str, Any] | None:
    reports = sorted((root / "reports" / name).glob("*.json"))
    for path in reversed(reports):
        data = json.loads(path.read_text(encoding="utf-8"))
        if release and data.get("release") not in {None, release}:
            continue
        if target and data.get("target") != target:
            continue
        if command and data.get("command") != command:
            continue
        return report_summary(root, path, data)
    return None


def report_summary(root: Path, path: Path, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_path": str(path.relative_to(root)),
        "command": data.get("command"),
        "status": data.get("status"),
        "build_id": data.get("build_id"),
        "release": data.get("release"),
        "target": data.get("target"),
        "generated_at": data.get("generated_at"),
        "approval_id": data.get("approval_id"),
        "mode": data.get("mode"),
    }


def find_release(root: Path, release_id: str | None) -> dict[str, Any] | None:
    if not release_id:
        return None
    release_dir = root / "content" / "releases"
    if not release_dir.is_dir():
        return None
    for path in sorted(release_dir.iterdir()):
        if not path.is_file() or path.suffix not in CONTENT_EXTENSIONS:
            continue
        data = json.loads(path.read_text(encoding="utf-8")) if path.suffix == ".json" else yaml.safe_load(path.read_text(encoding="utf-8"))
        release = data.get("release", {})
        if release.get("id") == release_id:
            release["file_path"] = str(path.relative_to(root))
            return release
    return None


def release_summary(release: dict[str, Any] | None) -> dict[str, Any] | None:
    if not release:
        return None
    return {
        "id": release.get("id"),
        "slug": release.get("slug"),
        "title": release.get("title"),
        "status": release.get("status"),
        "release_type": release.get("release_type"),
        "model": release.get("model"),
        "file_path": release.get("file_path"),
    }


def rollback_available(root: Path) -> bool:
    archives = archive_root(root)
    return archives.is_dir() and any(path.is_dir() for path in archives.glob("production-*"))


def format_status(result: dict[str, Any]) -> str:
    if result["status"] == "failed":
        lines = ["MRP status failed", f"Repository: {result['repo']}"]
        lines.extend(f"- {error['field']}: {error['message']}" for error in result["errors"])
        return "\n".join(lines)

    lines = ["MRP status", f"Repository: {result['repo']}"]
    if result.get("release"):
        release = result["release"]
        lines.append(f"Release: {release['id']} ({release['status']})")
    lines.append(f"Rollback available: {result['rollback_available']}")
    for name, report in result["latest"].items():
        if report:
            lines.append(f"{name}: {report['status']} ({report['report_path']})")
        else:
            lines.append(f"{name}: none")
    return "\n".join(lines)
