from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mrp.admin.deps import get_repo_root
from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.release import slugify
from mrp.core.validate import validate_schema

router = APIRouter(prefix="/artists")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_SCHEMA_PATH = Path(__file__).parents[2] / "schemas" / "artist.schema.json"

ARTIST_TYPES = ["solo", "band", "project"]
VISIBILITIES = ["public", "draft", "hidden", "archived"]
LINK_KEYS = [
    "spotify", "apple_music", "youtube", "youtube_music", "bandcamp",
    "soundcloud", "instagram", "facebook", "tiktok", "website",
]
_TEXT_FIELDS = [
    "name", "sort_name", "type", "label", "default_publisher",
    "bio_short", "bio_long", "promo_blurb", "image", "visibility",
]


def _artist_path(root: Path, artist_id: str) -> Path:
    return root / "content" / "artists" / f"{artist_id}.yaml"


def _release_counts(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in (root / "content" / "releases").glob("*.yaml"):
        try:
            rel = load_structured_record(path).get("release") or {}
        except Exception:
            continue
        artist_id = rel.get("artist_id")
        if artist_id:
            counts[artist_id] = counts.get(artist_id, 0) + 1
    return counts


def _form_context(artist: dict[str, Any], flash: dict[str, str] | None = None,
                  errors: list | None = None) -> dict[str, Any]:
    links = artist.get("links") or {}
    link_keys = LINK_KEYS + sorted(k for k in links if k not in LINK_KEYS)
    return {
        "artist": artist,
        "types": ARTIST_TYPES,
        "visibilities": VISIBILITIES,
        "link_keys": link_keys,
        "flash": flash,
        "errors": errors or [],
    }


@router.get("", response_class=HTMLResponse)
async def artists_list(request: Request):
    root = get_repo_root()
    counts = _release_counts(root)
    rows = []
    for path in sorted((root / "content" / "artists").glob("*.yaml")):
        try:
            artist = load_structured_record(path).get("artist") or {}
        except Exception:
            continue
        rows.append({
            "id": artist.get("id", path.stem),
            "name": artist.get("name", path.stem),
            "type": artist.get("type") or "—",
            "visibility": artist.get("visibility", ""),
            "releases": counts.get(artist.get("id", path.stem), 0),
            "links": sum(1 for v in (artist.get("links") or {}).values() if v),
        })
    return _templates.TemplateResponse(request, "artists/list.html", {"rows": rows})


@router.get("/new", response_class=HTMLResponse)
async def artist_new(request: Request):
    return _templates.TemplateResponse(request, "artists/new.html", {"types": ARTIST_TYPES})


@router.post("", response_class=HTMLResponse)
async def artist_create(
    request: Request,
    name: str = Form(...),
    artist_id: str = Form(""),
    artist_type: str = Form("solo"),
):
    root = get_repo_root()
    if not name.strip():
        return HTMLResponse('<div class="flash flash-error">Name is required.</div>', status_code=400)
    artist_id = slugify(artist_id or name)
    path = _artist_path(root, artist_id)
    if path.exists() or (path.parent / f"{artist_id}.json").exists():
        return HTMLResponse(
            f'<div class="flash flash-error">An artist with id <code>{artist_id}</code> already exists.</div>',
            status_code=409,
        )
    record = {
        "artist": {
            "id": artist_id,
            "name": name.strip(),
            "sort_name": name.strip(),
            "type": artist_type if artist_type in ARTIST_TYPES else "solo",
            "label": "Maricopa Records",
            "default_publisher": "Maricopa Publishing",
            "bio_short": None,
            "bio_long": None,
            "promo_blurb": None,
            "image": None,
            "links": {key: None for key in LINK_KEYS[:6]},
            "visibility": "draft",
            "bio_auto_generated": False,
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_structured_record(path, record))
    return RedirectResponse(url=f"/artists/{artist_id}", status_code=303)


@router.get("/{artist_id}", response_class=HTMLResponse)
async def artist_edit(request: Request, artist_id: str):
    root = get_repo_root()
    path = _artist_path(root, artist_id)
    if not path.exists():
        return HTMLResponse(f"Artist <b>{artist_id}</b> not found.", status_code=404)
    artist = load_structured_record(path).get("artist") or {}
    return _templates.TemplateResponse(request, "artists/form.html", _form_context(artist))


@router.post("/{artist_id}", response_class=HTMLResponse)
async def artist_save(request: Request, artist_id: str):
    root = get_repo_root()
    path = _artist_path(root, artist_id)
    if not path.exists():
        return HTMLResponse(f"Artist <b>{artist_id}</b> not found.", status_code=404)
    form = await request.form()

    data = load_structured_record(path)
    artist = data.get("artist") or {}
    for key in _TEXT_FIELDS:
        value = str(form.get(key) or "").strip()
        artist[key] = value or None
    artist["visibility"] = str(form.get("visibility") or "draft")
    artist["bio_auto_generated"] = form.get("bio_auto_generated") is not None

    links = dict(artist.get("links") or {})
    for key, value in form.multi_items():
        if key.startswith("link_"):
            links[key[5:]] = str(value).strip() or None
    artist["links"] = links
    data["artist"] = artist

    errors = validate_schema(path, data, _SCHEMA_PATH)
    if errors:
        context = _form_context(
            artist,
            flash={"cls": "error", "text": "Not saved — the record failed schema validation."},
            errors=errors,
        )
        return _templates.TemplateResponse(request, "artists/form.html", context, status_code=422)

    path.write_text(serialize_structured_record(path, data))
    context = _form_context(artist, flash={"cls": "ok", "text": f"Saved {artist_id}."})
    return _templates.TemplateResponse(request, "artists/form.html", context)
