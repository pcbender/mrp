"""Durable public-media references copied into immutable site builds."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from mrp.core.output import assert_outside_repo

PUBLIC_URL_PREFIX = "/media/"
DEFAULT_PUBLIC_MEDIA_ROOT = Path.home() / ".mrp" / "public-media" / "maricoparecords"


class PublicMediaError(Exception):
    pass


def public_media_root(repo_root: str | Path) -> Path:
    repo = Path(repo_root).resolve()
    raw = os.environ.get("MRP_PUBLIC_MEDIA_ROOT")
    root = Path(raw).expanduser() if raw else DEFAULT_PUBLIC_MEDIA_ROOT
    root = root.resolve()
    if root == Path(root.anchor):
        raise PublicMediaError("refusing to use a filesystem root as public-media storage")
    try:
        assert_outside_repo(repo, root)
    except ValueError as exc:
        raise PublicMediaError(str(exc)) from exc
    return root


def public_video_enabled(track: dict[str, Any]) -> bool:
    video = track.get("music_video")
    return bool(
        isinstance(video, dict)
        and video.get("opt_in") is True
        and video.get("status") == "published"
        and isinstance(video.get("public_url"), str)
        and video.get("public_url")
        and isinstance(video.get("poster"), str)
        and video.get("poster")
    )


def _tracks(release: dict[str, Any]) -> list[dict[str, Any]]:
    tracks = release.get("tracks")
    if isinstance(tracks, list):
        return [track for track in tracks if isinstance(track, dict)]
    song = release.get("song")
    return [song] if isinstance(song, dict) else []


def _release_records(root: Path) -> list[dict[str, Any]]:
    directory = root / "content" / "releases"
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.casefold() not in {".json", ".yaml", ".yml"}:
            continue
        try:
            document = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.suffix.casefold() == ".json"
                else yaml.safe_load(path.read_text(encoding="utf-8"))
            )
            release = (document.get("release") or {}) if isinstance(document, dict) else {}
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            raise PublicMediaError(f"cannot read public-media release {path}: {exc}") from exc
        if isinstance(release, dict):
            records.append(release)
    return records


def local_media_relative(value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        raise PublicMediaError("an opted-in public media reference is blank")
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return None
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise PublicMediaError(f"invalid public media reference: {text}")
    if not parsed.path.startswith(PUBLIC_URL_PREFIX):
        raise PublicMediaError(
            f"local public media must begin with {PUBLIC_URL_PREFIX}: {text}"
        )
    relative = Path(parsed.path.removeprefix(PUBLIC_URL_PREFIX))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise PublicMediaError(f"unsafe public media reference: {text}")
    return relative


def resolve_public_media(repo_root: str | Path, value: object) -> Path | None:
    relative = local_media_relative(value)
    if relative is None:
        return None
    root = public_media_root(repo_root)
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PublicMediaError(f"public media reference escapes its store: {value}") from exc
    return resolved


def referenced_public_media(repo_root: str | Path) -> list[tuple[Path, Path]]:
    repo = Path(repo_root).resolve()
    references: dict[str, tuple[Path, Path]] = {}
    for release in _release_records(repo):
        for track in _tracks(release):
            if not public_video_enabled(track):
                continue
            video = track["music_video"]
            for field in ("public_url", "poster"):
                relative = local_media_relative(video.get(field))
                if relative is None:
                    continue
                source = resolve_public_media(repo, video[field])
                if source is None or not source.is_file():
                    raise PublicMediaError(
                        f"opted-in {field} is missing from durable media: {video[field]}"
                    )
                references[relative.as_posix()] = (source, Path("media") / relative)
    return [references[key] for key in sorted(references)]
