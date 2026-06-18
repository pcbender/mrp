from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.core.output import build_artifact_dir, display_path
from mrp.core.validate import validate_repository


def build_repository(
    repo: str | Path,
    release: str | None = None,
    skip_validate: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    try:
        build_id = next_build_id(root, generated_at, release)
    except ValueError as exc:
        build_id = generated_at.replace("-", "").replace(":", "").replace(".", "").replace("Z", "Z") + "-site"
        result = base_result(root, build_id, generated_at, release)
        result.update(
            {
                "status": "failed",
                "stage": "output_path",
                "message": str(exc),
                "errors": [{"field": "MRP_SITE_OUT_ROOT", "message": str(exc), "severity": "error"}],
            }
        )
        result["report_path"] = write_build_report(root, build_id, result)
        return result

    validation = None
    if not skip_validate:
        validation = validate_repository(root, release=release)
        if validation["status"] != "passed":
            result = base_result(root, build_id, generated_at, release)
            result.update(
                {
                    "status": "failed",
                    "stage": "validation",
                    "message": "Validation failed; build was not run.",
                    "validation_report_path": validation["report_path"],
                    "errors": validation["errors"],
                }
            )
            result["report_path"] = write_build_report(root, build_id, result)
            return result

    site_dir = root / "site"
    build_dir = build_artifact_dir(root, build_id)
    build_dir.mkdir(parents=True, exist_ok=True)
    command = ["npm", "run", "build", "--", "--outDir", str(build_dir)]
    env = os.environ.copy()
    env["ASTRO_TELEMETRY_DISABLED"] = "1"
    result = base_result(root, build_id, generated_at, release)
    result["validation_report_path"] = validation["report_path"] if validation else None
    result["command_line"] = command

    try:
        completed = subprocess.run(
            command,
            cwd=site_dir,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        result.update(
            {
                "status": "failed",
                "stage": "static_build",
                "message": f"Could not run static site build: {exc}",
                "stdout": "",
                "stderr": str(exc),
                "exit_code": 1,
            }
        )
        result["report_path"] = write_build_report(root, build_id, result)
        return result

    result["stdout"] = completed.stdout
    result["stderr"] = completed.stderr

    if completed.returncode != 0:
        result.update(
            {
                "status": "failed",
                "stage": "static_build",
                "message": "Static site build failed.",
                "exit_code": completed.returncode,
            }
        )
        result["report_path"] = write_build_report(root, build_id, result)
        return result

    if not build_dir.is_dir():
        result.update(
            {
                "status": "failed",
                "stage": "static_build",
                "message": f"Static site build did not create output directory: {build_dir}",
                "exit_code": 1,
            }
        )
        result["report_path"] = write_build_report(root, build_id, result)
        return result

    files = inventory_files(build_dir)
    manifest = {
        "build_id": build_id,
        "generated_at": generated_at,
        "release": release,
        "source_dist": None,
        "output_path": str(build_dir),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }
    (build_dir / "build-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    result.update(
        {
            "status": "passed",
            "stage": "complete",
            "message": "Build completed.",
            "exit_code": completed.returncode,
            "build_path": str(build_dir),
            "build_path_display": display_path(root, build_dir),
            "manifest_path": str(build_dir / "build-manifest.json"),
            "manifest_path_display": display_path(root, build_dir / "build-manifest.json"),
            "file_count": manifest["file_count"],
            "total_bytes": manifest["total_bytes"],
        }
    )
    result["report_path"] = write_build_report(root, build_id, result)
    return result


def base_result(root: Path, build_id: str, generated_at: str, release: str | None) -> dict[str, Any]:
    return {
        "command": "build",
        "repo": str(root),
        "build_id": build_id,
        "generated_at": generated_at,
        "release": release,
    }


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def next_build_id(root: Path, generated_at: str, release: str | None) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace(".", "").replace("Z", "Z")
    release_part = release or "site"
    base = f"{timestamp}-{release_part}"
    candidate = base
    index = 1
    while build_artifact_dir(root, candidate).exists() or (root / "reports" / "build" / f"{candidate}.json").exists():
        candidate = f"{base}-{index:02d}"
        index += 1
    return candidate


def inventory_files(build_dir: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(build_dir.rglob("*")):
        if not path.is_file():
            continue
        files.append(
            {
                "path": str(path.relative_to(build_dir)),
                "bytes": path.stat().st_size,
            }
        )
    return files


def write_build_report(root: Path, build_id: str, result: dict[str, Any]) -> str:
    report_path = root / "reports" / "build" / f"{build_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def format_build(result: dict[str, Any]) -> str:
    lines = [
        f"Build {result['status']}",
        f"Build ID: {result['build_id']}",
        f"Report: {result['report_path']}",
    ]
    if result.get("build_path"):
        lines.append(f"Output: {result['build_path']}")
    if result.get("message"):
        lines.append(result["message"])
    return "\n".join(lines)
