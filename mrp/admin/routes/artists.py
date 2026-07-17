from __future__ import annotations

from html import escape as _escape
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
MEMBER_STATUSES = ["current", "former", "guest"]
MEMBER_IMAGE_EXTENSIONS = {".jpg", ".png", ".webp", ".gif"}
LINK_KEYS = [
    "spotify", "apple_music", "youtube", "youtube_music", "bandcamp",
    "soundcloud", "instagram", "facebook", "tiktok", "website",
]
_TEXT_FIELDS = [
    "name", "sort_name", "type", "label", "default_publisher",
    "bio_short", "bio_long", "promo_blurb", "image", "reference_image",
    "likeness_notes", "visibility",
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
        "member_rows": _member_rows(artist.get("members")),
        "show_members": artist.get("type") == "band" or bool(artist.get("members")),
        "flash": flash,
        "errors": errors or [],
    }


def _member_sort_key(member: dict[str, Any]) -> tuple[int, str]:
    order = member.get("display_order")
    return (order if isinstance(order, int) else 9999, str(member.get("name") or ""))


def _member_rows(members: list | None) -> list[dict[str, Any]]:
    rows = []
    for member in sorted(members or [], key=_member_sort_key):
        rows.append({
            "slug": member.get("slug"),
            "name": member.get("name"),
            "roles": ", ".join(member.get("roles") or []),
            "status": member.get("status") or "current",
            "display_order": member.get("display_order"),
            "has_roles": bool(member.get("roles")),
            "has_bio": bool(member.get("bio")),
            "has_image": bool(member.get("image")),
            "has_reference": bool(member.get("reference_image")),
            "has_likeness": bool(member.get("likeness_notes")),
        })
    return rows


async def _write_image(dest_dir: Path, basename: str,
                       upload: Any) -> tuple[str | None, str | None]:
    """Validate and write an upload as {basename}.{ext} in dest_dir.

    Keeps a single image per basename — drops any other-extension leftover.
    Returns (filename, None) on success or (None, error message).
    """
    ext = Path(upload.filename).suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in MEMBER_IMAGE_EXTENSIONS:
        return None, f"Unsupported image type: {ext or '(none)'} — use jpg, png, webp, or gif."
    contents = await upload.read()
    if not contents:
        return None, "Empty image file."
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old_ext in MEMBER_IMAGE_EXTENSIONS:
        old = dest_dir / f"{basename}{old_ext}"
        if old.exists() and old_ext != ext:
            old.unlink()
    (dest_dir / f"{basename}{ext}").write_bytes(contents)
    return f"{basename}{ext}", None


async def _store_identity_image(root: Path, artist_id: str, slug: str,
                                upload: Any) -> tuple[str | None, str | None]:
    """Save a public identity image under site/public/assets/artists/{id}/.

    Used for both member images (slug = member slug) and the artist's own
    public image (slug = artist id). Returns (site-relative path, None) on
    success or (None, error message).
    """
    name, err = await _write_image(
        root / "site" / "public" / "assets" / "artists" / artist_id, slug, upload)
    if err:
        return None, err
    return f"/assets/artists/{artist_id}/{name}", None


async def _store_reference_image(root: Path, artist_id: str,
                                 upload: Any) -> tuple[str | None, str | None]:
    """Save the base likeness reference under assets/artists/{id}/.

    Reference images are git-tracked (the Changes page's data pathspecs cover
    assets/) but never published — the site build only serves site/public/.
    Returns (repo-relative path, None) on success or (None, error message).
    """
    name, err = await _write_image(root / "assets" / "artists" / artist_id, "reference", upload)
    if err:
        return None, err
    return f"assets/artists/{artist_id}/{name}", None


async def _store_member_reference_image(root: Path, artist_id: str, slug: str,
                                        upload: Any) -> tuple[str | None, str | None]:
    """Save a member's base likeness reference under assets/artists/{id}/members/.

    The members/ subdirectory keeps member references clear of the artist's
    own reference.* file. Same git-tracked, never-published contract as
    _store_reference_image.
    """
    name, err = await _write_image(
        root / "assets" / "artists" / artist_id / "members", slug, upload)
    if err:
        return None, err
    return f"assets/artists/{artist_id}/members/{name}", None


def _find_member(artist: dict[str, Any], slug: str) -> dict[str, Any] | None:
    for member in artist.get("members") or []:
        if member.get("slug") == slug:
            return member
    return None


