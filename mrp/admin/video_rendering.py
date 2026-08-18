"""Draft/full render history and stale-safe approval for track videos."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mrp.admin.video_workspace import (
    resolve_asset,
    stem_selection_drift,
    track_key,
)
from mrp.core.release import effective_master_path


class VideoRenderingError(Exception):
    def __init__(self, *problems: str):
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


def _paths(root: Path, release: dict[str, Any], track: dict[str, Any]) -> dict[str, Path]:
    key = track_key(release, track)
    source = root / "assets" / "source" / "video" / key
    processed = root / "assets" / "processed" / "video" / key
    return {
        "release": root / "content" / "releases" / f"{release.get('slug')}.yaml",
        "project": source / "project.yaml",
        "aligned": source / "lyrics.aligned.yaml",
        "preflight": processed / "logs" / "preflight.json",
        "artifacts": processed / "logs" / "artifacts.json",
        "approval": processed / "logs" / "approval.json",
        "renders": processed / "renders",
    }


def renders_path(root: Path, release: dict[str, Any], track: dict[str, Any]) -> Path:
    return _paths(root, release, track)["renders"]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise VideoRenderingError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _current_preflight(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    paths = _paths(root, release, track)
    preflight = _read_json(paths["preflight"])
    problems: list[str] = []
    if preflight.get("status") != "passed":
        problems.append("current video preflight has not passed")
    fingerprint = preflight.get("input_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        problems.append("video preflight has no input fingerprint")
    # Every consumed file is re-hashed individually below, which already covers
    # content drift and reports it per input. The one thing hashes cannot see is
    # the track naming a different set of stems than preparation recorded.
    selection = stem_selection_drift(track, preflight)
    if selection is not None:
        problems.append(selection)
    expected_project_hash = preflight.get("project_hash")
    if paths["project"].is_file() and isinstance(expected_project_hash, str):
        if _hash_file(paths["project"]) != expected_project_hash:
            problems.append("versioned project changed after preflight")
    else:
        problems.append("versioned project or its preflight hash is missing")
    input_hashes = preflight.get("input_hashes")
    if not isinstance(input_hashes, dict):
        problems.append("video preflight input hashes are missing")
        input_hashes = {}
    expected_aligned = input_hashes.get("lyrics.aligned")
    if isinstance(expected_aligned, str):
        if not paths["aligned"].is_file() or _hash_file(paths["aligned"]) != expected_aligned:
            problems.append("aligned timing changed after preflight")
    master = resolve_asset(root, effective_master_path(release, track))
    expected_master = input_hashes.get("audio.master")
    if isinstance(expected_master, str):
        if master is None or not master.is_file() or _hash_file(master) != expected_master:
            problems.append("track master changed after preflight")
    for stem in track.get("stems") or []:
        if not isinstance(stem, dict) or stem.get("enabled", True) is False:
            continue
        stem_id = str(stem.get("id") or "")
        expected = input_hashes.get(f"audio.stem.{stem_id}")
        path = resolve_asset(root, stem.get("path"))
        if isinstance(expected, str) and (
            path is None or not path.is_file() or _hash_file(path) != expected
        ):
            problems.append(f"stem {stem_id} changed after preflight")
    return preflight, tuple(dict.fromkeys(problems))


def _sections(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    sections = value.get("sections") if isinstance(value, dict) else None
    if not isinstance(sections, list):
        return []
    result = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        try:
            start = float(section["start"])
            end = float(section["end"])
        except (KeyError, TypeError, ValueError):
            continue
        result.append(
            {
                "id": str(section.get("id") or ""),
                "type": str(section.get("type") or ""),
                "label": str(
                    section.get("label")
                    or str(section.get("type") or "section").replace("_", " ").title()
                ),
                "start": start,
                "end": end,
            }
        )
    return result


def _safe_artifact(
    root: Path,
    render_root: Path,
    artifact: dict[str, Any],
) -> tuple[Path, Path] | None:
    value = artifact.get("path")
    if not isinstance(value, str):
        return None
    output = (root / value).resolve()
    try:
        output.relative_to(render_root.resolve())
    except ValueError:
        return None
    manifest = output.with_suffix(".render.json")
    return output, manifest


def _iterations(
    root: Path,
    paths: dict[str, Path],
    preflight: dict[str, Any],
    kind: str,
    *,
    preflight_current: bool,
) -> list[dict[str, Any]]:
    index = _read_json(paths["artifacts"])
    fingerprint = preflight.get("input_fingerprint")
    iterations = []
    for artifact in index.get("artifacts") or []:
        if not isinstance(artifact, dict) or artifact.get("kind") != kind:
            continue
        resolved = _safe_artifact(root, paths["renders"], artifact)
        if resolved is None:
            continue
        output, manifest = resolved
        details = artifact.get("details") if isinstance(artifact.get("details"), dict) else {}
        manifest_payload = _read_json(manifest)
        current = bool(
            preflight_current
            and fingerprint
            and artifact.get("input_fingerprint") == fingerprint
        )
        iterations.append(
            {
                "id": str(details.get("render_id") or output.stem),
                "path": output.relative_to(root).as_posix(),
                "name": output.name,
                "group": output.parent.name,
                "manifest_path": manifest.relative_to(root).as_posix(),
                "exists": output.is_file(),
                "manifest_exists": manifest.is_file(),
                "current": current,
                "stale": not current,
                "verified": bool(
                    details.get("verified")
                    and manifest_payload.get("verification", {}).get("valid") is True
                ),
                "recorded_at": artifact.get("recorded_at"),
                "duration": details.get("duration"),
                "frame_count": details.get("frame_count"),
                "width": details.get("width"),
                "height": details.get("height"),
                "fps": details.get("fps"),
                "video_codec": details.get("video_codec"),
                "audio_codec": details.get("audio_codec"),
                "performance": details.get("performance") or {},
                "source_start": manifest_payload.get("timeline", {}).get("source_start"),
                "source_end": manifest_payload.get("timeline", {}).get("source_end"),
                "output_sha256": manifest_payload.get("output", {}).get("sha256"),
            }
        )
    return sorted(
        iterations,
        key=lambda item: str(item.get("recorded_at") or ""),
        reverse=True,
    )


def _plan(
    job: dict[str, Any] | None,
    fingerprint: object,
    *,
    preflight_current: bool,
) -> dict[str, Any] | None:
    if not job or job.get("status") != "done" or not job.get("output"):
        return None
    try:
        result = json.loads(str(job["output"]))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict) or not isinstance(result.get("render_plan"), dict):
        return None
    planned_fingerprint = (result.get("preflight") or {}).get("input_fingerprint")
    return {
        **result["render_plan"],
        "job_id": job.get("id"),
        "input_fingerprint": planned_fingerprint,
        "current": bool(
            preflight_current
            and fingerprint
            and planned_fingerprint == fingerprint
        ),
    }


def load_rendering(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    *,
    plan_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths = _paths(root, release, track)
    preflight, problems = _current_preflight(root, release, track)
    sections = _sections(paths["aligned"])
    approval = _read_json(paths["approval"])
    fingerprint = preflight.get("input_fingerprint")
    approval["current"] = bool(
        approval.get("status") == "approved"
        and fingerprint
        and approval.get("input_fingerprint") == fingerprint
        and not problems
    )
    return {
        "preflight": preflight,
        "preflight_current": not problems,
        "preflight_problems": list(problems),
        "sections": sections,
        "master_duration": preflight.get("master_duration"),
        "plan": _plan(plan_job, fingerprint, preflight_current=not problems),
        "drafts": _iterations(
            root,
            paths,
            preflight,
            "draft",
            preflight_current=not problems,
        ),
        "renders": _iterations(
            root,
            paths,
            preflight,
            "render",
            preflight_current=not problems,
        ),
        "approval": approval,
    }


def render_launch_problems(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    *,
    plan_job: dict[str, Any] | None = None,
    require_plan: bool = False,
) -> tuple[str, ...]:
    preflight, problems = _current_preflight(root, release, track)
    result = list(problems)
    if problems:
        # Every problem above describes an input that moved on; none of them
        # say what to do about it. Building the render plan consumes a preflight
        # rather than producing one, and nothing on this page refreshes one, so
        # without this the button reads as broken rather than blocked.
        result.append(
            "run Prepare on the track page to refresh the preflight, then retry here"
        )
    status = str((track.get("music_video") or {}).get("status") or "draft")
    if status not in {"cast", "previewed", "rendered"}:
        result.append("track must have a reviewed cast before rendering")
    if require_plan:
        plan = _plan(
            plan_job,
            preflight.get("input_fingerprint"),
            preflight_current=not problems,
        )
        if plan is None:
            result.append("build the render plan first")
        elif not plan["current"]:
            result.append("the render plan is stale; rebuild it")
    return tuple(dict.fromkeys(result))


def approve_render(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    artifact_path: str,
) -> dict[str, Any]:
    paths = _paths(root, release, track)
    preflight, problems = _current_preflight(root, release, track)
    if problems:
        raise VideoRenderingError(*problems)
    index = _read_json(paths["artifacts"])
    artifact = next(
        (
            item
            for item in index.get("artifacts") or []
            if isinstance(item, dict)
            and item.get("kind") == "render"
            and item.get("path") == artifact_path
        ),
        None,
    )
    if artifact is None:
        raise VideoRenderingError("full render is not present in the artifact index")
    fingerprint = preflight.get("input_fingerprint")
    if artifact.get("input_fingerprint") != fingerprint:
        raise VideoRenderingError("full render was made from a stale project fingerprint")
    resolved = _safe_artifact(root, paths["renders"], artifact)
    if resolved is None:
        raise VideoRenderingError("full render path escapes the track workspace")
    output, manifest_path = resolved
    if output.parent.name != "full":
        raise VideoRenderingError("refusing to approve a non-full render path")
    if not output.is_file() or not manifest_path.is_file():
        raise VideoRenderingError("full render or its render manifest is missing")
    manifest = _read_json(manifest_path)
    details = artifact.get("details") if isinstance(artifact.get("details"), dict) else {}
    if details.get("draft") is not False or details.get("verified") is not True:
        raise VideoRenderingError("artifact is not a verified full render")
    if manifest.get("timeline", {}).get("draft") is not False:
        raise VideoRenderingError("render manifest describes a draft render")
    if manifest.get("verification", {}).get("valid") is not True:
        raise VideoRenderingError("render manifest is not verified")
    expected_hash = manifest.get("output", {}).get("sha256")
    if not isinstance(expected_hash, str) or _hash_file(output) != expected_hash:
        raise VideoRenderingError("full render hash does not match its manifest")
    approval = {
        "version": 1,
        "status": "approved",
        "approved_at": datetime.now(UTC).isoformat(),
        "track_key": track_key(release, track),
        "input_fingerprint": fingerprint,
        "project_hash": preflight.get("project_hash"),
        "input_hashes": preflight.get("input_hashes"),
        "artifact_path": output.relative_to(root).as_posix(),
        "manifest_path": manifest_path.relative_to(root).as_posix(),
        "manifest_sha256": _hash_file(manifest_path),
        "output_sha256": expected_hash,
    }
    _write_json_atomic(paths["approval"], approval)
    return approval


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def discard_draft(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    draft_id: str,
) -> dict[str, Any]:
    paths = _paths(root, release, track)
    index = _read_json(paths["artifacts"])
    artifact = next(
        (
            item
            for item in index.get("artifacts") or []
            if isinstance(item, dict)
            and item.get("kind") == "draft"
            and str((item.get("details") or {}).get("render_id") or "") == draft_id
        ),
        None,
    )
    if artifact is None:
        raise VideoRenderingError(f"draft iteration not found: {draft_id}")
    resolved = _safe_artifact(root, paths["renders"], artifact)
    if resolved is None:
        raise VideoRenderingError("draft path escapes the track workspace")
    output, manifest = resolved
    if output.parent.name != "drafts":
        raise VideoRenderingError("refusing to discard a non-draft render")
    output.unlink(missing_ok=True)
    manifest.unlink(missing_ok=True)
    artifacts = index.get("artifacts") or []
    index["artifacts"] = [item for item in artifacts if item is not artifact]
    _write_json_atomic(paths["artifacts"], index)
    return {"draft_id": draft_id, "discarded": True}
