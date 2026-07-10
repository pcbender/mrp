from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.admin.deps import get_repo_root
from mrp.core.migrate_site import load_structured_record

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _artist_names(root: Path) -> dict[str, str]:
    """Map artist id → display name for the catalog rows/filter."""
    artists_dir = root / "content" / "artists"
    names: dict[str, str] = {}
    for path in sorted(list(artists_dir.glob("*.yaml")) + list(artists_dir.glob("*.json"))):
        try:
            data = load_structured_record(path)
        except Exception:
            continue
        a = data.get("artist", {})
        names[a.get("id", path.stem)] = a.get("name", path.stem)
    return names


def _release_songs(rel: dict) -> list[dict]:
    """Yield every song record in a release (single `song` or `tracks[]`)."""
    songs: list[dict] = []
    song = rel.get("song")
    if isinstance(song, dict):
        songs.append(song)
    for t in rel.get("tracks") or []:
        if isinstance(t, dict):
            songs.append(t)
    return songs


def _load_all_tracks(root: Path) -> list[dict[str, Any]]:
    """Flatten every track across all releases into a single catalog list."""
    releases_dir = root / "content" / "releases"
    names = _artist_names(root)
    rows: list[dict[str, Any]] = []
    for path in sorted(releases_dir.glob("*.yaml")):
        try:
            data = load_structured_record(path)
        except Exception:
            continue
        rel = data.get("release")
        if not isinstance(rel, dict):
            continue
        artist_id = rel.get("artist_id", "")
        for song in _release_songs(rel):
            slug = song.get("slug")
            if not slug:
                continue
            rows.append({
                "release_slug": path.stem,
                "release_title": rel.get("title", path.stem),
                "release_date": rel.get("release_date") or "",
                "status": rel.get("status", ""),
                "artist_id": artist_id,
                "artist_name": names.get(artist_id, artist_id),
                "track_slug": slug,
                "title": song.get("title", slug),
                "number": song.get("number"),
                "duration": song.get("duration") or "",
                "explicit": bool(song.get("explicit")),
                "instrumental": bool(song.get("instrumental")),
            })
    # Newest releases first; within a release, track order.
    rows.sort(key=lambda r: (r["release_date"] or "0000", r["release_slug"],
                             r["number"] if isinstance(r["number"], int) else 0),
              reverse=False)
    rows.sort(key=lambda r: r["release_date"] or "0000", reverse=True)
    return rows


def _filter_tracks(rows: list[dict], q: str, artist_f: str) -> list[dict]:
    if q:
        ql = q.lower()
        rows = [
            r for r in rows
            if ql in r["title"].lower()
            or ql in r["artist_name"].lower()
            or ql in r["artist_id"].lower()
            or ql in r["release_title"].lower()
        ]
    if artist_f:
        rows = [r for r in rows if r["artist_id"] == artist_f]
    return rows


@router.get("/catalog", response_class=HTMLResponse)
async def catalog_list(request: Request, q: str = "", artist_filter: str = ""):
    root = get_repo_root()
    rows = _load_all_tracks(root)
    filtered = _filter_tracks(rows, q, artist_filter)
    # Artist options: only artists that actually own tracks, sorted by name.
    seen = {(r["artist_id"], r["artist_name"]) for r in rows}
    artists = sorted(({"id": aid, "name": name} for aid, name in seen),
                     key=lambda a: a["name"].lower())
    ctx = {
        "tracks": filtered,
        "total": len(rows),
        "q": q,
        "artist_filter": artist_filter,
        "artists": artists,
    }
    if _is_htmx(request):
        return _templates.TemplateResponse(request, "catalog/_table_body.html", ctx)
    return _templates.TemplateResponse(request, "catalog/list.html", ctx)
