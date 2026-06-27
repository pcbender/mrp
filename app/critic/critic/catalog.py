"""
Catalog reader: pulls lyrics and persona from the mrp YAML content store.
Single source of truth — no loose files.
"""
from __future__ import annotations

from pathlib import Path

import yaml

# mrp repo root relative to this file: critic/ → app/critic/ → app/ → mrp/
_MRP_ROOT = Path(__file__).resolve().parents[3]
_RELEASES_DIR = _MRP_ROOT / "content" / "releases"
_ARTISTS_DIR = _MRP_ROOT / "content" / "artists"


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def get_lyrics(track_slug: str, release_slug: str | None = None) -> str:
    """
    Return lyrics_text for a track. For singles (model=song), the lyrics
    live at release.song.lyrics_text. For album tracks, search release.tracks.
    If release_slug is given, search that release first.
    """
    candidates = (
        [_RELEASES_DIR / f"{release_slug}.yaml"] if release_slug
        else sorted(_RELEASES_DIR.glob("*.yaml"))
    )

    for path in candidates:
        if not path.exists():
            continue
        data = _load_yaml(path)
        rel = data.get("release", {})

        # Single (model=song): track slug matches release slug
        if rel.get("model") == "song" and rel.get("slug") == track_slug:
            return rel.get("song", {}).get("lyrics_text", "") or ""

        # Also check if this release slug IS the track slug
        if rel.get("slug") == track_slug:
            song = rel.get("song", {})
            if song.get("lyrics_text"):
                return song["lyrics_text"]

        # Multi-track release: search tracks array
        for track in rel.get("tracks", []):
            if track.get("slug") == track_slug:
                return track.get("lyrics_text", "") or ""

    return ""


def get_persona(artist_slug: str) -> str:
    """Return artist bio_long (falls back to bio_short) from artist YAML."""
    for ext in (".yaml", ".json"):
        path = _ARTISTS_DIR / f"{artist_slug}{ext}"
        if path.exists():
            data = _load_yaml(path)
            artist = data.get("artist", {})
            return artist.get("bio_long") or artist.get("bio_short") or ""
    return ""


def get_artist_name(artist_slug: str) -> str:
    for ext in (".yaml", ".json"):
        path = _ARTISTS_DIR / f"{artist_slug}{ext}"
        if path.exists():
            data = _load_yaml(path)
            return data.get("artist", {}).get("name", artist_slug)
    return artist_slug


def get_release_meta(release_slug: str) -> dict:
    """Return top-level release metadata (artist_id, title, release_date, etc.)."""
    path = _RELEASES_DIR / f"{release_slug}.yaml"
    if not path.exists():
        return {}
    data = _load_yaml(path)
    rel = data.get("release", {})
    return {
        "title": rel.get("title", ""),
        "artist_id": rel.get("artist_id", ""),
        "release_date": rel.get("release_date", ""),
        "release_type": rel.get("release_type", ""),
    }
