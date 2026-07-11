"""Phase-2 workflow state for the Changes publishing pipeline.

Tracks the staging (and, in Phase 3, production) deploy + verification state of
the *working tree*, keyed to a content signature so that any edit after a
verify silently invalidates it. State is persisted outside git in
``~/.mrp/changes-workflow.json``, keyed by repo root (the metrics.db pattern).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.admin import gitops

STATE_DIR = Path.home() / ".mrp"
STATE_PATH = STATE_DIR / "changes-workflow.json"

STAGING_URL = os.environ.get("MRP_STAGING_URL", "https://staging.maricoparecords.com").rstrip("/")
PRODUCTION_URL = os.environ.get("MRP_PRODUCTION_URL", "https://www.maricoparecords.com").rstrip("/")
STAGING_TARGET = "remote-staging"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def working_signature(root: Path) -> str:
    """A stable short hash of the current managed working-tree changes.

    Empty string when the tree is clean. Any content edit, add, or delete
    under content/ or assets/ changes the signature.
    """
    changes = gitops.data_changes(root)
    parts: list[str] = []
    for c in sorted(changes, key=lambda x: x["path"]):
        path = c["path"]
        fpath = root / path
        if c.get("label") == "deleted" or not fpath.exists():
            parts.append(f"{path}:DELETED")
            continue
        try:
            blob = gitops._git(root, "hash-object", "--", path).stdout.strip()
        except gitops.GitError:
            blob = str(fpath.stat().st_mtime)
        parts.append(f"{path}:{c.get('label')}:{blob}")
    if not parts:
        return ""
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


# --- persistence -------------------------------------------------------------

def _load_all() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_all(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_state(root: Path) -> dict[str, Any]:
    return _load_all().get(str(root.resolve()), {})


def save_state(root: Path, state: dict[str, Any]) -> None:
    data = _load_all()
    data[str(root.resolve())] = state
    _save_all(data)


def record_staging(root: Path, signature: str, build_id: str | None,
                   report: str | None, status: str) -> None:
    """Persist a completed staging deploy; a new deploy clears production state."""
    state = load_state(root)
    state["staging"] = {
        "signature": signature,
        "build_id": build_id,
        "report": report,
        "status": status,
        "deployed_at": _now(),
        "verified": False,
        "verified_signature": None,
    }
    state.pop("production", None)
    save_state(root, state)


def mark_staging_verified(root: Path, signature: str) -> bool:
    """Mark staging verified iff its deploy matches the given (current) signature."""
    state = load_state(root)
    staging = state.get("staging")
    if not staging or staging.get("signature") != signature or not signature:
        return False
    staging["verified"] = True
    staging["verified_signature"] = signature
    save_state(root, state)
    return True


# --- derived status for the panel -------------------------------------------

def workflow_status(root: Path) -> dict[str, Any]:
    """Current staging state relative to the live working-tree signature."""
    signature = working_signature(root)
    staging = (load_state(root).get("staging")) or {}
    staged_current = bool(signature and staging.get("status") == "passed"
                          and staging.get("signature") == signature)
    staging_stale = bool(staging.get("build_id") and staging.get("signature") != signature)
    staging_verified = bool(staged_current and staging.get("verified")
                            and staging.get("verified_signature") == signature)
    return {
        "signature": signature,
        "staging": staging,
        "staged_current": staged_current,
        "staging_stale": staging_stale,
        "staging_verified": staging_verified,
        "staging_url": STAGING_URL,
    }


def affected_pages(changes: list[dict], base_url: str) -> list[dict[str, str]]:
    """Public page URLs touched by the given changes (releases + artists)."""
    seen: dict[str, str] = {}
    for c in changes:
        kind = c.get("kind")
        if kind in ("release", "release-asset") and c.get("release_slug"):
            seen[f"/releases/{c['release_slug']}/"] = c.get("entity_title") or c["release_slug"]
        elif kind in ("artist", "artist-asset") and c.get("entity_id"):
            seen[f"/artists/{c['entity_id']}/"] = c.get("entity_title") or c["entity_id"]
    return [{"url": base_url + path, "path": path, "label": label}
            for path, label in sorted(seen.items())]


def run_staging_deploy(root_str: str, signature: str) -> dict[str, Any]:
    """Background-job body: build the whole site, then rsync to staging.

    On success, records staging state against ``signature``. Returns a compact
    result the poll template renders.
    """
    from mrp.core.build import build_repository
    from mrp.core.deploy import stage_build

    root = Path(root_str)
    build = build_repository(root)
    if build.get("status") != "passed":
        return {"stage": "build", "status": "failed",
                "message": build.get("message") or "Build failed.",
                "errors": build.get("errors") or []}

    deploy = stage_build(root, build=build.get("build_id"), target=STAGING_TARGET)
    result = {
        "stage": "deploy",
        "status": deploy.get("status"),
        "build_id": build.get("build_id"),
        "target": deploy.get("target"),
        "message": deploy.get("message"),
        "report": deploy.get("report_path"),
    }
    if deploy.get("status") == "passed":
        record_staging(root, signature, build.get("build_id"), deploy.get("report_path"), "passed")
    return result
