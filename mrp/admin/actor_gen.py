"""Generate a per-track song-title actor from a real font (deterministic).

Runs after a successful ``prepare`` (auto) or from the casting page
(Regenerate). The title text is outlined into a single ``text`` layer — one
letter-contour each, all traced together — exactly like the designer's
"Generate text" panel. It is a draft: trace, color, and drivers are refined
in the Actor Designer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mrp.admin import text_outline
from mrp.admin.video_casting import (
    CastingEditorError,
    _invalidate_preflight,
    _preflight_path,
    _read_mapping,
    _validation_problems,
    _write_yaml_atomic,
    project_path,
)

TITLE_ACTOR_ID = "song-title"


def _load_release_track(
    root: Path, release_slug: str, track_slug: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    from mrp.admin.workspace import track_units
    from mrp.core.migrate_site import load_structured_record

    path = root / "content" / "releases" / f"{release_slug}.yaml"
    if not path.is_file():
        raise CastingEditorError(f"release does not exist: {release_slug}")
    release = load_structured_record(path).get("release") or {}
    unit = next(
        (item for item in track_units(release) if item["slug"] == track_slug), None
    )
    if unit is None:
        raise CastingEditorError(f"track does not exist: {track_slug}")
    return release, unit["track"]


def title_text(track: dict[str, Any]) -> str:
    return str(track.get("title") or track.get("slug") or "").strip()


def _title_actor_payload(title: str, path_data: str) -> dict[str, Any]:
    """A draft song-title actor: one text layer with a legible write-on trace."""
    return {
        "id": TITLE_ACTOR_ID,
        "name": f"{title} (title)",
        "description": f"Auto-generated title layer for “{title}”.",
        "kind": "spirogram",
        "character": "vocals",
        "components": [
            {
                "id": "title",
                "role": "vocals",
                "geometry": {
                    "family": "text",
                    "path_data": path_data,
                    "samples": 300,
                },
                "trace": {
                    "cycles_per_second": 0.3,
                    "trail_fraction": 0.85,
                    "ghost_count": 0,
                    "ghost_spacing": 0.08,
                    "head_radius": 0,
                },
                "color": "#ffffff",
                "z_index": 0,
                "opacity": 1.0,
                "line_width": 2.5,
            }
        ],
    }


def build_title_document(
    payload: dict[str, Any], title: str, path_data: str
) -> dict[str, Any]:
    """Insert/replace the song-title actor in a raw track-project mapping."""
    actors = (
        payload.setdefault("project", {})
        .setdefault("visuals", {})
        .setdefault("actors", {})
    )
    actors[TITLE_ACTOR_ID] = _title_actor_payload(title, path_data)
    return payload


def generate_title_actor(
    root: str | Path,
    release_slug: str,
    track_slug: str,
    *,
    only_if_missing: bool = False,
    font: str | None = None,
) -> dict[str, Any]:
    """Outline the track title into the project's ``song-title`` text actor."""
    root = Path(root)
    release, track = _load_release_track(root, release_slug, track_slug)
    title = title_text(track)
    if not title:
        raise CastingEditorError("track has no title to render")

    path = project_path(root, release, track)
    if not path.is_file():
        raise CastingEditorError("video project does not exist; run prepare first")
    payload = _read_mapping(path)
    existing = (
        payload.get("project", {}).get("visuals", {}).get("actors", {})
    )
    if only_if_missing and TITLE_ACTOR_ID in existing:
        return {"status": "skipped", "reason": "exists", "actor": TITLE_ACTOR_ID}

    font_path = text_outline.resolve_font(root, font)
    path_data = text_outline.text_to_path_data(title, font_path)
    build_title_document(payload, title, path_data)

    from mrp.video.track_project import TrackProjectDocument

    try:
        updated = TrackProjectDocument.model_validate(payload)
    except ValidationError as exc:
        raise CastingEditorError(*_validation_problems(exc)) from exc
    _write_yaml_atomic(path, updated.model_dump(mode="json", exclude_none=True))
    _invalidate_preflight(_preflight_path(root, release, track))
    return {
        "status": "generated",
        "actor": TITLE_ACTOR_ID,
        "title": title,
        "contours": path_data.count("M"),
        "font": font_path.name,
    }
