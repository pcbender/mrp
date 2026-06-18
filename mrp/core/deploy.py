from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


MARKER_FILE = ".allow-deploy"


def stage_build(
    repo: str | Path,
    build: str | None = None,
    target: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    target_name = target or "local-staging"
    generated_at = now_utc()

    result = {
        "command": "stage",
        "repo": str(root),
        "generated_at": generated_at,
        "target": target_name,
        "dry_run": dry_run,
    }

    targets, config_errors = load_targets(root)
    if config_errors:
        result.update(failed("config", "; ".join(config_errors)))
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result
    if target_name not in targets:
        result.update(failed("config", f"Unknown deploy target: {target_name}"))
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result

    target_config = targets[target_name]
    if target_config.get("type") != "local":
        result.update(failed("config", f"Unsupported deploy target type: {target_config.get('type')}"))
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result

    build_record = resolve_build(root, build)
    if build_record["status"] != "passed":
        result.update(failed("build", build_record["message"]))
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result

    result["build_id"] = build_record["build_id"]
    result["build_path"] = build_record["build_path"]
    result["build_report_path"] = build_record["report_path"]
    result["release"] = build_record.get("release")

    safety = validate_target(root, target_name, target_config)
    result["target_path"] = safety.get("target_path")
    result["environment"] = safety.get("environment")
    if safety["status"] != "passed":
        result.update(failed("safety", safety["message"]))
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result

    source = root / build_record["build_path"]
    destination = root / safety["target_path"]
    plan = copy_plan(source, destination)
    result["plan"] = plan

    if dry_run:
        result.update(
            {
                "status": "planned",
                "stage": "dry_run",
                "message": "Dry-run completed; no files were copied.",
            }
        )
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result

    copied = copy_build(source, destination)
    result.update(
        {
            "status": "passed",
            "stage": "complete",
            "message": "Deployment completed.",
            "copied_files": copied,
        }
    )
    result["report_path"] = write_deployment_report(root, generated_at, result)
    return result


def load_targets(root: Path) -> tuple[dict[str, Any], list[str]]:
    targets: dict[str, Any] = {}
    errors: list[str] = []
    for path in [root / "deploy" / "targets.yaml", root / "deploy" / "targets.local.yaml"]:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception as exc:  # noqa: BLE001 - converted to structured config error.
            errors.append(f"Could not parse {path}: {exc}")
            continue
        if not isinstance(data.get("targets"), dict):
            errors.append(f"{path} must contain a targets mapping.")
            continue
        targets.update(data["targets"])
    if not targets:
        errors.append("No deploy targets configured.")
    return targets, errors


def resolve_build(root: Path, build: str | None) -> dict[str, Any]:
    if build:
        report_path = root / "reports" / "build" / f"{build}.json"
        build_path = root / "builds" / "staging" / build
        if not report_path.is_file():
            return failed_build(f"Unknown build report: {build}")
        if not build_path.is_dir():
            return failed_build(f"Build directory is missing: {build}")
        report = json.loads(report_path.read_text())
        return {
            "status": "passed",
            "build_id": build,
            "build_path": str(build_path.relative_to(root)),
            "report_path": str(report_path.relative_to(root)),
            "release": report.get("release"),
        }

    reports = sorted((root / "reports" / "build").glob("*.json"))
    for report_path in reversed(reports):
        report = json.loads(report_path.read_text())
        if report.get("status") != "passed":
            continue
        build_id = report.get("build_id") or report_path.stem
        build_path = root / "builds" / "staging" / build_id
        if build_path.is_dir():
            return {
                "status": "passed",
                "build_id": build_id,
                "build_path": str(build_path.relative_to(root)),
                "report_path": str(report_path.relative_to(root)),
                "release": report.get("release"),
            }
    return failed_build("No deployable build found.")


def validate_target(root: Path, target_name: str, config: dict[str, Any]) -> dict[str, Any]:
    raw_path = config.get("path")
    if not raw_path:
        return {"status": "failed", "message": f"Deploy target {target_name} has no path."}

    target_path = (root / raw_path).resolve()
    if target_path == Path("/") or target_path == Path.home():
        return {"status": "failed", "message": f"Unsafe deploy target path: {target_path}"}
    try:
        relative_target = target_path.relative_to(root)
    except ValueError:
        return {"status": "failed", "message": f"Deploy target must be inside the repository: {target_path}"}

    marker = target_path / MARKER_FILE
    if config.get("require_marker", True):
        if not marker.is_file():
            return {
                "status": "failed",
                "target_path": str(relative_target),
                "environment": config.get("environment"),
                "message": f"Missing deploy marker: {marker}",
            }
        expected = f"MARICOPA_RECORDS_DEPLOY_TARGET={config.get('environment', target_name)}"
        marker_text = marker.read_text().strip().splitlines()
        if expected not in marker_text:
            return {
                "status": "failed",
                "target_path": str(relative_target),
                "environment": config.get("environment"),
                "message": f"Deploy marker does not match expected target: {expected}",
            }

    return {
        "status": "passed",
        "target_path": str(relative_target),
        "environment": config.get("environment"),
        "message": "Target passed safety checks.",
    }


def copy_plan(source: Path, destination: Path) -> dict[str, Any]:
    files = [path for path in sorted(source.rglob("*")) if path.is_file()]
    return {
        "source": str(source),
        "destination": str(destination),
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
    }


def copy_build(source: Path, destination: Path) -> int:
    clean_destination(destination)
    copied = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        output_path = destination / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, output_path)
        copied += 1
    return copied


def clean_destination(destination: Path) -> None:
    for path in sorted(destination.iterdir()):
        if path.name == MARKER_FILE:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def failed(stage: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "stage": stage,
        "message": message,
    }


def failed_build(message: str) -> dict[str, Any]:
    result = failed("build", message)
    result["build_id"] = None
    return result


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_deployment_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    build_id = result.get("build_id") or "no-build"
    target = result.get("target") or "unknown-target"
    report_path = root / "reports" / "deployment" / f"{timestamp}-{target}-{build_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def format_deployment(result: dict[str, Any]) -> str:
    lines = [
        f"Deployment {result['status']}",
        f"Target: {result['target']}",
        f"Report: {result['report_path']}",
    ]
    if result.get("build_id"):
        lines.append(f"Build ID: {result['build_id']}")
    if result.get("target_path"):
        lines.append(f"Target path: {result['target_path']}")
    if result.get("message"):
        lines.append(result["message"])
    return "\n".join(lines)
