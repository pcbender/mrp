from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mrp.admin.deps import get_repo_root
from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.release import slugify
from mrp.core.validate import validate_repository

_SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "release.schema.json"


def _validate_release_dict(data: dict) -> list[dict]:
    schema = json.loads(_SCHEMA_PATH.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for err in validator.iter_errors(data):
        field = ".".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append({"field": field, "message": err.message, "severity": "error"})
    return errors

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

PLATFORM_KEYS = [
    "spotify", "apple_music", "youtube", "youtube_music",
    "tidal", "amazon_music", "deezer", "soundcloud", "bandcamp", "pandora",
]

STATUSES = ["draft", "staged", "verified", "approved", "live", "failed", "archived"]


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _load_all_releases(root: Path) -> list[dict[str, Any]]:
    releases_dir = root / "content" / "releases"
    rows = []
    for path in sorted(releases_dir.glob("*.yaml")):
        try:
            data = load_structured_record(path)
        except Exception:
            continue
        rel = data.get("release")
        if not isinstance(rel, dict):
            continue
        links = rel.get("links") or {}
        platform_count = sum(1 for k in PLATFORM_KEYS if links.get(k))
        rows.append({
            "slug": path.stem,
            "title": rel.get("title", path.stem),
            "artist_id": rel.get("artist_id", ""),
            "model": rel.get("model", ""),
            "release_type": rel.get("release_type", ""),
            "status": rel.get("status", ""),
            "release_date": rel.get("release_date") or "",
            "platform_count": platform_count,
        })
    rows.sort(key=lambda r: r["release_date"] or "0000", reverse=True)
    return rows


def _filter_releases(rows: list[dict], q: str, status_f: str, model_f: str) -> list[dict]:
    if q:
        q_lower = q.lower()
        rows = [r for r in rows if q_lower in r["title"].lower() or q_lower in r["artist_id"].lower()]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if model_f:
        rows = [r for r in rows if r["model"] == model_f]
    return rows


@router.get("/releases", response_class=HTMLResponse)
async def releases_list(
    request: Request,
    q: str = "",
    status_filter: str = "",
    model_filter: str = "",
):
    root = get_repo_root()
    rows = _load_all_releases(root)
    filtered = _filter_releases(rows, q, status_filter, model_filter)
    ctx = {
        "releases": filtered,
        "total": len(rows),
        "q": q,
        "status_filter": status_filter,
        "model_filter": model_filter,
        "statuses": STATUSES,
    }
    if _is_htmx(request):
        return _templates.TemplateResponse(request, "releases/_table_body.html", ctx)
    return _templates.TemplateResponse(request, "releases/list.html", ctx)


@router.get("/releases/new", response_class=HTMLResponse)
async def release_new(request: Request):
    root = get_repo_root()
    artists = _load_artists(root)
    return _templates.TemplateResponse(request, "releases/new.html", {"artists": artists})


@router.post("/releases", response_class=HTMLResponse)
async def release_create(
    request: Request,
    title: str = Form(...),
    artist_id: str = Form(...),
    model: str = Form(...),
    release_type: str = Form(...),
):
    root = get_repo_root()
    slug = slugify(title)
    path = root / "content" / "releases" / f"{slug}.yaml"
    if path.exists():
        return HTMLResponse(
            f'<div class="flash flash-error">A release with slug <code>{slug}</code> already exists.</div>',
            status_code=409,
        )
    skeleton = _new_release_skeleton(slug, title, artist_id, model, release_type)
    path.write_text(serialize_structured_record(path, {"release": skeleton}))
    return RedirectResponse(url=f"/releases/{slug}/edit", status_code=303)


@router.get("/releases/{slug}/edit", response_class=HTMLResponse)
async def release_edit(request: Request, slug: str):
    root = get_repo_root()
    path = root / "content" / "releases" / f"{slug}.yaml"
    if not path.exists():
        return HTMLResponse(f"Release <b>{slug}</b> not found.", status_code=404)
    data = load_structured_record(path)
    rel = data.get("release", {})
    artists = _load_artists(root)
    return _templates.TemplateResponse(request, "releases/edit.html", {
        "slug": slug,
        "release": rel,
        "artists": artists,
        "statuses": STATUSES,
        "platform_keys": PLATFORM_KEYS,
    })


@router.post("/releases/{slug}", response_class=HTMLResponse)
async def release_save(request: Request, slug: str):
    root = get_repo_root()
    path = root / "content" / "releases" / f"{slug}.yaml"
    if not path.exists():
        return HTMLResponse(f"Release <b>{slug}</b> not found.", status_code=404)

    original_data = load_structured_record(path)
    original = original_data.get("release", {})
    form = await request.form()
    updated = _form_to_release(dict(form), original)
    data = {"release": updated}

    errors = _validate_release_dict(data)
    if errors:
        return _templates.TemplateResponse(request, "releases/_validation.html", {
            "errors": errors,
        }, status_code=422)

    path.write_text(serialize_structured_record(path, data))
    response = HTMLResponse('<div class="flash flash-ok">Saved successfully.</div>')
    response.headers["HX-Trigger"] = "releaseSaved"
    return response


@router.get("/releases/{slug}/validate", response_class=HTMLResponse)
async def release_validate(request: Request, slug: str):
    root = get_repo_root()
    result = validate_repository(root, release=slug)
    errors = result.get("errors") or []
    return _templates.TemplateResponse(request, "releases/_validation.html", {
        "errors": errors,
        "status": result.get("status"),
    })


@router.get("/missing-links", response_class=HTMLResponse)
async def missing_links(request: Request):
    root = get_repo_root()
    releases_dir = root / "content" / "releases"
    rows = []
    for path in sorted(releases_dir.glob("*.yaml")):
        try:
            data = load_structured_record(path)
        except Exception:
            continue
        rel = data.get("release")
        if not isinstance(rel, dict):
            continue
        links = rel.get("links") or {}
        missing = [k for k in PLATFORM_KEYS if not links.get(k)]
        if missing:
            rows.append({
                "slug": path.stem,
                "title": rel.get("title", path.stem),
                "artist_id": rel.get("artist_id", ""),
                "missing": missing,
                "present": [k for k in PLATFORM_KEYS if links.get(k)],
            })
    return _templates.TemplateResponse(request, "missing_links.html", {
        "rows": rows,
        "platform_keys": PLATFORM_KEYS,
    })


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_artists(root: Path) -> list[dict[str, Any]]:
    artists_dir = root / "content" / "artists"
    result = []
    for path in sorted(artists_dir.glob("*.yaml")):
        try:
            data = load_structured_record(path)
        except Exception:
            continue
        a = data.get("artist", {})
        result.append({"id": a.get("id", path.stem), "name": a.get("name", path.stem)})
    return result


def _str_or_none(v: Any) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _bool_field(form: dict, key: str) -> bool:
    return form.get(key) in {"on", "true", "1", True}


def _form_to_release(form: dict, original: dict) -> dict:
    rel = dict(original)

    # Top-level scalars
    for key in ["title", "title_ascii", "artist_id", "model", "release_type", "status",
                "release_date", "label", "publisher", "upc", "catalog_number",
                "cover_image", "hero_image", "summary", "description"]:
        if key in form:
            rel[key] = _str_or_none(form[key])

    # Ensure required strings stay non-null
    for key in ["title", "artist_id", "model", "release_type", "status", "cover_image"]:
        if not rel.get(key) and key in form:
            rel[key] = form[key]

    # Links
    links = dict(rel.get("links") or {})
    for k in PLATFORM_KEYS:
        field = f"links_{k}"
        if field in form:
            links[k] = _str_or_none(form[field])
    rel["links"] = links

    # Credits
    credits = dict(rel.get("credits") or {})
    for k in ["primary_artist", "songwriter", "lyrics", "producer", "mastering"]:
        field = f"credits_{k}"
        if field in form:
            credits[k] = _str_or_none(form[field])
    rel["credits"] = credits

    # SEO
    seo = dict(rel.get("seo") or {})
    if "seo_title" in form:
        seo["title"] = form["seo_title"] or ""
    if "seo_description" in form:
        seo["description"] = form["seo_description"] or ""
    rel["seo"] = seo

    # Automation
    automation = dict(rel.get("automation") or {})
    automation["allow_auto_publish"] = _bool_field(form, "allow_auto_publish")
    rel["automation"] = automation

    # Song (model:song)
    if rel.get("model") == "song":
        song = dict(rel.get("song") or {})
        for k in ["title", "slug", "isrc", "duration", "preview_audio",
                   "lyrics_text", "lyrics_raw", "lyrics_source", "style"]:
            field = f"song_{k}"
            if field in form:
                song[k] = _str_or_none(form[field])
        song["explicit"] = _bool_field(form, "song_explicit")
        song["instrumental"] = _bool_field(form, "song_instrumental")
        if "song_number" in form:
            try:
                song["number"] = int(form["song_number"]) if form["song_number"] else None
            except (ValueError, TypeError):
                song["number"] = None
        song_links = dict((song.get("links") or {}))
        for k in PLATFORM_KEYS:
            field = f"song_links_{k}"
            if field in form:
                song_links[k] = _str_or_none(form[field])
        song["links"] = song_links
        rel["song"] = song

    # Tracks (model:album)
    elif rel.get("model") == "album":
        try:
            track_count = int(form.get("track_count", 0))
        except (ValueError, TypeError):
            track_count = 0
        tracks = list(rel.get("tracks") or [])
        for i in range(track_count):
            track = dict(tracks[i]) if i < len(tracks) else {}
            for k in ["title", "slug", "isrc", "duration", "preview_audio",
                       "lyrics_text", "lyrics_raw", "lyrics_source", "style"]:
                field = f"track_{i}_{k}"
                if field in form:
                    track[k] = _str_or_none(form[field])
            track["explicit"] = _bool_field(form, f"track_{i}_explicit")
            track["instrumental"] = _bool_field(form, f"track_{i}_instrumental")
            try:
                track["number"] = int(form[f"track_{i}_number"]) if form.get(f"track_{i}_number") else i + 1
            except (ValueError, TypeError):
                track["number"] = i + 1
            track_links = dict((track.get("links") or {}))
            for k in PLATFORM_KEYS:
                field = f"track_{i}_links_{k}"
                if field in form:
                    track_links[k] = _str_or_none(form[field])
            track["links"] = track_links
            if i < len(tracks):
                tracks[i] = track
            else:
                tracks.append(track)
        rel["tracks"] = tracks

    return rel


def _new_release_skeleton(
    slug: str, title: str, artist_id: str, model: str, release_type: str
) -> dict[str, Any]:
    skeleton: dict[str, Any] = {
        "id": slug,
        "slug": slug,
        "title": title,
        "artist_id": artist_id,
        "model": model,
        "release_type": release_type,
        "status": "draft",
        "release_date": None,
        "label": None,
        "publisher": None,
        "upc": None,
        "catalog_number": None,
        "cover_image": f"site/public/assets/releases/{slug}/cover.jpg",
        "hero_image": None,
        "summary": None,
        "description": None,
        "credits": {
            "primary_artist": None,
            "songwriter": None,
            "lyrics": None,
            "producer": None,
            "mastering": None,
        },
        "links": {k: None for k in PLATFORM_KEYS},
        "seo": {
            "title": f"{title}",
            "description": f"{title} on Maricopa Records.",
        },
        "automation": {"allow_auto_publish": False},
    }
    if model == "song":
        skeleton["song"] = {
            "number": 1,
            "title": title,
            "slug": slug,
            "isrc": None,
            "duration": None,
            "explicit": False,
            "instrumental": False,
            "preview_audio": None,
            "lyrics_text": None,
            "lyrics_raw": None,
            "lyrics_source": None,
            "style": None,
            "links": {k: None for k in PLATFORM_KEYS},
            "hints": {},
        }
    else:
        skeleton["tracks"] = []
    return skeleton
