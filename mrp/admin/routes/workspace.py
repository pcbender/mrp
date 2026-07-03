"""Release workspace routes: stage pages, slice saves, track detail."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mrp.admin import db
from mrp.admin.deps import get_repo_root
from mrp.admin.workspace import (
    PLATFORM_KEYS,
    STAGES,
    STAGE_IDS,
    STATUSES,
    bool_field,
    effective_master_path,
    stage_statuses,
    str_or_none,
    track_completion,
    track_units,
    validate_release_dict,
)
from mrp.core.migrate_site import load_structured_record, serialize_structured_record

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
_templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else {}

_STUBS = {
    "critic": (
        "Critic",
        "Run per-track reviews, the album/EP pass, and recontextualized track reviews — "
        "each with human edit and approval before writeback to the site.",
    ),
    "promoter": (
        "Promoter",
        "Update the artist promo blurb and bio from the newly released material, "
        "with human review before saving.",
    ),
    "publish": (
        "Build / Publish",
        "Validate, build, stage, verify, approve, publish, and rollback — the full "
        "MRP pipeline with a recommended-next-step action.",
    ),
    "monitoring": (
        "Link Monitoring",
        "Ongoing checks for streaming links that appear after release day; absorbs "
        "the Missing Links report.",
    ),
}


def _release_path(root: Path, slug: str) -> Path:
    return root / "content" / "releases" / f"{slug}.yaml"


def _workspace_ctx(root: Path, slug: str, active_stage: str) -> dict | None:
    path = _release_path(root, slug)
    if not path.exists():
        return None
    data = load_structured_record(path)
    release = data.get("release") or {}
    return {
        "slug": slug,
        "release": release,
        "stages": STAGES,
        "stage_status": stage_statuses(root, slug, release),
        "active_stage": active_stage,
        "platform_keys": PLATFORM_KEYS,
        "statuses": STATUSES,
    }


def _not_found(slug: str) -> HTMLResponse:
    return HTMLResponse(f"Release <b>{slug}</b> not found.", status_code=404)


def _save_ok() -> HTMLResponse:
    response = HTMLResponse('<div class="flash flash-ok">Saved successfully.</div>')
    response.headers["HX-Trigger"] = "releaseSaved"
    return response


def _validation_errors(request: Request, errors: list[dict]) -> HTMLResponse:
    return _templates.TemplateResponse(
        request, "releases/_validation.html", {"errors": errors}, status_code=422
    )


@router.get("/releases/{slug}/tabs", response_class=HTMLResponse)
async def stage_tabs(request: Request, slug: str, active: str = ""):
    root = get_repo_root()
    ctx = _workspace_ctx(root, slug, active or "details")
    if ctx is None:
        return _not_found(slug)
    return _templates.TemplateResponse(request, "releases/workspace/_stage_tabs.html", ctx)


# --- Slice saves -------------------------------------------------------------

@router.post("/releases/{slug}/details", response_class=HTMLResponse)
async def details_save(request: Request, slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)

    data = load_structured_record(path)
    rel = data.get("release") or {}
    form = dict(await request.form())

    for key in ["title", "artist_id", "status", "release_date", "label", "publisher",
                "upc", "catalog_number", "cover_image", "hero_image", "summary",
                "description"]:
        if key in form:
            rel[key] = str_or_none(form[key])
    # Required strings must stay non-null even when submitted blank
    for key in ["title", "artist_id", "cover_image"]:
        if not rel.get(key) and key in form:
            rel[key] = form[key]

    credits = dict(rel.get("credits") or {})
    for k in ["primary_artist", "songwriter", "lyrics", "producer", "mastering"]:
        field = f"credits_{k}"
        if field in form:
            credits[k] = str_or_none(form[field])
    rel["credits"] = credits

    seo = dict(rel.get("seo") or {})
    if "seo_title" in form:
        seo["title"] = form["seo_title"] or ""
    if "seo_description" in form:
        seo["description"] = form["seo_description"] or ""
    rel["seo"] = seo

    automation = rel.setdefault("automation", {})
    automation["allow_auto_publish"] = bool_field(form, "allow_auto_publish")

    errors = validate_release_dict(data)
    if errors:
        return _validation_errors(request, errors)
    path.write_text(serialize_structured_record(path, data))
    return _save_ok()


@router.post("/releases/{slug}/links/{platform}", response_class=HTMLResponse)
async def link_save(request: Request, slug: str, platform: str):
    if platform not in PLATFORM_KEYS:
        return HTMLResponse("Unknown platform", status_code=404)
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)

    data = load_structured_record(path)
    rel = data.get("release") or {}
    form = dict(await request.form())

    url = str_or_none(form.get("url"))
    links = rel.setdefault("links", {})
    links[platform] = url
    if url:
        automation = rel.get("automation") or {}
        na = [p for p in (automation.get("links_na") or []) if p != platform]
        if "links_na" in automation:
            automation["links_na"] = na

    errors = validate_release_dict(data)
    if errors:
        return _validation_errors(request, errors)
    path.write_text(serialize_structured_record(path, data))
    return _link_row_response(request, root, slug, platform)


@router.post("/releases/{slug}/links/{platform}/na", response_class=HTMLResponse)
async def link_toggle_na(request: Request, slug: str, platform: str):
    if platform not in PLATFORM_KEYS:
        return HTMLResponse("Unknown platform", status_code=404)
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)

    data = load_structured_record(path)
    rel = data.get("release") or {}
    automation = rel.setdefault("automation", {})
    na = set(automation.get("links_na") or [])
    if platform in na:
        na.discard(platform)
    else:
        na.add(platform)
    automation["links_na"] = sorted(na)

    errors = validate_release_dict(data)
    if errors:
        return _validation_errors(request, errors)
    path.write_text(serialize_structured_record(path, data))
    return _link_row_response(request, root, slug, platform)


def _link_row_response(request: Request, root: Path, slug: str, platform: str) -> HTMLResponse:
    data = load_structured_record(_release_path(root, slug))
    rel = data.get("release") or {}
    links = rel.get("links") or {}
    na = set((rel.get("automation") or {}).get("links_na") or [])
    response = _templates.TemplateResponse(request, "releases/workspace/_link_row.html", {
        "slug": slug,
        "platform": platform,
        "url": links.get(platform),
        "is_na": platform in na,
    })
    response.headers["HX-Trigger"] = "releaseSaved"
    return response


# --- Track detail (must register before the generic {stage} route) ----------

@router.get("/releases/{slug}/tracks/{track_slug}", response_class=HTMLResponse)
async def track_detail(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _workspace_ctx(root, slug, "tracks")
    if ctx is None:
        return _not_found(slug)
    release = ctx["release"]
    unit = next((u for u in track_units(release) if u["slug"] == track_slug), None)
    if unit is None:
        return HTMLResponse(f"Track <b>{track_slug}</b> not found.", status_code=404)
    pipeline_status = {
        "sampler": db.get_latest_job_by_command(f"{slug}/sampler"),
    }
    ctx.update({
        "unit": unit,
        "track": unit["track"],
        "track_slug": track_slug,
        "master_fallback": effective_master_path(release, unit["index"], unit["track"]),
        "pipeline_status": pipeline_status,
        "step": "sampler",
        "step_label": "Sampler (30s snippet)",
        "job": pipeline_status["sampler"],
        "critic_settings": {},
    })
    return _templates.TemplateResponse(request, "releases/workspace/track_detail.html", ctx)


@router.post("/releases/{slug}/tracks/{track_slug}", response_class=HTMLResponse)
async def track_save(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)

    data = load_structured_record(path)
    rel = data.get("release") or {}
    unit = next((u for u in track_units(rel) if u["slug"] == track_slug), None)
    if unit is None:
        return HTMLResponse(f"Track <b>{track_slug}</b> not found.", status_code=404)
    track = unit["track"]
    form = dict(await request.form())

    for k in ["title", "slug", "isrc", "duration", "preview_audio", "master_path",
              "lyrics_text", "lyrics_raw", "lyrics_source", "style"]:
        field = f"track_{k}"
        if field in form:
            track[k] = str_or_none(form[field])
    if not track.get("title") and "track_title" in form:
        track["title"] = form["track_title"]
    if not track.get("slug"):
        track["slug"] = track_slug
    track["explicit"] = bool_field(form, "track_explicit")
    track["instrumental"] = bool_field(form, "track_instrumental")
    if "track_number" in form:
        try:
            track["number"] = int(form["track_number"]) if form["track_number"] else None
        except (ValueError, TypeError):
            track["number"] = None

    links = dict(track.get("links") or {})
    for k in PLATFORM_KEYS:
        field = f"track_links_{k}"
        if field in form:
            links[k] = str_or_none(form[field])
    track["links"] = links

    errors = validate_release_dict(data)
    if errors:
        return _validation_errors(request, errors)
    path.write_text(serialize_structured_record(path, data))

    new_slug = track.get("slug") or track_slug
    if new_slug != track_slug:
        response = HTMLResponse('<div class="flash flash-ok">Saved — slug changed.</div>')
        response.headers["HX-Redirect"] = f"/releases/{slug}/tracks/{new_slug}"
        return response
    return _save_ok()


# --- Stage dispatch (generic route registered last) --------------------------

@router.get("/releases/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def workspace_root(slug: str):
    return RedirectResponse(url=f"/releases/{slug}/details", status_code=303)


@router.get("/releases/{slug}/{stage}", response_class=HTMLResponse)
async def stage_page(request: Request, slug: str, stage: str):
    if stage not in STAGE_IDS:
        return HTMLResponse(f"Unknown stage: {stage}", status_code=404)
    root = get_repo_root()
    ctx = _workspace_ctx(root, slug, stage)
    if ctx is None:
        return _not_found(slug)

    if stage in _STUBS:
        title, text = _STUBS[stage]
        ctx.update({"stub_title": title, "stub_text": text})
        return _templates.TemplateResponse(request, "releases/workspace/stage_stub.html", ctx)

    if stage == "details":
        from mrp.admin.routes.releases import _load_artists
        ctx["artists"] = _load_artists(root)
        return _templates.TemplateResponse(request, "releases/workspace/details.html", ctx)

    if stage == "links":
        release = ctx["release"]
        links = release.get("links") or {}
        na = set((release.get("automation") or {}).get("links_na") or [])
        link_steps = ["odesli", "landr", "apple-music", "youtube"]
        step_labels = {
            "odesli": "Streaming Links (Odesli)",
            "landr": "LANDR Promo Links",
            "apple-music": "Apple Music",
            "youtube": "YouTube",
        }
        ctx.update({
            "links": links,
            "links_na": na,
            "link_steps": [{"id": s, "label": step_labels[s]} for s in link_steps],
            "pipeline_status": {
                s: db.get_latest_job_by_command(f"{slug}/{s}") for s in link_steps
            },
            "critic_settings": {},
        })
        return _templates.TemplateResponse(request, "releases/workspace/links.html", ctx)

    if stage == "tracks":
        ctx["track_rows"] = track_completion(ctx["release"], root)
        return _templates.TemplateResponse(request, "releases/workspace/tracks.html", ctx)

    if stage == "intake":
        path = _release_path(root, slug)
        stat = path.stat()
        from datetime import datetime
        ctx["yaml_path"] = str(path.relative_to(root))
        ctx["yaml_mtime"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        return _templates.TemplateResponse(request, "releases/workspace/intake.html", ctx)

    return HTMLResponse(f"Unknown stage: {stage}", status_code=404)
