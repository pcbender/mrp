"""Phase-1 helpers for the Changes publishing workflow.

Classifies each managed working-tree change to the entity it affects
(release / artist / post / page / asset), resolves the owning release's
publish eligibility, and generates a human commit message from the actual
changes. Pure / read-only — no git or deploy side effects here.

Eligibility rule (v1): a change is publish-eligible unless it belongs to a
release whose status is not ``approved`` or ``live``. Non-release content
(artists, posts, pages) and unattributable assets are always eligible.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mrp.core.migrate_site import load_structured_record

# A release must reach one of these before its files may be published.
ELIGIBLE_STATUSES = {"approved", "live"}


def _load_yaml_record(root: Path, rel_path: str) -> dict | None:
    path = root / rel_path
    if not path.exists():
        return None
    try:
        return load_structured_record(path)
    except Exception:
        return None


def _artist_name(root: Path, artist_id: str | None) -> str | None:
    if not artist_id:
        return None
    rec = _load_yaml_record(root, f"content/artists/{artist_id}.yaml")
    if not rec:
        return artist_id
    return (rec.get("artist") or {}).get("name") or artist_id


def _release_slug_from_parts(parts: tuple[str, ...]) -> str | None:
    """Best-effort: pull a release slug from any '.../releases/<slug>...' path."""
    if "releases" in parts:
        i = parts.index("releases")
        if i + 1 < len(parts):
            return Path(parts[i + 1]).stem
    return None


def _release_slug_for_video_key(root: Path, key: str) -> str | None:
    directory = root / "content" / "releases"
    if not directory.is_dir():
        return None
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.casefold() not in {".json", ".yaml", ".yml"}:
            continue
        record = _load_yaml_record(root, path.relative_to(root).as_posix())
        release = (record or {}).get("release") or {}
        artist_id = str(release.get("artist_id") or "")
        tracks = release.get("tracks") if isinstance(release.get("tracks"), list) else []
        song = release.get("song")
        units = [song] if isinstance(song, dict) else tracks
        if any(
            isinstance(track, dict)
            and f"{artist_id}--{track.get('slug') or ''}" == key
            for track in units
        ):
            return str(release.get("slug") or path.stem)
    return None


def classify_change(root: Path, path: str) -> dict[str, Any]:
    """Resolve one changed file to its entity + publish eligibility.

    Returns a dict with: kind, entity_id, entity_title, artist_name,
    release_slug, release_status, eligible, reason.
    """
    parts = Path(path).parts
    info: dict[str, Any] = {
        "kind": "other", "entity_id": None, "entity_title": None,
        "artist_name": None, "release_slug": None, "release_status": None,
        "eligible": True, "reason": None,
    }

    if parts[:2] == ("content", "releases") and path.endswith(".yaml"):
        info["kind"] = "release"
        info["release_slug"] = Path(path).stem
    elif parts[:2] == ("content", "artists") and path.endswith(".yaml"):
        info["kind"] = "artist"
        info["entity_id"] = Path(path).stem
        info["entity_title"] = _artist_name(root, Path(path).stem)
        return info
    elif parts[:2] == ("content", "posts") and path.endswith(".yaml"):
        info["kind"] = "post"
        info["entity_id"] = Path(path).stem
        rec = _load_yaml_record(root, path)
        info["entity_title"] = ((rec or {}).get("post") or {}).get("title") or Path(path).stem
        return info
    elif parts[:2] == ("content", "pages"):
        info["kind"] = "page"
        info["entity_id"] = Path(path).stem
        return info
    else:
        # Asset or other file — try to attribute it to a release/artist.
        slug = None
        if parts[:3] == ("assets", "source", "video") and len(parts) >= 4:
            slug = _release_slug_for_video_key(root, parts[3])
        slug = slug or _release_slug_from_parts(parts)
        if slug:
            info["kind"] = "release-asset"
            info["release_slug"] = slug
        elif "artists" in parts:
            info["kind"] = "artist-asset"
            i = parts.index("artists")
            if i + 1 < len(parts):
                info["entity_id"] = Path(parts[i + 1]).stem
                info["entity_title"] = _artist_name(root, info["entity_id"])
            return info
        else:
            info["kind"] = "asset" if "assets" in parts else "other"
            return info

    # Release-attributed change: resolve title/artist/status + eligibility.
    slug = info["release_slug"]
    rec = _load_yaml_record(root, f"content/releases/{slug}.yaml")
    rel = (rec or {}).get("release") if rec else None
    if not rel:
        # A release asset with no (longer any) release record — leave eligible.
        info["entity_title"] = slug
        return info
    info["entity_id"] = slug
    info["entity_title"] = rel.get("title") or slug
    info["artist_name"] = _artist_name(root, rel.get("artist_id"))
    status = rel.get("status")
    info["release_status"] = status
    if status not in ELIGIBLE_STATUSES:
        info["eligible"] = False
        info["reason"] = f"release is “{status or 'unknown'}” — needs approved or live"
    return info


def annotate_changes(root: Path, changes: list[dict]) -> list[dict]:
    """Attach classify_change() output to each change entry in place."""
    for c in changes:
        c.update(classify_change(root, c["path"]))
    return changes


def eligibility_summary(changes: list[dict]) -> dict[str, Any]:
    """Which changes block publishing (grouped by release for messaging)."""
    blockers = [c for c in changes if not c.get("eligible", True)]
    blocked_releases: dict[str, str] = {}
    for c in blockers:
        title = c.get("entity_title") or c.get("release_slug") or c["path"]
        blocked_releases.setdefault(title, c.get("reason") or "not eligible")
    return {
        "all_eligible": not blockers,
        "blocker_count": len(blockers),
        "blocked_releases": blocked_releases,
    }


def _join_and(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def generate_commit_message(changes: list[dict]) -> str:
    """A default, editable commit message derived from the actual changes."""
    releases: dict[str, tuple[str, str | None]] = {}
    artists: set[str] = set()
    posts: set[str] = set()
    other = 0
    for c in changes:
        kind = c.get("kind")
        if kind in ("release", "release-asset") and c.get("release_slug"):
            releases[c["release_slug"]] = (
                c.get("entity_title") or c["release_slug"], c.get("artist_name"))
        elif kind in ("artist", "artist-asset") and c.get("entity_id"):
            artists.add(c["entity_id"])
        elif kind == "post" and c.get("entity_id"):
            posts.add(c["entity_id"])
        else:
            other += 1

    # Releases-only: name the titles when there aren't too many.
    if releases and not artists and not posts and not other:
        titles = [t for t, _ in releases.values()]
        artist_names = {a for _, a in releases.values() if a}
        by = f" by {next(iter(artist_names))}" if len(artist_names) == 1 else ""
        if len(titles) <= 3:
            return f"Update {_join_and(sorted(titles))}{by}"
        return f"Update {len(titles)} releases{by}"

    # Mixed / many: fall back to humanized counts.
    parts = []
    if releases:
        parts.append(_count(len(releases), "release", "releases"))
    if artists:
        parts.append(_count(len(artists), "artist profile", "artist profiles"))
    if posts:
        parts.append(_count(len(posts), "post", "posts"))
    if not parts:
        return "Update site content"
    return "Update " + _join_and(parts)
