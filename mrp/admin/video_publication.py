"""Publish approved track videos into durable, build-mounted public media."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mrp.admin.video_rendering import VideoRenderingError, approve_render
from mrp.admin.video_workspace import resolve_asset, track_key
from mrp.core.public_media import (
    PublicMediaError,
    public_media_root,
    resolve_public_media,
)

_POSTER_EXTENSIONS = {".avif", ".jpg", ".jpeg", ".png", ".svg", ".webp"}
_TRACK_KEY = re.compile(r"^[a-z0-9][a-z0-9-]*--[a-z0-9][a-z0-9-]*$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class VideoPublicationError(Exception):
    def __init__(self, *problems: str):
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    track_key: str
    video_source: Path
    poster_source: Path
    video_destination: Path
    poster_destination: Path
    public_url: str
    poster_url: str
    output_sha256: str
    poster_sha256: str
    approval: dict[str, Any]
    publication_record: Path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise VideoPublicationError(f"cannot hash publication input {path}: {exc}") from exc
    return digest.hexdigest()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return value if isinstance(value, dict) else {}


def _approval_path(root: Path, key: str) -> Path:
    return root / "assets" / "processed" / "video" / key / "logs" / "approval.json"


def _publication_record(root: Path, key: str) -> Path:
    return root / "assets" / "source" / "video" / key / "publication.yaml"


def plan_publication(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
) -> PublicationPlan:
    repo = root.resolve()
    key = track_key(release, track)
    if not _TRACK_KEY.fullmatch(key):
        raise VideoPublicationError("release artist and track slug do not form a safe track key")
    video = track.get("music_video")
    if not isinstance(video, dict) or video.get("status") not in {"approved", "published"}:
        raise VideoPublicationError("a verified full render must be approved before publication")
    existing_approval = _read_yaml(_approval_path(repo, key))
    artifact_path = existing_approval.get("artifact_path")
    if existing_approval.get("status") != "approved" or not isinstance(artifact_path, str):
        raise VideoPublicationError("current render approval record is missing")
    try:
        approval = approve_render(repo, release, track, artifact_path)
    except VideoRenderingError as exc:
        raise VideoPublicationError(*exc.problems) from exc

    video_source = (repo / str(approval["artifact_path"])).resolve()
    try:
        video_source.relative_to(repo)
    except ValueError as exc:
        raise VideoPublicationError("approved full render escapes the repository") from exc
    cover = resolve_asset(repo, release.get("cover_image"))
    if cover is None or not cover.is_file():
        raise VideoPublicationError("release cover is missing; it is required as the video poster")
    poster_suffix = cover.suffix.casefold()
    if poster_suffix not in _POSTER_EXTENSIONS:
        raise VideoPublicationError(
            f"release cover format cannot be used as a public poster: {poster_suffix or 'none'}"
        )

    output_hash = approval.get("output_sha256")
    if not isinstance(output_hash, str) or not _SHA256.fullmatch(output_hash):
        raise VideoPublicationError("approved render has no valid SHA-256 output hash")
    if _hash_file(video_source) != output_hash:
        raise VideoPublicationError("approved MP4 changed before publication")
    poster_hash = _hash_file(cover)
    relative_dir = Path("music-videos") / key / output_hash
    video_relative = relative_dir / "video.mp4"
    poster_relative = relative_dir / f"poster-{poster_hash}{poster_suffix}"
    try:
        media_root = public_media_root(repo)
    except PublicMediaError as exc:
        raise VideoPublicationError(str(exc)) from exc
    return PublicationPlan(
        track_key=key,
        video_source=video_source,
        poster_source=cover,
        video_destination=media_root / video_relative,
        poster_destination=media_root / poster_relative,
        public_url=f"/media/{video_relative.as_posix()}",
        poster_url=f"/media/{poster_relative.as_posix()}",
        output_sha256=output_hash,
        poster_sha256=poster_hash,
        approval=approval,
        publication_record=_publication_record(repo, key),
    )


def _copy_atomic(source: Path, destination: Path, expected_hash: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        if _hash_file(destination) != expected_hash:
            raise VideoPublicationError(
                f"content-addressed public media has unexpected bytes: {destination}"
            )
        return
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        if _hash_file(temporary) != expected_hash:
            raise VideoPublicationError(f"public media copy verification failed: {destination}")
        os.replace(temporary, destination)
    except OSError as exc:
        raise VideoPublicationError(f"cannot publish durable media {destination}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _write_yaml_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        raise VideoPublicationError(f"cannot write publication record {path}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def apply_publication(plan: PublicationPlan) -> dict[str, Any]:
    _copy_atomic(plan.video_source, plan.video_destination, plan.output_sha256)
    _copy_atomic(plan.poster_source, plan.poster_destination, plan.poster_sha256)
    record = {
        "version": 1,
        "track_key": plan.track_key,
        "status": "published",
        "opt_in": True,
        "published_at": datetime.now(UTC).isoformat(),
        "public_url": plan.public_url,
        "poster": plan.poster_url,
        "project_hash": plan.approval.get("project_hash"),
        "input_fingerprint": plan.approval.get("input_fingerprint"),
        "manifest_sha256": plan.approval.get("manifest_sha256"),
        "output_sha256": plan.output_sha256,
        "poster_sha256": plan.poster_sha256,
    }
    _write_yaml_atomic(plan.publication_record, record)
    return record


def public_media_available(root: Path, track: dict[str, Any]) -> bool:
    video = track.get("music_video")
    if not isinstance(video, dict):
        return False
    try:
        paths = [
            resolve_public_media(root, video.get("public_url")),
            resolve_public_media(root, video.get("poster")),
        ]
    except PublicMediaError:
        return False
    return all(path is None or path.is_file() for path in paths) and all(
        video.get(field) for field in ("public_url", "poster")
    )


def load_publication(root: Path, release: dict[str, Any], track: dict[str, Any]) -> dict[str, Any]:
    video = track.get("music_video") if isinstance(track.get("music_video"), dict) else {}
    key = track_key(release, track)
    return {
        "status": video.get("status"),
        "opt_in": video.get("opt_in") is True,
        "public_url": video.get("public_url"),
        "poster": video.get("poster"),
        "media_available": public_media_available(root, track),
        "record": _read_yaml(_publication_record(root, key)),
    }


def record_opt_in(root: Path, release: dict[str, Any], track: dict[str, Any], opt_in: bool) -> None:
    path = _publication_record(root.resolve(), track_key(release, track))
    record = _read_yaml(path)
    if not record:
        return
    record["opt_in"] = opt_in
    record["visibility_updated_at"] = datetime.now(UTC).isoformat()
    _write_yaml_atomic(path, record)
