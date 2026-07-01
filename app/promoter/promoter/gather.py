"""
Gather context from catalog and critic output for a given artist.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .config import ARTISTS_DIR, CRITIC_OUT_DIR, RELEASES_DIR


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        if path.suffix == ".json":
            return json.load(f)
        return yaml.safe_load(f)


def get_artist(slug: str) -> dict:
    """Return the artist dict (inner 'artist' key) or {} if not found."""
    for ext in (".yaml", ".json"):
        path = ARTISTS_DIR / f"{slug}{ext}"
        if path.exists():
            data = _load(path)
            return data.get("artist", {})
    return {}


def get_recent_releases(artist_slug: str, n: int = 3) -> list[dict]:
    """
    Return the N most recent releases for artist_slug, sorted by release_date desc.
    Each dict: slug, title, release_type, release_date, model.
    """
    releases = []
    for path in RELEASES_DIR.glob("*.yaml"):
        data = _load(path)
        rel = data.get("release", {})
        if rel.get("artist_id") != artist_slug:
            continue
        releases.append({
            "slug": rel.get("slug", path.stem),
            "title": rel.get("title", ""),
            "release_type": rel.get("release_type", ""),
            "release_date": rel.get("release_date", "") or "",
            "model": rel.get("model", "album"),
        })

    releases.sort(key=lambda r: r["release_date"], reverse=True)
    return releases[:n]


def get_critic_text(release_slug: str, artist_slug: str) -> str:
    """
    Return the best available critic text for a release:
    - Album/EP: album-- record review
    - Single: track record review
    Returns empty string if nothing found.
    """
    # Try album record first
    album_path = CRITIC_OUT_DIR / f"album--{artist_slug}--{release_slug}.json"
    if album_path.exists():
        data = json.loads(album_path.read_text())
        return data.get("review", {}).get("review_text", "") or data.get("synthesis", {}).get("text", "")

    # Try single track record
    track_path = CRITIC_OUT_DIR / f"{artist_slug}--{release_slug}.json"
    if track_path.exists():
        data = json.loads(track_path.read_text())
        return data.get("review", {}).get("review_text", "")

    # Collect individual track reviews for multi-track releases
    texts = []
    for path in sorted(CRITIC_OUT_DIR.glob(f"{artist_slug}--*.json")):
        if path.name.startswith("album--"):
            continue
        data = json.loads(path.read_text())
        release = (
            data.get("source", {}).get("release_slug")
            or data.get("release_slug", "")
        )
        if release == release_slug:
            rv = data.get("review", {}).get("review_text", "")
            if rv:
                texts.append(rv)
    return "\n\n".join(texts)


def get_all_lyrics(artist_slug: str) -> list[dict]:
    """
    Return all lyrics for an artist across all releases.
    Each dict: release_title, track_title, lyrics_text.
    """
    results = []
    for path in RELEASES_DIR.glob("*.yaml"):
        data = _load(path)
        rel = data.get("release", {})
        if rel.get("artist_id") != artist_slug:
            continue
        release_title = rel.get("title", path.stem)

        # Single
        song = rel.get("song")
        if song and song.get("lyrics_text"):
            results.append({
                "release_title": release_title,
                "track_title": song.get("title", ""),
                "lyrics_text": song["lyrics_text"],
            })

        # Multi-track
        for track in rel.get("tracks", []):
            if track.get("lyrics_text"):
                results.append({
                    "release_title": release_title,
                    "track_title": track.get("title", ""),
                    "lyrics_text": track["lyrics_text"],
                })

    return results
