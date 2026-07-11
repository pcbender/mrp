from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.admin.deps import get_repo_root
from mrp.core import metrics
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


def _streams_by_isrc() -> dict[str, dict[str, int]]:
    """Streams (SUM quantity) per ISRC, split by distributor, from metrics.db.

    Returns {isrc: {"landr": n, "amuse": n, "total": n}}. Empty if the
    metrics database is missing or unreadable.
    """
    out: dict[str, dict[str, int]] = {}
    try:
        conn = metrics.open_db()
    except Exception:
        return out
    try:
        rows = conn.execute(
            """SELECT isrc, distributor, SUM(quantity) AS q FROM royalty_rows
               WHERE isrc IS NOT NULL AND isrc != '' GROUP BY isrc, distributor"""
        ).fetchall()
    except Exception:
        return out
    finally:
        conn.close()
    for row in rows:
        entry = out.setdefault(row["isrc"], {"landr": 0, "amuse": 0, "total": 0})
        qty = row["q"] or 0
        if row["distributor"] in ("landr", "amuse"):
            entry[row["distributor"]] += qty
        entry["total"] += qty
    return out


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
    streams = _streams_by_isrc()
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
            isrc = song.get("isrc") or ""
            s = streams.get(isrc, {"landr": 0, "amuse": 0, "total": 0})
            rows.append({
                "release_slug": path.stem,
                "release_title": rel.get("title", path.stem),
                "release_date": rel.get("release_date") or "",
                "status": rel.get("status", ""),
                "distributor": rel.get("distributor", ""),
                "artist_id": artist_id,
                "artist_name": names.get(artist_id, artist_id),
                "track_slug": slug,
                "title": song.get("title", slug),
                "isrc": isrc,
                "number": song.get("number"),
                "duration": song.get("duration") or "",
                "explicit": bool(song.get("explicit")),
                "instrumental": bool(song.get("instrumental")),
                "streams_landr": s["landr"],
                "streams_amuse": s["amuse"],
                "streams_total": s["total"],
            })
    # Newest releases first; within a release, track order.
    rows.sort(key=lambda r: (r["release_date"] or "0000", r["release_slug"],
                             r["number"] if isinstance(r["number"], int) else 0),
              reverse=False)
    rows.sort(key=lambda r: r["release_date"] or "0000", reverse=True)
    return rows


# Sortable columns → the row field they sort on. '#' (number) is deliberately
# excluded per the catalog spec; the blank actions column is not sortable.
_SORT_FIELDS = {
    "title": "title",
    "isrc": "isrc",
    "artist": "artist_name",
    "release": "release_title",
    "date": "release_date",
    "distributor": "distributor",
    "duration": "duration",
    "streams": "streams",
}


def _duration_seconds(value: str) -> int:
    """Parse 'm:ss' / 'h:mm:ss' into seconds for numeric duration sorting.

    Blank or unparseable durations sort first in ascending order.
    """
    if not value:
        return -1
    seconds = 0
    for part in str(value).split(":"):
        try:
            seconds = seconds * 60 + int(part)
        except ValueError:
            return -1
    return seconds


def _sort_tracks(rows: list[dict], sort: str, direction: str) -> list[dict]:
    """Sort by a clicked column. Unknown/empty `sort` keeps the default order."""
    if sort not in _SORT_FIELDS:
        return rows
    reverse = direction == "desc"
    if sort == "duration":
        return sorted(rows, key=lambda r: _duration_seconds(r["duration"]), reverse=reverse)
    if sort == "streams":
        return sorted(rows, key=lambda r: r.get("streams") or 0, reverse=reverse)
    field = _SORT_FIELDS[sort]
    # Empty strings sort last in ascending order regardless of direction.
    return sorted(rows, key=lambda r: (not r.get(field), str(r.get(field) or "").lower()),
                  reverse=reverse)


def _filter_tracks(rows: list[dict], q: str, artist_f: str, dist_f: str) -> list[dict]:
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
    if dist_f:
        rows = [r for r in rows if r["distributor"] == dist_f]
    return rows


@router.get("/catalog", response_class=HTMLResponse)
async def catalog_list(
    request: Request,
    q: str = "",
    artist_filter: str = "",
    dist_filter: str = "",
    sort: str = "",
    dir: str = "asc",
):
    root = get_repo_root()
    dist_filter = dist_filter if dist_filter in ("landr", "amuse") else ""
    rows = _load_all_tracks(root)
    filtered = _filter_tracks(rows, q, artist_filter, dist_filter)
    # Streams follow the distributor filter: All → combined total.
    streams_key = {"landr": "streams_landr", "amuse": "streams_amuse"}.get(
        dist_filter, "streams_total")
    for r in filtered:
        r["streams"] = r[streams_key]
    filtered = _sort_tracks(filtered, sort, dir)
    # Artist options: only artists that actually own tracks, sorted by name.
    seen = {(r["artist_id"], r["artist_name"]) for r in rows}
    artists = sorted(({"id": aid, "name": name} for aid, name in seen),
                     key=lambda a: a["name"].lower())
    is_htmx = _is_htmx(request)
    ctx = {
        "tracks": filtered,
        "total": len(rows),
        "q": q,
        "artist_filter": artist_filter,
        "dist_filter": dist_filter,
        "sort": sort if sort in _SORT_FIELDS else "",
        "dir": "desc" if dir == "desc" else "asc",
        "artists": artists,
        "is_htmx": is_htmx,
    }
    if is_htmx:
        return _templates.TemplateResponse(request, "catalog/_table_body.html", ctx)
    return _templates.TemplateResponse(request, "catalog/list.html", ctx)