def _member_from_form(form: dict[str, Any], fallback_slug: str = "") -> dict[str, Any]:
    def clean(key: str) -> str | None:
        value = str(form.get(key) or "").strip()
        return value or None

    name = clean("member_name")
    slug = slugify(str(form.get("member_slug") or "").strip() or (name or fallback_slug))
    roles = [r.strip() for r in str(form.get("member_roles") or "").split(",") if r.strip()]
    status = str(form.get("member_status") or "").strip() or None
    order_raw = str(form.get("member_display_order") or "").strip()
    try:
        display_order = int(order_raw) if order_raw else None
    except ValueError:
        display_order = None
    return {
        "slug": slug,
        "name": name,
        "roles": roles,
        "status": status if status in MEMBER_STATUSES else None,
        "display_order": display_order,
        "image": clean("member_image"),
        "reference_image": clean("member_reference_image"),
        "likeness_notes": clean("member_likeness_notes"),
        "bio": clean("member_bio"),
    }


def _member_form_context(artist: dict[str, Any], member: dict[str, Any],
                         is_new: bool, flash: dict[str, str] | None = None,
                         errors: list | None = None) -> dict[str, Any]:
    return {
        "artist": artist,
        "member": member,
        "is_new": is_new,
        "statuses": MEMBER_STATUSES,
        "flash": flash,
        "errors": errors or [],
    }


def _errors_response(errors: list) -> HTMLResponse:
    """Render just the flash + error list into #save-result (not the whole page)."""
    rows = "".join(
        f'<div class="err-row"><span class="err-field">{_escape(str(e.get("field", "")))}</span>'
        f'{_escape(str(e.get("message", "")))}</div>'
        for e in errors
    )
    return HTMLResponse(
        '<div class="flash flash-error">Not saved — the record failed validation.</div>'
        f'<div class="validation-errors">{rows}</div>',
        status_code=422,
    )


def _member_saved_redirect(artist_id: str) -> HTMLResponse:
    """On a successful member save, load the artist editor."""
    response = HTMLResponse('<div class="flash flash-ok">Saved.</div>')
    response.headers["HX-Redirect"] = f"/artists/{artist_id}"
    return response


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

    for field, input_name, store in (
        ("image", "image_file",
         lambda up: _store_identity_image(root, artist_id, artist_id, up)),
        ("reference_image", "reference_image_file",
         lambda up: _store_reference_image(root, artist_id, up)),
    ):
        upload = form.get(input_name)
        if upload is not None and getattr(upload, "filename", ""):
            image_path, err = await store(upload)
            if err:
                context = _form_context(
                    artist,
                    flash={"cls": "error", "text": "Not saved — the image upload failed."},
                    errors=[{"field": field, "message": err}],
                )
                return _templates.TemplateResponse(request, "artists/form.html", context, status_code=422)
            artist[field] = image_path
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


# --- Band members ------------------------------------------------------------

def _duplicate_slug_error(path: Path, members: list, slug: str,
                          ignore_index: int | None = None) -> list:
    for index, member in enumerate(members):
        if index == ignore_index:
            continue
        if member.get("slug") == slug:
            return [{
                "field": "members.slug",
                "message": f"Another member already uses the slug '{slug}'.",
                "file_path": str(path),
                "severity": "error",
            }]
    return []


@router.get("/{artist_id}/members/new", response_class=HTMLResponse)
async def member_new(request: Request, artist_id: str):
    root = get_repo_root()
    path = _artist_path(root, artist_id)
    if not path.exists():
        return HTMLResponse(f"Artist <b>{artist_id}</b> not found.", status_code=404)
    artist = load_structured_record(path).get("artist") or {}
    blank = {"slug": "", "name": "", "roles": [], "status": "current",
             "display_order": len(artist.get("members") or []) + 1,
             "image": None, "reference_image": None, "likeness_notes": None, "bio": None}
    return _templates.TemplateResponse(
        request, "artists/member_form.html", _member_form_context(artist, blank, is_new=True))


