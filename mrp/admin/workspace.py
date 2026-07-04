"""Shared workspace helpers: stage registry, completion indicators, form utilities.

The release workspace presents each release as a set of workflow-stage screens
(intake → details → links → tracks → critic → sampler → promoter → publish →
monitoring).
This module owns the stage registry and the cheap heuristics that drive the
per-stage completion dots in the workspace header.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "release.schema.json"

PLATFORM_KEYS = [
    "spotify", "apple_music", "itunes_store", "youtube", "youtube_music",
    "tidal", "amazon_music", "deezer", "soundcloud", "bandcamp", "pandora",
]

STATUSES = ["draft", "staged", "verified", "approved", "live", "failed", "archived"]

STAGES = [
    ("intake",     "Intake"),
    ("details",    "Details"),
    ("links",      "Links"),
    ("tracks",     "Tracks"),
    ("critic",     "Critic"),
    ("sampler",    "Sampler"),
    ("promoter",   "Promoter"),
    ("publish",    "Build / Publish"),
    ("monitoring", "Monitoring"),
]
STAGE_IDS = {s for s, _ in STAGES}


def validate_release_dict(data: dict) -> list[dict]:
    schema = json.loads(_SCHEMA_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for err in validator.iter_errors(data):
        field = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append({"field": field, "message": err.message, "severity": "error"})
    return errors


def str_or_none(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def bool_field(form: dict, key: str) -> bool:
    return form.get(key) in {"on", "true", "1", True}


def track_units(release: dict) -> list[dict]:
    """Normalize song vs album into a uniform list of track units.

    Each unit: {"index": i, "slug": ..., "title": ..., "track": <dict ref>}.
    The "track" value references the live dict inside the release, so patches
    to it are patches to the record.
    """
    if release.get("model") == "song":
        song = release.get("song")
        if not isinstance(song, dict):
            return []
        return [{
            "index": 0,
            "slug": song.get("slug") or release.get("slug") or "",
            "title": song.get("title") or release.get("title") or "",
            "track": song,
        }]
    units = []
    for i, track in enumerate(release.get("tracks") or []):
        if not isinstance(track, dict):
            continue
        units.append({
            "index": i,
            "slug": track.get("slug") or f"track-{i + 1}",
            "title": track.get("title") or f"(track {i + 1})",
            "track": track,
        })
    return units


def effective_master_path(release: dict, index: int, track: dict) -> str | None:
    """Track-level master_path, falling back to legacy automation.master_path."""
    if track.get("master_path"):
        return track["master_path"]
    legacy = (release.get("automation") or {}).get("master_path")
    if isinstance(legacy, list):
        return legacy[index] if index < len(legacy) else None
    return legacy or None


# Per-stage detail heuristics ------------------------------------------------

_DETAILS_REQUIRED = ["title", "artist_id", "release_date", "cover_image"]
_DETAILS_NICE = ["label", "publisher", "upc", "summary", "description"]
_TRACK_FIELDS = ["title", "slug", "isrc", "duration", "style", "lyrics_text"]


def _details_status(release: dict) -> dict:
    seo = release.get("seo") or {}
    required = [bool(release.get(k)) for k in _DETAILS_REQUIRED]
    required += [bool(seo.get("title")), bool(seo.get("description"))]
    credits = release.get("credits") or {}
    nice = [bool(release.get(k)) for k in _DETAILS_NICE]
    nice.append(bool(credits.get("primary_artist")))
    filled = sum(required) + sum(nice)
    total = len(required) + len(nice)
    if all(required) and all(nice):
        state = "done"
    elif all(required):
        state = "partial"
    else:
        state = "todo"
    return {"state": state, "detail": f"{filled}/{total}"}


def _links_status(release: dict) -> dict:
    links = release.get("links") or {}
    na = set((release.get("automation") or {}).get("links_na") or [])
    resolved = sum(1 for k in PLATFORM_KEYS if links.get(k) or k in na)
    total = len(PLATFORM_KEYS)
    state = "done" if resolved == total else ("partial" if resolved else "todo")
    return {"state": state, "detail": f"{resolved}/{total}"}


def track_completion(release: dict, root: Path) -> list[dict]:
    """Per-track completion cells for the matrix and the tracks stage dot."""
    artist_id = release.get("artist_id") or ""
    critic_out = root / "app" / "critic" / "out"
    rows = []
    for unit in track_units(release):
        t = unit["track"]
        links = t.get("links") or {}
        fields_filled = sum(1 for k in _TRACK_FIELDS if t.get(k))
        master = effective_master_path(release, unit["index"], t)
        rows.append({
            **unit,
            "metadata": fields_filled >= len(_TRACK_FIELDS) - 1,  # lyrics optional for instrumentals
            "fields_filled": fields_filled,
            "fields_total": len(_TRACK_FIELDS),
            "lyrics": bool(t.get("lyrics_text")) or bool(t.get("instrumental")),
            "master": bool(master),
            "master_path": master,
            "snippet": bool(t.get("preview_audio")),
            "review": (critic_out / f"{artist_id}--{unit['slug']}.json").is_file(),
            "links_count": sum(1 for k in PLATFORM_KEYS if links.get(k)),
        })
    return rows


def _tracks_status(release: dict, root: Path) -> dict:
    rows = track_completion(release, root)
    if not rows:
        return {"state": "todo", "detail": "0 tracks"}
    complete = sum(
        1 for r in rows
        if r["metadata"] and r["lyrics"] and r["master"] and r["snippet"]
    )
    any_progress = any(r["fields_filled"] for r in rows)
    state = "done" if complete == len(rows) else ("partial" if any_progress else "todo")
    return {"state": state, "detail": f"{complete}/{len(rows)} tracks"}


def _critic_status(release: dict, root: Path) -> dict:
    rows = track_completion(release, root)
    if not rows:
        return {"state": "todo", "detail": ""}
    reviewed = sum(1 for r in rows if r["review"])
    state = "done" if reviewed == len(rows) else ("partial" if reviewed else "todo")
    return {"state": state, "detail": f"{reviewed}/{len(rows)}"}


def _promoter_status(root: Path, release: dict) -> dict:
    """Done when the artist has a promo blurb and a human-reviewed bio."""
    import yaml

    artist_path = root / "content" / "artists" / f"{release.get('artist_id') or ''}.yaml"
    if not artist_path.is_file():
        return {"state": "todo", "detail": "no artist"}
    artist = (yaml.safe_load(artist_path.read_text()) or {}).get("artist") or {}
    blurb = bool(artist.get("promo_blurb"))
    bio = bool(artist.get("bio_short") or artist.get("bio_long"))
    reviewed = artist.get("bio_auto_generated") is False
    if blurb and bio and reviewed:
        return {"state": "done", "detail": ""}
    if blurb or bio:
        return {"state": "partial", "detail": "unreviewed" if not reviewed else "incomplete"}
    return {"state": "todo", "detail": ""}


def _sampler_status(release: dict) -> dict:
    units = track_units(release)
    if not units:
        return {"state": "todo", "detail": "0 tracks"}
    cut = sum(1 for u in units if u["track"].get("preview_audio"))
    state = "done" if cut == len(units) else ("partial" if cut else "todo")
    return {"state": state, "detail": f"{cut}/{len(units)}"}


def _publish_status(release: dict) -> dict:
    status = release.get("status") or "draft"
    if status == "live":
        return {"state": "done", "detail": "live"}
    if status in ("staged", "verified", "approved"):
        return {"state": "partial", "detail": status}
    return {"state": "todo", "detail": status}


def stage_statuses(root: Path, slug: str, release: dict) -> dict[str, dict]:
    """Compute {stage_id: {"state": done|partial|todo, "detail": str}} for the header."""
    return {
        "intake": {"state": "done", "detail": ""},
        "details": _details_status(release),
        "links": _links_status(release),
        "tracks": _tracks_status(release, root),
        "critic": _critic_status(release, root),
        "sampler": _sampler_status(release),
        "promoter": _promoter_status(root, release),
        "publish": _publish_status(release),
        "monitoring": {"state": "todo", "detail": ""},
    }
