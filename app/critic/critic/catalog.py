"""
Catalog reader: pulls lyrics and persona from the mrp YAML content store.
Single source of truth — no loose files.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml

# mrp repo root relative to this file: critic/ → app/critic/ → app/ → mrp/
_MRP_ROOT = Path(__file__).resolve().parents[3]
_RELEASES_DIR = _MRP_ROOT / "content" / "releases"
_ARTISTS_DIR = _MRP_ROOT / "content" / "artists"
_REVIEWS_DIR = _MRP_ROOT / "site" / "src" / "content" / "reviews"
_CRITIC_OUT_DIR = Path(__file__).resolve().parents[1] / "out"
_APPROVED_REVIEW_STATUSES = {"approved", "publishable"}


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


def _find_track(track_slug: str, release_slug: str | None = None) -> dict:
    """Return the raw track/song dict for a slug, or {} if not found."""
    candidates = (
        [_RELEASES_DIR / f"{release_slug}.yaml"] if release_slug
        else sorted(_RELEASES_DIR.glob("*.yaml"))
    )
    for path in candidates:
        if not path.exists():
            continue
        data = _load_yaml(path)
        rel = data.get("release", {})
        # Single (model=song): the song lives at release.song
        song = rel.get("song") or {}
        if song and (song.get("slug") == track_slug or rel.get("slug") == track_slug):
            return song
        # Multi-track release: search tracks array
        for track in rel.get("tracks", []):
            if track.get("slug") == track_slug:
                return track
    return {}


def get_hints(track_slug: str, release_slug: str | None = None) -> dict:
    """Return hints dict for a track, or {} if none defined."""
    return _find_track(track_slug, release_slug).get("hints") or {}


def get_lyrics_raw(track_slug: str, release_slug: str | None = None) -> str:
    """Return the raw generation script (lyrics with Suno structural tags)."""
    return _find_track(track_slug, release_slug).get("lyrics_raw") or ""


def get_style(track_slug: str, release_slug: str | None = None) -> str:
    """Return the Suno style prompt the track was generated with."""
    return _find_track(track_slug, release_slug).get("style") or ""


def _artist_record(artist_slug: str) -> dict:
    for ext in (".yaml", ".json"):
        path = _ARTISTS_DIR / f"{artist_slug}{ext}"
        if path.exists():
            data = _load_yaml(path)
            return data.get("artist", {})
    return {}


def _parse_catalog_date(value: object) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _context_excerpt(release: dict) -> str:
    """Return a compact dated-release excerpt without track-list boilerplate."""
    value = str(release.get("summary") or release.get("description") or "")
    value = re.split(r"\n## Tracks\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.sub(r"!\[[^]]*]\([^)]+\)", " ", value)
    value = re.sub(r"\[([^]]*)]\([^)]+\)", r"\1", value)
    value = re.sub(r"[*_#]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= 360:
        return value
    return value[:357].rsplit(" ", 1)[0] + "..."


def _release_review_id(release: dict) -> str:
    """Return the critic/writeback id for a catalog release."""
    artist_id = str(release.get("artist_id") or "")
    release_slug = str(release.get("slug") or "")
    release_type = str(release.get("release_type") or "").lower()
    is_multi_track = (
        release.get("model") == "album"
        or release_type in {"album", "ep"}
        or isinstance(release.get("tracks"), list)
    )
    if is_multi_track:
        return f"album--{artist_id}--{release_slug}"
    song = release.get("song") or {}
    return f"{artist_id}--{song.get('slug') or release_slug}"


def _review_frontmatter(path: Path) -> dict:
    """Load YAML frontmatter from a critic review, failing closed."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        data = yaml.safe_load("\n".join(lines[1:end])) or {}
    except (StopIteration, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _approved_review_summary(release: dict) -> str:
    """Return the written summary only when its critic record is approved."""
    review_id = _release_review_id(release)
    record_path = _CRITIC_OUT_DIR / f"{review_id}.json"
    review_path = _REVIEWS_DIR / f"{review_id}.md"
    if not record_path.is_file() or not review_path.is_file():
        return ""
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    if not isinstance(record, dict):
        return ""
    review = record.get("review") or {}
    if not isinstance(review, dict):
        return ""
    status = str(review.get("status") or "")
    if status not in _APPROVED_REVIEW_STATUSES:
        return ""
    frontmatter = _review_frontmatter(review_path)
    if frontmatter.get("track_id") != review_id:
        return ""
    summary = frontmatter.get("summary")
    return summary.strip() if isinstance(summary, str) else ""


def get_releases_as_of(artist_slug: str, cutoff: str) -> list[dict]:
    """Return this artist's dated catalog on or before cutoff, oldest first.

    Undated or invalidly dated records are excluded because they cannot safely
    be placed on the target release's timeline.
    """
    cutoff_date = _parse_catalog_date(cutoff)
    if cutoff_date is None:
        raise ValueError(f"Invalid point-in-time release date: {cutoff or '(missing)'}")

    releases = []
    for path in sorted(_RELEASES_DIR.glob("*.yaml")):
        data = _load_yaml(path) or {}
        release = data.get("release", {})
        release_date = _parse_catalog_date(release.get("release_date"))
        if release.get("artist_id") != artist_slug or release_date is None:
            continue
        if release_date <= cutoff_date:
            releases.append({
                "slug": release.get("slug") or path.stem,
                "title": release.get("title") or path.stem,
                "release_type": release.get("release_type") or "release",
                "release_date": release_date.isoformat(),
                "excerpt": _context_excerpt(release),
                "review_summary": _approved_review_summary(release),
            })
    return sorted(releases, key=lambda item: (item["release_date"], item["slug"]))


def get_point_in_time_context(artist_slug: str, release_slug: str) -> str:
    """Build deterministic critic context as it existed on the release date.

    Artist bios are mutable and currently have no dated revisions, so the
    current bio is deliberately not supplied to historical reviews. Career
    context instead comes from catalog records whose release dates are at or
    before the target release.
    """
    target = get_release_meta(release_slug)
    if not target:
        raise ValueError(f"Release not found: {release_slug}")
    if target.get("artist_id") != artist_slug:
        raise ValueError(
            f"Release {release_slug} belongs to {target.get('artist_id')}, not {artist_slug}"
        )
    cutoff = str(target.get("release_date") or "")
    releases = get_releases_as_of(artist_slug, cutoff)
    artist_name = get_artist_name(artist_slug)
    target_order = (cutoff, release_slug)

    lines = [
        "POINT-IN-TIME ARTIST CONTEXT",
        f"Release-date cutoff: {cutoff}",
        "Write as though the target release is new on this date.",
        "Do not mention, infer, or rely on releases or artist developments after this cutoff.",
        "The current mutable artist biography is excluded because it has no dated revision.",
        "For prior releases, approved critic summaries take precedence over catalog descriptions.",
        f"Artist: {artist_name}",
        "Catalog available at this point (oldest first):",
    ]
    for release in releases:
        target_label = " [target release]" if release["slug"] == release_slug else ""
        line = (
            f"- {release['release_date']} — {release['title']} "
            f"({release['release_type']}){target_label}"
        )
        # Avoid feeding the target's existing marketing/review copy back into
        # the critic. Earlier approved reviews provide continuity; catalog
        # copy remains the safe fallback when no approved review is available.
        if release["slug"] != release_slug:
            release_order = (release["release_date"], release["slug"])
            if release_order < target_order and release["review_summary"]:
                line += f"\n  Approved critic summary: {release['review_summary']}"
            elif release["excerpt"]:
                line += f"\n  Catalog description: {release['excerpt']}"
        lines.append(line)
    return "\n".join(lines)


def get_persona(artist_slug: str, release_slug: str | None = None) -> str:
    """Return PIT artist context for a release, or the current bio for legacy callers."""
    if release_slug:
        return get_point_in_time_context(artist_slug, release_slug)
    artist = _artist_record(artist_slug)
    return artist.get("bio_long") or artist.get("bio_short") or ""


def get_artist_name(artist_slug: str) -> str:
    return _artist_record(artist_slug).get("name", artist_slug)


def get_release_tracks(release_slug: str) -> list[dict]:
    """Return ordered tracks for a release.
    Each dict: slug, title, number, duration.
    Works for multi-track albums/EPs and single-song releases."""
    path = _RELEASES_DIR / f"{release_slug}.yaml"
    if not path.exists():
        return []
    data = _load_yaml(path)
    rel = data.get("release", {})

    tracks = rel.get("tracks", [])
    if tracks:
        return [
            {
                "slug": t["slug"],
                "title": t.get("title", ""),
                "number": t.get("number", i + 1),
                "duration": t.get("duration", ""),
            }
            for i, t in enumerate(sorted(tracks, key=lambda t: t.get("number", 0)))
        ]

    song = rel.get("song", {})
    if song:
        return [
            {
                "slug": song.get("slug", release_slug),
                "title": song.get("title", rel.get("title", "")),
                "number": 1,
                "duration": song.get("duration", ""),
            }
        ]

    return []


def is_release_instrumental(release_slug: str) -> bool:
    """Return True if every track/song in the release has instrumental=True."""
    path = _RELEASES_DIR / f"{release_slug}.yaml"
    if not path.exists():
        return False
    data = _load_yaml(path)
    rel = data.get("release", {})

    tracks = rel.get("tracks", [])
    if tracks:
        return all(t.get("instrumental", False) for t in tracks)

    song = rel.get("song", {})
    if song:
        return bool(song.get("instrumental", False))

    return False


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
