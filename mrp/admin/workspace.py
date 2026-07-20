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

from mrp.core.validate import validate_release_stem_ids

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
    errors.extend(
        {
            "field": error["field"],
            "message": error["message"],
            "severity": error["severity"],
        }
        for error in validate_release_stem_ids(Path("(release)"), data)
    )
    return errors


def str_or_none(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def bool_field(form: dict, key: str) -> bool:
    return form.get(key) in {"on", "true", "1", True}


def artist_record_path(root: Path, artist_id: str) -> Path | None:
    """Path of an artist record — YAML preferred, legacy JSON fallback.
    None when the artist has no record."""
    for ext in (".yaml", ".json"):
        path = root / "content" / "artists" / f"{artist_id}{ext}"
        if path.exists():
            return path
    return None


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


# Artist change migration ------------------------------------------------------
#
# Critic records (app/critic/out/), review markdown (site/src/content/reviews/)
# and preview samples (site/public/samples/) are all keyed {artist_id}--{slug}.
# Changing a release's artist_id orphans every one of them, so the change is
# gated in the Details save and these helpers re-key the files.

_ARTIFACT_DIRS = [
    (Path("app") / "critic" / "out", ".json"),
    (Path("site") / "src" / "content" / "reviews", ".md"),
    (Path("site") / "public" / "samples", ".mp3"),
]


def artist_artifact_moves(
    root: Path, release: dict, old_id: str, new_id: str
) -> list[tuple[Path, Path]]:
    """Existing files an artist_id change must re-key, as (src, dst) pairs."""
    ids = [(f"{old_id}--{u['slug']}", f"{new_id}--{u['slug']}")
           for u in track_units(release)]
    if release.get("model") == "album":
        rslug = release.get("slug") or ""
        ids.append((f"album--{old_id}--{rslug}", f"album--{new_id}--{rslug}"))
    moves = []
    for rel_dir, ext in _ARTIFACT_DIRS:
        for old_key, new_key in ids:
            src = root / rel_dir / f"{old_key}{ext}"
            if src.exists():
                moves.append((src, root / rel_dir / f"{new_key}{ext}"))
    return moves


def migrate_artist_artifacts(
    root: Path, release: dict, old_id: str, new_id: str
) -> list[str]:
    """Re-key downstream artifacts after an artist_id change.

    Renames the files, rewrites embedded ids (track_id/album_id in critic
    records and review frontmatter), and patches preview_audio URLs on the
    release dict (caller persists the release). Returns human-readable actions.
    """
    actions: list[str] = []
    for src, dst in artist_artifact_moves(root, release, old_id, new_id):
        if src.suffix == ".json":
            # Only re-key the record ids; source/proxy paths still point at
            # real files on disk and must not be rewritten.
            rec = json.loads(src.read_text(encoding="utf-8"))
            def _rekey(v: str) -> str:
                return v.replace(f"{old_id}--", f"{new_id}--", 1)
            for key in ("track_id", "album_id"):
                if isinstance(rec.get(key), str):
                    rec[key] = _rekey(rec[key])
            for tic in rec.get("track_reviews_in_context") or []:
                if isinstance(tic, dict) and isinstance(tic.get("track_id"), str):
                    tic["track_id"] = _rekey(tic["track_id"])
            src.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                           encoding="utf-8")
        elif src.suffix == ".md":
            text = src.read_text(encoding="utf-8")
            src.write_text(
                text.replace(f"track_id: {old_id}--", f"track_id: {new_id}--", 1),
                encoding="utf-8")
        src.replace(dst)
        actions.append(f"{src.relative_to(root)} → {dst.name}")
    for u in track_units(release):
        pa = u["track"].get("preview_audio") or ""
        if pa.startswith(f"/samples/{old_id}--"):
            u["track"]["preview_audio"] = pa.replace(
                f"/samples/{old_id}--", f"/samples/{new_id}--", 1)
            actions.append(f"preview_audio → {u['track']['preview_audio']}")
    return actions


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
    from mrp.core.migrate_site import load_structured_record

    artist_path = artist_record_path(root, release.get("artist_id") or "")
    if artist_path is None:
        return {"state": "todo", "detail": "no artist"}
    artist = load_structured_record(artist_path).get("artist") or {}
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
