from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mrp.core.output import display_path, path_from_report, resolve_output_path


MARKER_FILE = ".allow-deploy"


def _load_env(root: Path) -> dict[str, str]:
    merged = dict(os.environ)
    dotenv_path = root / ".env"
    if dotenv_path.is_file():
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                merged.setdefault(key, value)
    return merged


def _expand_env(value: str, env: dict[str, str]) -> str:
    return re.sub(r"\$\{([^}]+)\}", lambda m: env.get(m.group(1), m.group(0)), value)


def _expand_target(config: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    return {k: _expand_env(v, env) if isinstance(v, str) else v for k, v in config.items()}


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
    target_type = target_config.get("type")

    build_record = resolve_build(root, build)
    if build_record["status"] != "passed":
        result.update(failed("build", build_record["message"]))
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result

    result["build_id"] = build_record["build_id"]
    result["build_path"] = build_record["build_path"]
    result["build_report_path"] = build_record["report_path"]
    result["release"] = build_record.get("release")

    if target_type == "local":
        safety = validate_target(root, target_name, target_config)
        result["target_path"] = safety.get("target_path")
        result["environment"] = safety.get("environment")
        if safety["status"] != "passed":
            result.update(failed("safety", safety["message"]))
            result["report_path"] = write_deployment_report(root, generated_at, result)
            return result

        source = path_from_report(root, build_record["build_path"])
        destination = path_from_report(root, safety["target_path"])
        plan = copy_plan(source, destination)
        result["plan"] = plan

        if dry_run:
            result.update({"status": "planned", "stage": "dry_run", "message": "Dry-run completed; no files were copied."})
            result["report_path"] = write_deployment_report(root, generated_at, result)
            return result

        copied = copy_build(source, destination)
        result.update({"status": "passed", "stage": "complete", "message": "Deployment completed.", "copied_files": copied})
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result

    if target_type == "rsync":
        safety = validate_rsync_target(target_name, target_config)
        result["target_path"] = safety.get("target_path")
        result["environment"] = safety.get("environment")
        if safety["status"] != "passed":
            result.update(failed("safety", safety["message"]))
            result["report_path"] = write_deployment_report(root, generated_at, result)
            return result

        source = path_from_report(root, build_record["build_path"])
        plan = copy_plan(source, None)
        result["plan"] = plan

        rsync = rsync_build(source, target_config["host"], target_config["path"], ssh_key=target_config.get("ssh_key", ""), dry_run=dry_run)
        result["rsync_output"] = rsync["stdout"] + rsync["stderr"]
        if rsync["returncode"] != 0:
            result.update(failed("deploy", f"rsync exited with code {rsync['returncode']}"))
            result["report_path"] = write_deployment_report(root, generated_at, result)
            return result

        label = "Dry-run completed; no files were transferred." if dry_run else "Deployment completed."
        result.update({"status": "planned" if dry_run else "passed", "stage": "dry_run" if dry_run else "complete", "message": label})
        result["report_path"] = write_deployment_report(root, generated_at, result)
        return result

    result.update(failed("config", f"Unsupported deploy target type: {target_type}"))
    result["report_path"] = write_deployment_report(root, generated_at, result)
    return result


def load_targets(root: Path) -> tuple[dict[str, Any], list[str]]:
    targets: dict[str, Any] = {}
    errors: list[str] = []
    for path in [root / "deploy" / "targets.yaml", root / "deploy" / "targets.local.yaml"]:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
    env = _load_env(root)
    targets = {name: _expand_target(config, env) for name, config in targets.items()}
    return targets, errors


def resolve_build(root: Path, build: str | None) -> dict[str, Any]:
    if build:
        report_path = root / "reports" / "build" / f"{build}.json"
        if not report_path.is_file():
            return failed_build(f"Unknown build report: {build}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        raw_build_path = report.get("build_path")
        if not raw_build_path:
            return failed_build(f"Build report has no build_path: {build}")
        build_path = path_from_report(root, raw_build_path)
        if not build_path.is_dir():
            return failed_build(f"Build directory is missing: {build}")
        return {
            "status": "passed",
            "build_id": build,
            "build_path": str(build_path),
            "build_path_display": display_path(root, build_path),
            "report_path": str(report_path.relative_to(root)),
            "release": report.get("release"),
        }

    reports = sorted((root / "reports" / "build").glob("*.json"))
    for report_path in reversed(reports):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("status") != "passed":
            continue
        build_id = report.get("build_id") or report_path.stem
        raw_build_path = report.get("build_path")
        if not raw_build_path:
            continue
        build_path = path_from_report(root, raw_build_path)
        if build_path.is_dir():
            return {
                "status": "passed",
                "build_id": build_id,
                "build_path": str(build_path),
                "build_path_display": display_path(root, build_path),
                "report_path": str(report_path.relative_to(root)),
                "release": report.get("release"),
            }
    return failed_build("No deployable build found.")


def validate_target(root: Path, target_name: str, config: dict[str, Any]) -> dict[str, Any]:
    raw_path = config.get("path")
    if not raw_path:
        return {"status": "failed", "message": f"Deploy target {target_name} has no path."}

    try:
        target_path = resolve_output_path(root, raw_path)
    except ValueError as exc:
        return {"status": "failed", "message": str(exc)}
    if target_path == Path("/") or target_path == Path.home():
        return {"status": "failed", "message": f"Unsafe deploy target path: {target_path}"}
    target_display = display_path(root, target_path)

    marker = target_path / MARKER_FILE
    if config.get("require_marker", True):
        if not marker.is_file():
            return {
                "status": "failed",
                "target_path": str(target_path),
                "target_path_display": target_display,
                "environment": config.get("environment"),
                "message": f"Missing deploy marker: {marker}",
            }
        expected = f"MARICOPA_RECORDS_DEPLOY_TARGET={config.get('environment', target_name)}"
        marker_text = marker.read_text(encoding="utf-8").strip().splitlines()
        if expected not in marker_text:
            return {
                "status": "failed",
                "target_path": str(target_path),
                "target_path_display": target_display,
                "environment": config.get("environment"),
                "message": f"Deploy marker does not match expected target: {expected}",
            }

    return {
        "status": "passed",
        "target_path": str(target_path),
        "target_path_display": target_display,
        "environment": config.get("environment"),
        "message": "Target passed safety checks.",
    }


def copy_plan(source: Path, destination: Path | None) -> dict[str, Any]:
    files = [path for path in sorted(source.rglob("*")) if path.is_file()]
    return {
        "source": str(source),
        "destination": str(destination) if destination is not None else None,
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


def validate_rsync_target(target_name: str, config: dict[str, Any]) -> dict[str, Any]:
    host = config.get("host", "").strip()
    path = config.get("path", "").strip()
    if not host:
        return {"status": "failed", "message": f"Deploy target {target_name} has no host."}
    if not path:
        return {"status": "failed", "message": f"Deploy target {target_name} has no path."}
    if not shutil.which("rsync"):
        return {"status": "failed", "message": "rsync not found in PATH."}
    ssh_key = config.get("ssh_key", "").strip()
    if ssh_key:
        key_path = Path(ssh_key).expanduser()
        if not key_path.is_file():
            return {"status": "failed", "message": f"SSH key not found: {key_path}"}
    if config.get("require_marker", True):
        expected = f"MARICOPA_RECORDS_DEPLOY_TARGET={config.get('environment', target_name)}"
        check = _ssh_check_marker(host, path, ssh_key, expected)
        if check["status"] != "passed":
            return {
                "status": "failed",
                "target_path": f"{host}:{path}",
                "environment": config.get("environment"),
                "message": check["message"],
            }
    return {
        "status": "passed",
        "target_path": f"{host}:{path}",
        "environment": config.get("environment"),
        "message": "Target passed safety checks.",
    }


def _ssh_check_marker(host: str, path: str, ssh_key: str, expected: str) -> dict[str, Any]:
    clean_path = path.rstrip("/")
    marker_remote = clean_path + "/" + MARKER_FILE
    # tilde must not be quoted — substitute $HOME so the remote shell expands it
    if marker_remote.startswith("~/"):
        marker_remote = "$HOME/" + marker_remote[2:]
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if ssh_key:
        cmd.extend(["-i", str(Path(ssh_key).expanduser())])
    cmd.extend([host, f"cat {marker_remote}"])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        return {"status": "failed", "message": f"Could not read remote deploy marker: {stderr or 'SSH connection failed'}"}
    marker_lines = proc.stdout.strip().splitlines()
    if expected not in marker_lines:
        return {"status": "failed", "message": f"Remote deploy marker does not match expected target: {expected}"}
    return {"status": "passed"}


def rsync_build(source: Path, host: str, path: str, ssh_key: str = "", dry_run: bool = False) -> dict[str, Any]:
    ssh_cmd = "ssh"
    if ssh_key:
        ssh_cmd = f"ssh -i {shlex.quote(str(Path(ssh_key).expanduser()))}"
    cmd = ["rsync", "-az", "--delete", "--stats", f"--exclude={MARKER_FILE}", "-e", ssh_cmd]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend([str(source).rstrip("/") + "/", f"{host}:{path}"])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


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
    if result.get("rsync_output"):
        lines.append(result["rsync_output"].strip())
    return "\n".join(lines)