@router.post("/{artist_id}/members", response_class=HTMLResponse)
async def member_create(request: Request, artist_id: str):
    root = get_repo_root()
    path = _artist_path(root, artist_id)
    if not path.exists():
        return HTMLResponse(f"Artist <b>{artist_id}</b> not found.", status_code=404)
    data = load_structured_record(path)
    artist = data.get("artist") or {}
    form = await request.form()
    member = _member_from_form(dict(form))

    if not member["name"] or not member["slug"]:
        return _errors_response([{"field": "members", "message": "Name and slug are required."}])

    members = list(artist.get("members") or [])
    errors = _duplicate_slug_error(path, members, member["slug"])
    if errors:
        return _errors_response(errors)

    upload = form.get("member_image_file")
    if upload is not None and getattr(upload, "filename", ""):
        image_path, err = await _store_identity_image(root, artist_id, member["slug"], upload)
        if err:
            return _errors_response([{"field": "members.image", "message": err}])
        member["image"] = image_path

    upload = form.get("member_reference_image_file")
    if upload is not None and getattr(upload, "filename", ""):
        image_path, err = await _store_member_reference_image(root, artist_id, member["slug"], upload)
        if err:
            return _errors_response([{"field": "members.reference_image", "message": err}])
        member["reference_image"] = image_path

    members.append(member)
    artist["members"] = members
    data["artist"] = artist
    errors = validate_schema(path, data, _SCHEMA_PATH)
    if errors:
        return _errors_response(errors)

    path.write_text(serialize_structured_record(path, data))
    return _member_saved_redirect(artist_id)


@router.get("/{artist_id}/members/{slug}", response_class=HTMLResponse)
async def member_detail(request: Request, artist_id: str, slug: str):
    root = get_repo_root()
    path = _artist_path(root, artist_id)
    if not path.exists():
        return HTMLResponse(f"Artist <b>{artist_id}</b> not found.", status_code=404)
    artist = load_structured_record(path).get("artist") or {}
    member = _find_member(artist, slug)
    if member is None:
        return HTMLResponse(f"Member <b>{slug}</b> not found.", status_code=404)
    return _templates.TemplateResponse(
        request, "artists/member_form.html", _member_form_context(artist, member, is_new=False))


@router.post("/{artist_id}/members/{slug}", response_class=HTMLResponse)
async def member_save(request: Request, artist_id: str, slug: str):
    root = get_repo_root()
    path = _artist_path(root, artist_id)
    if not path.exists():
        return HTMLResponse(f"Artist <b>{artist_id}</b> not found.", status_code=404)
    data = load_structured_record(path)
    artist = data.get("artist") or {}
    members = list(artist.get("members") or [])
    index = next((i for i, m in enumerate(members) if m.get("slug") == slug), None)
    if index is None:
        return HTMLResponse(f"Member <b>{slug}</b> not found.", status_code=404)

    form = await request.form()
    member = _member_from_form(dict(form), fallback_slug=slug)
    if not member["name"] or not member["slug"]:
        return _errors_response([{"field": "members", "message": "Name and slug are required."}])

    errors = _duplicate_slug_error(path, members, member["slug"], ignore_index=index)
    if errors:
        return _errors_response(errors)

    upload = form.get("member_image_file")
    if upload is not None and getattr(upload, "filename", ""):
        image_path, err = await _store_identity_image(root, artist_id, member["slug"], upload)
        if err:
            return _errors_response([{"field": "members.image", "message": err}])
        member["image"] = image_path

    upload = form.get("member_reference_image_file")
    if upload is not None and getattr(upload, "filename", ""):
        image_path, err = await _store_member_reference_image(root, artist_id, member["slug"], upload)
        if err:
            return _errors_response([{"field": "members.reference_image", "message": err}])
        member["reference_image"] = image_path

    members[index] = member
    artist["members"] = members
    data["artist"] = artist
    errors = validate_schema(path, data, _SCHEMA_PATH)
    if errors:
        return _errors_response(errors)

    path.write_text(serialize_structured_record(path, data))
    return _member_saved_redirect(artist_id)


@router.post("/{artist_id}/members/{slug}/delete", response_class=HTMLResponse)
async def member_delete(request: Request, artist_id: str, slug: str):
    root = get_repo_root()
    path = _artist_path(root, artist_id)
    if not path.exists():
        return HTMLResponse(f"Artist <b>{artist_id}</b> not found.", status_code=404)
    data = load_structured_record(path)
    artist = data.get("artist") or {}
    members = [m for m in (artist.get("members") or []) if m.get("slug") != slug]
    if members:
        artist["members"] = members
    else:
        artist.pop("members", None)  # members has minItems:1 — drop the key when empty
    data["artist"] = artist
    path.write_text(serialize_structured_record(path, data))
    return RedirectResponse(url=f"/artists/{artist_id}", status_code=303)
