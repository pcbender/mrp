"""Workflow state for the Changes publishing pipeline.

Tracks the staging and production deploy + verification state of the managed
content tree, keyed to a content-state signature so that any edit after a
verify silently invalidates it. The signature covers the *effective* content
(index blobs overlaid with working-tree edits), so committing pending changes
does not invalidate a verified deploy — publishing and git commit are
independent (Phase 4). State is persisted outside git in
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
PRODUCTION_TARGET = "remote-production"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def working_signature(root: Path) -> str:
    """A stable short hash of the managed content state.

    Covers the *effective* content: every indexed file's blob overlaid with
    working-tree edits, adds, and deletes. Because git blob hashes are
    content-addressed, committing pending changes leaves the signature
    unchanged — staged/verified state survives a commit. Any content edit,
    add, or delete changes it. Empty only when there is no managed content.
    """
    try:
        indexed = gitops._git(root, "ls-files", "-s", "--", *gitops.DATA_PATHSPECS).stdout
    except gitops.GitError:
        indexed = ""
    blobs: dict[str, str] = {}
    for line in indexed.splitlines():
        # "<mode> <blob-sha> <stage>\t<path>"
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if path and len(fields) >= 2:
            blobs[path] = fields[1]
    for c in gitops.data_changes(root):
        path = c["path"]
        fpath = root / path
        if c.get("label") == "deleted" or not fpath.exists():
            blobs.pop(path, None)
            continue
        try:
            blobs[path] = gitops._git(root, "hash-object", "--", path).stdout.strip()
        except gitops.GitError:
            blobs[path] = str(fpath.stat().st_mtime)
    if not blobs:
        return ""
    joined = "\n".join(f"{path}:{blob}" for path, blob in sorted(blobs.items()))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


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


def record_production(root: Path, signature: str, build_id: str | None,
                      deploy_report: str | None, verify_report: str | None,
                      status: str) -> None:
    """Persist a completed production deploy (same build that was staged)."""
    state = load_state(root)
    state["production"] = {
        "signature": signature,
        "build_id": build_id,
        "deploy_report": deploy_report,
        "verify_report": verify_report,
        "status": status,
        "deployed_at": _now(),
        "verified": False,
        "verified_signature": None,
    }
    save_state(root, state)


def mark_production_verified(root: Path, signature: str) -> bool:
    """Mark production verified iff its deploy matches the given (current) signature."""
    state = load_state(root)
    production = state.get("production")
    if not production or production.get("signature") != signature or not signature:
        return False
    production["verified"] = True
    production["verified_signature"] = signature
    save_state(root, state)
    return True


def clear_state(root: Path) -> None:
    """Drop all workflow state for this root (manual reset; commits keep state)."""
    data = _load_all()
    if data.pop(str(root.resolve()), None) is not None:
        _save_all(data)


# --- derived status for the panel -------------------------------------------

def workflow_status(root: Path) -> dict[str, Any]:
    """Staging + production state relative to the live content signature.

    Every "verified" flag is only honored while its signature still matches the
    current content state, so any edit silently invalidates the whole ladder —
    but a commit of that same content does not (the signature is invariant
    across commits).
    """
    signature = working_signature(root)
    state = load_state(root)
    staging = state.get("staging") or {}
    production = state.get("production") or {}

    staged_current = bool(signature and staging.get("status") == "passed"
                          and staging.get("signature") == signature)
    staging_stale = bool(staging.get("build_id") and staging.get("signature") != signature)
    staging_verified = bool(staged_current and staging.get("verified")
                            and staging.get("verified_signature") == signature)

    prod_current = bool(signature and production.get("status") == "passed"
                        and production.get("signature") == signature)
    production_stale = bool(production.get("build_id") and production.get("signature") != signature)
    production_verified = bool(prod_current and production.get("verified")
                               and production.get("verified_signature") == signature)

    return {
        "signature": signature,
        "staging": staging,
        "production": production,
        "staged_current": staged_current,
        "staging_stale": staging_stale,
        "staging_verified": staging_verified,
        "prod_current": prod_current,
        "production_stale": production_stale,
        "production_verified": production_verified,
        "staging_url": STAGING_URL,
        "production_url": PRODUCTION_URL,
        "staged_build_id": staging.get("build_id"),
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


def run_production_deploy(root_str: str, signature: str, build_id: str | None) -> dict[str, Any]:
    """Background-job body: rsync the *already-staged* build to production, then
    run verify_target as a safety net. Records production state on success.
    """
    from mrp.core.deploy import stage_build
    from mrp.core.verify import verify_target

    root = Path(root_str)
    if not build_id:
        return {"stage": "build", "status": "failed",
                "message": "No staged build to promote — deploy to staging first."}

    deploy = stage_build(root, build=build_id, target=PRODUCTION_TARGET)
    result = {
        "stage": "deploy",
        "status": deploy.get("status"),
        "build_id": build_id,
        "target": deploy.get("target"),
        "message": deploy.get("message"),
        "report": deploy.get("report_path"),
    }
    if deploy.get("status") != "passed":
        return result

    verification = verify_target(root, target=PRODUCTION_TARGET)
    result["verify_status"] = verification.get("status")
    result["verify_report"] = verification.get("report_path")
    if verification.get("status") != "passed":
        result["status"] = "failed"
        result["stage"] = "verify"
        result["message"] = "Production verification failed."
        result["verify_errors"] = verification.get("errors", [])
        return result

    record_production(root, signature, build_id, deploy.get("report_path"),
                      verification.get("report_path"), "passed")
    return result
