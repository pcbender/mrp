"""Lightweight readiness and asset helpers for the admin Video workspace."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mrp.admin import db, video_jobs
from mrp.admin.workspace import track_units
from mrp.core.release import slugify

STEM_ROLES = ("drums", "bass", "vocals", "instruments", "other")
STEM_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".aif", ".aiff", ".m4a"})
_ROLE_KEYWORDS = (
    ("drums", frozenset({"drum", "drums", "percussion", "kick", "snare"})),
    ("bass", frozenset({"bass"})),
    ("vocals", frozenset({"vocal", "vocals", "vox", "voice"})),
    (
        "instruments",
        frozenset(
            {
                "guitar",
                "instrumental",
                "keys",
                "keyboard",
                "music",
                "piano",
                "strings",
                "synth",
            }
        ),
    ),
)


class StemImportError(ValueError):
    """A local stem directory cannot be scanned safely."""


def _stem_role(name: str) -> str:
    words = set(slugify(name).split("-"))
    return next(
        (role for role, keywords in _ROLE_KEYWORDS if words & keywords),
        "other",
    )


def scan_stem_directory(root: Path, value: object) -> list[dict[str, object]]:
    """Describe supported audio files in one local directory as editable stems."""
    text = str(value or "").strip()
    if not text:
        raise StemImportError("Enter a directory containing stem audio files.")
    directory = Path(text).expanduser()
    if not directory.is_absolute():
        directory = root / directory
    directory = directory.resolve()
    if not directory.exists():
        raise StemImportError(f"Stem directory does not exist: {directory}")
    if not directory.is_dir():
        raise StemImportError(f"Stem import path is not a directory: {directory}")

    files = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() in STEM_AUDIO_SUFFIXES
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )
    if not files:
        supported = ", ".join(sorted(STEM_AUDIO_SUFFIXES))
        raise StemImportError(
            f"No supported audio files found in {directory}. Expected: {supported}."
        )
    if len(files) > 100:
        raise StemImportError(
            f"Stem directory contains {len(files)} audio files; the import limit is 100."
        )

    stems: list[dict[str, object]] = []
    used_ids: set[str] = set()
    for path in files:
        base_id = slugify(path.stem)
        stem_id = base_id
        suffix = 2
        while stem_id in used_ids:
            stem_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(stem_id)
        stems.append(
            {
                "id": stem_id,
                "label": path.stem,
                "role": _stem_role(path.stem),
                "path": str(path.resolve()),
                "enabled": True,
            }
        )
    return stems


def track_key(release: dict[str, Any], track: dict[str, Any]) -> str:
    return f"{release.get('artist_id') or ''}--{track.get('slug') or ''}"


def resolve_asset(root: Path, value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        if candidate.is_file():
            return candidate.resolve()
        if text.startswith("/assets/"):
            public = root / "site" / "public" / text.lstrip("/")
            return public.resolve()
        return candidate.resolve()
    direct = (root / candidate).resolve()
    if direct.exists():
        return direct
    public = (root / "site" / "public" / candidate).resolve()
    return public if public.exists() else direct


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _workspace_paths(root: Path, key: str) -> dict[str, Path]:
    source = root / "assets" / "source" / "video" / key
    processed = root / "assets" / "processed" / "video" / key
    return {
        "project": source / "project.yaml",
        "aligned": source / "lyrics.aligned.yaml",
        "preflight": processed / "logs" / "preflight.json",
        "artifacts": processed / "logs" / "artifacts.json",
    }


def _artifact_state(paths: dict[str, Path], kind: str) -> bool:
    index = _read_json(paths["artifacts"])
    preflight = _read_json(paths["preflight"])
    fingerprint = preflight.get("input_fingerprint")
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list):
        return False
    return any(
        isinstance(item, dict)
        and item.get("kind") == kind
        and (not fingerprint or item.get("input_fingerprint") == fingerprint)
        for item in artifacts
    )


def _validation_state(release_path: Path, preflight_path: Path) -> tuple[str, str]:
    report = _read_json(preflight_path)
    if not report:
        return "none", "not prepared"
    try:
        if release_path.stat().st_mtime > preflight_path.stat().st_mtime:
            return "stale", "assets changed"
    except OSError:
        pass
    status = str(report.get("status") or "failed")
    if status == "passed":
        return "passed", "passed"
    errors = report.get("errors") or []
    return "failed", str(errors[0]) if errors else "failed"


def video_track_rows(root: Path, release_slug: str, release: dict[str, Any]) -> list[dict[str, Any]]:
    release_path = root / "content" / "releases" / f"{release_slug}.yaml"
    rows: list[dict[str, Any]] = []
    for unit in track_units(release):
        track = unit["track"]
        key = track_key(release, track)
        paths = _workspace_paths(root, key)
        video = track.get("music_video") if isinstance(track.get("music_video"), dict) else {}
        stems = [stem for stem in (track.get("stems") or []) if isinstance(stem, dict)]
        enabled_stems = [stem for stem in stems if stem.get("enabled", True)]
        master_value = track.get("master_path")
        master = resolve_asset(root, master_value)
        artwork = resolve_asset(root, release.get("cover_image"))
        validation, validation_detail = _validation_state(release_path, paths["preflight"])
        try:
            last_job = db.get_latest_video_job(key)
        except AssertionError:
            last_job = None
        status = str(video.get("status") or "draft")
        rows.append(
            {
                **unit,
                "track_key": key,
                "master": bool(master and master.is_file()),
                "master_path": master_value,
                "stem_count": len(stems),
                "enabled_stem_count": len(enabled_stems),
                "stems": all(
                    bool(resolve_asset(root, stem.get("path")) and resolve_asset(root, stem.get("path")).is_file())
                    for stem in enabled_stems
                ),
                "lyrics": bool(track.get("lyrics_text")) or bool(track.get("instrumental")),
                "artwork": bool(artwork and artwork.is_file()),
                "project": paths["project"].is_file(),
                "timing": paths["aligned"].is_file(),
                "cast": status in {"cast", "previewed", "rendered", "approved", "published"},
                "preview": validation == "passed"
                and (
                    status in {"previewed", "rendered", "approved", "published"}
                    or _artifact_state(paths, "preview")
                ),
                "render": validation == "passed"
                and (
                    status in {"rendered", "approved", "published"}
                    or _artifact_state(paths, "render")
                ),
                "approval": status in {"approved", "published"},
                "video_status": status,
                "validation": validation,
                "validation_detail": validation_detail,
                "last_job": last_job,
            }
        )
    return rows


def video_stage_status(root: Path, release_slug: str, release: dict[str, Any]) -> dict[str, str]:
    rows = video_track_rows(root, release_slug, release)
    requested = [row for row in rows if row["project"] or row["track"].get("music_video")]
    if not requested:
        return {"state": "todo", "detail": "optional"}
    rendered = sum(1 for row in requested if row["render"])
    state = "done" if rendered == len(requested) else "partial"
    return {"state": state, "detail": f"{rendered}/{len(requested)} videos"}


def _probe(path: Path, entries: str, *, select: str | None = None) -> dict[str, Any]:
    command = ["ffprobe", "-v", "error"]
    if select:
        command.extend(["-select_streams", select])
    command.extend(["-show_entries", entries, "-of", "json", str(path)])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or f"ffprobe rejected {path.name}")
    value = json.loads(result.stdout)
    return value if isinstance(value, dict) else {}


def _audio_duration(path: Path) -> float:
    payload = _probe(path, "format=duration")
    try:
        return float((payload.get("format") or {})["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"ffprobe returned no duration for {path.name}") from exc


def _default_font() -> Path | None:
    configured = os.environ.get("MRP_VIDEO_FONT")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    return next((path.resolve() for path in candidates if path and path.is_file()), None)


def validate_assets(
    root: Path,
    release: dict[str, Any],
    unit: dict[str, Any],
) -> dict[str, Any]:
    """Perform the Video-stage preflight without importing the renderer stack."""
    track = unit["track"]
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    renderer_ready, renderer_detail = video_jobs.renderer_environment(root)
    record("Renderer Python", renderer_ready, renderer_detail)
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    record("FFmpeg", bool(ffmpeg), ffmpeg or "not on PATH")
    record("ffprobe", bool(ffprobe), ffprobe or "not on PATH")

    master_value = track.get("master_path")
    master = resolve_asset(root, master_value)
    record("Master", bool(master and master.is_file()), str(master_value or "not configured"))

    stems = [stem for stem in (track.get("stems") or []) if isinstance(stem, dict)]
    enabled = [stem for stem in stems if stem.get("enabled", True)]
    missing_stems = [
        str(stem.get("id") or "unnamed")
        for stem in enabled
        if not (resolve_asset(root, stem.get("path")) and resolve_asset(root, stem.get("path")).is_file())
    ]
    record(
        "Stems",
        not missing_stems,
        f"{len(enabled)} enabled" if not missing_stems else f"missing: {', '.join(missing_stems)}",
    )

    has_lyrics = bool(track.get("lyrics_text")) or bool(track.get("instrumental"))
    record("Lyrics", has_lyrics, "instrumental" if track.get("instrumental") else ("present" if has_lyrics else "missing"))

    cover_value = release.get("cover_image")
    cover = resolve_asset(root, cover_value)
    record("Artwork", bool(cover and cover.is_file()), str(cover_value or "not configured"))
    font = _default_font()
    record("Font", bool(font), str(font or "set MRP_VIDEO_FONT"))

    if ffprobe and master and master.is_file():
        try:
            master_duration = _audio_duration(master)
            record("Master audio", True, f"decodable, {master_duration:.3f}s")
            duration_errors: list[str] = []
            for stem in enabled:
                path = resolve_asset(root, stem.get("path"))
                if not path or not path.is_file():
                    continue
                duration = _audio_duration(path)
                difference = abs(duration - master_duration)
                if difference > 0.05:
                    duration_errors.append(
                        f"{stem.get('id')}: {difference:.3f}s difference"
                    )
            record(
                "Stem duration",
                not duration_errors,
                "within 0.050s" if not duration_errors else "; ".join(duration_errors),
            )
        except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            record("Audio decode", False, str(exc))

    if ffprobe and cover and cover.is_file():
        try:
            payload = _probe(cover, "stream=width,height", select="v:0")
            streams = payload.get("streams") or []
            width = int(streams[0]["width"])
            height = int(streams[0]["height"])
            record("Artwork image", width > 0 and height > 0, f"{width}x{height}")
        except (IndexError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            record("Artwork image", False, str(exc))

    return {
        "status": "passed" if not errors else "failed",
        "checks": checks,
        "errors": errors,
    }
