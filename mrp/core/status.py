from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPORT_TYPES = ["build", "deployment", "verification", "approval"]


def status(repo: str | Path) -> dict[str, Any]:
    root = Path(repo).resolve()
    latest = {name: latest_report(root, name) for name in REPORT_TYPES}
    return {
        "command": "status",
        "status": "ok",
        "repo": str(root),
        "latest": latest,
    }


def latest_report(root: Path, name: str) -> dict[str, Any] | None:
    reports = sorted((root / "reports" / name).glob("*.json"))
    if not reports:
        return None
    path = reports[-1]
    data = json.loads(path.read_text())
    return {
        "report_path": str(path.relative_to(root)),
        "status": data.get("status"),
        "build_id": data.get("build_id"),
        "release": data.get("release"),
        "target": data.get("target"),
        "generated_at": data.get("generated_at"),
        "approval_id": data.get("approval_id"),
        "mode": data.get("mode"),
    }


def format_status(result: dict[str, Any]) -> str:
    lines = ["MRP status", f"Repository: {result['repo']}"]
    for name, report in result["latest"].items():
        if report:
            lines.append(f"{name}: {report['status']} ({report['report_path']})")
        else:
            lines.append(f"{name}: none")
    return "\n".join(lines)
