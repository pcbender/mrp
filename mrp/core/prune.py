from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from mrp.core.output import archive_root, site_out_root

try:
    import fcntl
except ImportError:  # Windows: proceed unlocked, concurrent prunes fail safe on dest-exists checks
    fcntl = None  # type: ignore[assignment]

DEFAULT_HISTORY_ROOT = Path("/mnt/nas/mrp-history")
HISTORY_MARKER = ".mrp-history-root"
DEFAULT_KEEP = 5


def history_root() -> Path:
    raw = os.environ.get("MRP_HISTORY_ROOT")
    return Path(raw).expanduser() if raw else DEFAULT_HISTORY_ROOT


def prune_outputs(
    repo: str | Path,
    keep: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    if keep is None:
        keep = int(os.environ.get("MRP_PRUNE_KEEP", str(DEFAULT_KEEP)))
    history = history_root()
    result: dict[str, Any] = {
        "command": "prune",
        "repo": str(root),
        "generated_at": generated_at,
        "keep": keep,
        "dry_run": dry_run,
        "history_root": str(history),
        "kept_builds": [],
        "protected_builds": [],
        "moved_builds": [],
        "moved_caches": [],
        "kept_archives": [],
        "moved_archives": [],
        "errors": [],
    }

    if keep < 1:
        result.update(
            {
                "status": "failed",
                "stage": "config",
                "message": f"Refusing to prune with keep={keep}; at least one build must be retained.",
            }
        )
        result["report_path"] = write_prune_report(root, generated_at, result)
        return result

    try:
        out_root = site_out_root(root)
    except ValueError as exc:
        result.update({"status": "failed", "stage": "config", "message": str(exc)})
        result["report_path"] = write_prune_report(root, generated_at, result)
        return result

    builds_root = out_root / "builds" / "staging"
    cache_root = out_root / "cache"

    # Multiple repo clones (dev checkout, admin clone) share one output root;
    # serialize prunes across them so two runs never race on the same moves.
    lock_file = acquire_prune_lock(out_root)
    if lock_file is None:
        result.update(
            {
                "status": "skipped",
                "stage": "lock",
                "message": "Another prune is already running against this output root; nothing was pruned.",
            }
        )
        result["report_path"] = write_prune_report(root, generated_at, result)
        return result

    try:
        # The history root doubles as the NAS mount point; when the share is not
        # mounted the path can still exist as an empty stub directory on the local
        # disk. The marker file distinguishes the real archive from a stub so we
        # never "move" 60G back onto the disk we are trying to relieve.
        if not (history / HISTORY_MARKER).is_file():
            result.update(
                {
                    "status": "failed",
                    "stage": "safety",
                    "message": (
                        f"History root {history} is unavailable (marker {HISTORY_MARKER} not found). "
                        "Is the NAS mounted? Nothing was pruned."
                    ),
                }
            )
            result["report_path"] = write_prune_report(root, generated_at, result)
            return result

        build_ids = sorted(p.name for p in builds_root.iterdir() if p.is_dir()) if builds_root.is_dir() else []
        # Deployment reports live in each clone's gitignored reports/ tree, so a
        # prune run from one clone cannot see the other's deployments. The target
        # directories in the shared output root carry their own build-manifest,
        # which every clone can see; protect from both.
        protected = deployed_build_ids(root) | target_build_ids(out_root)
        kept = set(build_ids[-keep:]) | (protected & set(build_ids))
        result["kept_builds"] = sorted(kept)
        result["protected_builds"] = sorted(protected & set(build_ids))

        to_move = [build_id for build_id in build_ids if build_id not in kept]
        cache_ids = sorted(p.name for p in cache_root.iterdir() if p.is_dir()) if cache_root.is_dir() else []
        cache_to_move = [cache_id for cache_id in cache_ids if cache_id not in kept]

        for build_id in to_move:
            moved = move_to_history(builds_root / build_id, history / "builds" / "staging", dry_run, result["errors"])
            if moved:
                result["moved_builds"].append(build_id)
        for cache_id in cache_to_move:
            moved = move_to_history(cache_root / cache_id, history / "cache", dry_run, result["errors"])
            if moved:
                result["moved_caches"].append(cache_id)

        # Production rollback archives: rollback always restores the newest
        # archive, so keeping the newest N preserves every rollback path it uses.
        archives_root = archive_root(root)
        archive_ids = sorted(p.name for p in archives_root.glob("production-*") if p.is_dir()) if archives_root.is_dir() else []
        result["kept_archives"] = archive_ids[-keep:]
        for archive_id in archive_ids[:-keep]:
            moved = move_to_history(archives_root / archive_id, history / "archive", dry_run, result["errors"])
            if moved:
                result["moved_archives"].append(archive_id)

        verb = "Would move" if dry_run else "Moved"
        result.update(
            {
                "status": "failed" if result["errors"] else "passed",
                "stage": "complete",
                "message": (
                    f"{verb} {len(result['moved_builds'])} build(s), {len(result['moved_caches'])} cache "
                    f"workspace(s) and {len(result['moved_archives'])} production archive(s) to {history}; "
                    f"kept {len(kept)} build(s) and {len(result['kept_archives'])} archive(s)."
                ),
            }
        )
        result["report_path"] = write_prune_report(root, generated_at, result)
        return result
    finally:
        release_prune_lock(lock_file)


def acquire_prune_lock(out_root: Path) -> IO[str] | None:
    """Take an exclusive non-blocking lock on the shared output root.

    Returns the open lock file handle (kept open to hold the lock), or None
    when another prune already holds it. Without fcntl the lock degrades to a
    no-op sentinel; concurrent moves still fail safe on dest-exists checks.
    """
    lock_path = out_root / ".prune.lock"
    try:
        lock_file = open(lock_path, "w")
    except OSError:
        return None
    if fcntl is None:
        return lock_file
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def release_prune_lock(lock_file: IO[str]) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
    finally:
        lock_file.close()


def target_build_ids(out_root: Path) -> set[str]:
    """Build ids currently deployed to local targets under the output root.

    Every deployed copy (prod/, staging/) carries the build-manifest.json of
    the build it came from. Unlike per-clone deployment reports this is
    visible to every repo clone sharing the output root.
    """
    ids: set[str] = set()
    for manifest_path in out_root.glob("*/build-manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        build_id = manifest.get("build_id")
        if build_id:
            ids.add(build_id)
    return ids


def deployed_build_ids(root: Path) -> set[str]:
    """Build ids referenced by the most recent deployment report per target."""
    reports_dir = root / "reports" / "deployment"
    if not reports_dir.is_dir():
        return set()
    latest: dict[str, str] = {}
    for report_path in sorted(reports_dir.glob("*.json")):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        target = report.get("target")
        build_id = report.get("build_id")
        if target and build_id and report.get("status") == "passed":
            latest[target] = build_id
    return set(latest.values())


def move_to_history(source: Path, dest_root: Path, dry_run: bool, errors: list[dict[str, str]]) -> bool:
    dest = dest_root / source.name
    if dest.exists():
        errors.append(
            {
                "field": source.name,
                "message": f"Destination already exists, not moving: {dest}",
                "severity": "error",
            }
        )
        return False
    if dry_run:
        return True
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
    except OSError as exc:
        errors.append({"field": source.name, "message": str(exc), "severity": "error"})
        return False
    return True


def write_prune_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace(".", "")
    report_path = root / "reports" / "prune" / f"{timestamp}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return report_path.relative_to(root).as_posix()


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def format_prune(result: dict[str, Any]) -> str:
    lines = [
        f"Prune {result['status']}",
        f"History root: {result['history_root']}",
        f"Report: {result.get('report_path', '-')}",
    ]
    if result.get("message"):
        lines.append(result["message"])
    for error in result.get("errors", []):
        lines.append(f"error [{error['field']}]: {error['message']}")
    return "\n".join(lines)
