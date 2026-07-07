"""Release workspace routes: stage pages, slice saves, track detail, stage jobs."""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mrp.admin import critic_io, db, nim, pipeline as pipe
from mrp.admin import jobs as job_runner
from mrp.admin.deps import get_repo_root
from mrp.admin.workspace import (
    PLATFORM_KEYS,
    STAGES,
    STAGE_IDS,
    STATUSES,
    artist_artifact_moves,
    artist_record_path,
    bool_field,
    effective_master_path,
    migrate_artist_artifacts,
    stage_statuses,
    str_or_none,
    track_completion,
    track_units,
    validate_release_dict,
)
from mrp.core.migrate_site import load_structured_record, serialize_structured_record

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _fromjson(value: str) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


_templates.env.filters["fromjson"] = _fromjson

LINK_STEPS = ["odesli", "promo", "apple-music", "youtube"]
LINK_STEP_LABELS = {
    "odesli": "Streaming Links (Odesli)",
    "promo": "Distributor Promo Links",
    "apple-music": "Apple Music",
    "youtube": "YouTube",
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


def _save_ok(actions: list[str] | None = None) -> HTMLResponse:
    detail = ""
    if actions:
        items = "".join(f"<li><code>{a}</code></li>" for a in actions)
        detail = (f"<ul style='margin:.4rem 0 0 1.25rem;font-size:12px'>{items}</ul>")
    response = HTMLResponse(
        f'<div class="flash flash-ok">Saved successfully.{detail}</div>')
    response.headers["HX-Trigger"] = "releaseSaved"
    return response


def _artist_change_confirm(
    slug: str, old_id: str, new_id: str, moves: list[tuple[Path, Path]]
) -> HTMLResponse:
    """Two-step confirmation for an artist_id change (nothing saved yet)."""
    if moves:
        items = "".join(
            f"<li><code>{src.name}</code> → <code>{dst.name}</code></li>"
            for src, dst in moves)
    else:
        items = "<li>no existing files need renaming</li>"
    return HTMLResponse(
        '<div class="flash flash-warn">'
        f"<p><strong>Change artist &ldquo;{old_id}&rdquo; &rarr; &ldquo;{new_id}&rdquo;?</strong> "
        "Critic records, review files, and preview samples are keyed by artist id. "
        "Confirming will rename these files and update preview URLs:</p>"
        f"<ul style='margin:.4rem 0 .6rem 1.25rem;font-size:12px'>{items}</ul>"
        f'<form hx-post="/releases/{slug}/details" hx-target="#save-result" '
        f'hx-swap="innerHTML" hx-include="#details-form">'
        f'<input type="hidden" name="confirm_artist_change" value="{old_id}">'
        '<button type="submit" class="btn btn-primary">'
        "Yes — change artist and migrate files</button>"
        "</form></div>")


def _validation_errors(request: Request, errors: list[dict]) -> HTMLResponse:
    return _templates.TemplateResponse(
        request, "releases/_validation.html", {"errors": errors}, status_code=422
    )


@router.get("/releases/{slug}/status-badge", response_class=HTMLResponse)
async def status_badge(slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)
    status = ((load_structured_record(path)).get("release") or {}).get("status") or "draft"
    return HTMLResponse(f'<span class="badge badge-{status}">{status}</span>')


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
    old_artist = str(rel.get("artist_id") or "")

    for key in ["title", "artist_id", "status", "release_date", "label", "publisher",
                "distributor", "upc", "catalog_number", "language", "cover_image",
                "summary", "description"]:
        if key in form:
            rel[key] = str_or_none(form[key])
    # Required strings must stay non-null even when submitted blank
    for key in ["title", "artist_id", "cover_image"]:
        if not rel.get(key) and key in form:
            rel[key] = form[key]

    # Copyright block (LANDR-tracked ownership/year fields)
    if any(f"copyright_{k}" in form for k in
           ["composition_owner", "composition_year", "recording_owner", "recording_year"]):
        copyright_ = dict(rel.get("copyright") or {})
        for k in ["composition_owner", "recording_owner"]:
            field = f"copyright_{k}"
            if field in form:
                copyright_[k] = str_or_none(form[field])
        for k in ["composition_year", "recording_year"]:
            field = f"copyright_{k}"
            if field in form:
                raw = str(form[field]).strip()
                try:
                    copyright_[k] = int(raw) if raw else None
                except ValueError:
                    copyright_[k] = None
        rel["copyright"] = copyright_

    seo = dict(rel.get("seo") or {})
    if "seo_title" in form:
        seo["title"] = form["seo_title"] or ""
    if "seo_description" in form:
        seo["description"] = form["seo_description"] or ""
    rel["seo"] = seo

    automation = rel.setdefault("automation", {})
    automation["allow_auto_publish"] = bool_field(form, "allow_auto_publish")

    # Artist change gate: critic records, review files, and samples are all
    # keyed {artist_id}--{slug}, so this needs an explicit confirmation and a
    # migration of the downstream artifacts.
    migration_actions: list[str] = []
    new_artist = str(rel.get("artist_id") or "")
    if old_artist and new_artist != old_artist:
        if artist_record_path(root, new_artist) is None:
            return _validation_errors(request, [{
                "field": "artist_id", "severity": "error",
                "message": f"No artist record found for '{new_artist}'",
            }])
        if str(form.get("confirm_artist_change") or "") != old_artist:
            moves = artist_artifact_moves(root, rel, old_artist, new_artist)
            return _artist_change_confirm(slug, old_artist, new_artist, moves)

    errors = validate_release_dict(data)
    if errors:
        return _validation_errors(request, errors)
    if old_artist and new_artist != old_artist:
        migration_actions = migrate_artist_artifacts(root, rel, old_artist, new_artist)
    path.write_text(serialize_structured_record(path, data))
    return _save_ok(migration_actions)


_HERO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@router.post("/releases/{slug}/hero-image", response_class=HTMLResponse)
async def hero_image_upload(request: Request, slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)

    form = await request.form()
    upload = form.get("hero_file")
    if upload is None or not getattr(upload, "filename", ""):
        return HTMLResponse('<div class="flash flash-error">No file selected.</div>', status_code=400)

    ext = Path(upload.filename).suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in _HERO_EXTENSIONS:
        return HTMLResponse(
            f'<div class="flash flash-error">Unsupported image type: {ext or "(none)"} — use jpg, png, or webp.</div>',
            status_code=400,
        )

    contents = await upload.read()
    if not contents:
        return HTMLResponse('<div class="flash flash-error">Empty file.</div>', status_code=400)

    dest_dir = root / "site" / "public" / "assets" / "releases" / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Remove any previous hero with a different extension so only one remains
    for old_ext in _HERO_EXTENSIONS:
        old = dest_dir / f"hero{old_ext}"
        if old.exists() and old_ext != ext:
            old.unlink()
    dest = dest_dir / f"hero{ext}"
    dest.write_bytes(contents)

    data = load_structured_record(path)
    rel = data.get("release") or {}
    rel["hero_image"] = str(dest.relative_to(root))
    errors = validate_release_dict(data)
    if errors:
        return _validation_errors(request, errors)
    path.write_text(serialize_structured_record(path, data))

    response = HTMLResponse(
        f'<div class="flash flash-ok">Hero image uploaded ({len(contents) // 1024} KB) → <code>{rel["hero_image"]}</code></div>'
    )
    response.headers["HX-Trigger"] = "releaseSaved"
    return response


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


# --- Workspace background jobs -----------------------------------------------

PUB_STEPS = ["validate", "build", "stage", "verify", "approve", "publish", "rollback"]

_PUB_FNS = {
    "validate": pipe.pub_validate,
    "build": pipe.pub_build,
    "stage": pipe.pub_stage,
    "verify": pipe.pub_verify,
    "approve": pipe.pub_approve,
    "publish": pipe.pub_publish,
    "rollback": pipe.pub_rollback,
}


def _critic_kwargs(form: dict) -> dict:
    kwargs = {
        "model": str(form.get("critic_model", "dev")),
        "persona": str(form.get("critic_persona", "default")),
        "target": str(form.get("critic_target", "blurb")),
    }
    tier = form.get("critic_target_tier", "")
    if tier:
        try:
            kwargs["target_tier"] = int(str(tier))
        except ValueError:
            pass
    return kwargs


def _ws_dispatch(step: str, form: dict):
    """Map a workspace job step id to (label, fn, kwargs). None if unknown."""
    if step.startswith("critic-track/"):
        tslug = step.split("/", 1)[1]
        kwargs = _critic_kwargs(form)
        kwargs["track_slug"] = tslug
        return (f"Critic — {tslug}", pipe.run_critic, kwargs)
    if step == "critic-all":
        return ("Critic — all tracks", pipe.run_critic, _critic_kwargs(form))
    if step == "critic-album":
        return ("Album review (pass 2+3)", pipe.run_critic_album, {
            "target": str(form.get("album_target", "album_blurb")),
            "model": str(form.get("critic_model", "default")),
            "persona": str(form.get("critic_persona", "default")),
        })
    if step == "writeback":
        return ("Writeback approved reviews", pipe.run_writeback, {})
    if step.startswith("sampler/"):
        tslug = step.split("/", 1)[1]
        return (f"Sampler — {tslug}", pipe.run_sampler,
                {"track_slug": tslug, "force": True})
    if step.startswith("snip/"):
        tslug = step.split("/", 1)[1]
        try:
            start_s = float(str(form.get("snip_start", "")))
            end_s = float(str(form.get("snip_end", "")))
        except ValueError:
            start_s, end_s = 0.0, 0.0  # run_snip rejects the empty range with a clear message
        return (f"Snippet — {tslug}", pipe.run_snip,
                {"track_slug": tslug, "start_s": start_s, "end_s": end_s})
    if step == "promoter-blurb":
        return ("Promo blurb", pipe.run_promoter,
                {"mode": "blurb", "model": str(form.get("promoter_model", "default"))})
    if step == "promoter-bio":
        return ("Artist bio", pipe.run_promoter,
                {"mode": "bio", "model": str(form.get("promoter_model", "default"))})
    if step == "promoter-kit":
        return ("Promo kit", pipe.run_promo_kit,
                {"model": str(form.get("promoter_model", "default"))})
    if step == "promoter-animated-cover":
        return ("Animated cover", pipe.run_promo_kit_animated_cover, {})
    if step.startswith("pub-"):
        name = step[4:]
        fn = _PUB_FNS.get(name)
        if fn is None:
            return None
        kwargs = {}
        if name in ("stage", "verify"):
            # Both must act on the target chosen in the stage settings picker
            kwargs["target"] = str(form.get("stage_target", "local-staging"))
        return (f"Pipeline — {name}", fn, kwargs)
    return None


def _ws_job_ctx(slug: str, step: str, label: str, job: dict | None) -> dict:
    settings_sel = ""
    if step.startswith("critic-track/"):
        # Per-track settings live next to each row; critic-all has no form and
        # relies on the settings saved on each track (track.critic).
        settings_sel = "#critic-settings-" + step.split("/", 1)[1]
    elif step == "critic-album":
        settings_sel = "#album-settings"
    elif step.startswith("snip/"):
        settings_sel = "#snip-settings-" + step.split("/", 1)[1]
    elif step in ("pub-stage", "pub-verify"):
        settings_sel = "#stage-settings"
    elif step.startswith("promoter-"):
        settings_sel = "#promoter-settings"
    return {
        "slug": slug,
        "step": step,
        "step_label": label,
        "dom_id": "ws-" + step.replace("/", "-").replace(":", "-"),
        "settings_sel": settings_sel,
        "job": job,
    }


@router.post("/releases/{slug}/ws/{step:path}", response_class=HTMLResponse)
async def ws_job_launch(request: Request, slug: str, step: str):
    root = get_repo_root()
    if not _release_path(root, slug).exists():
        return _not_found(slug)
    form = dict(await request.form())
    dispatched = _ws_dispatch(step, form)
    if dispatched is None:
        return HTMLResponse(f"Unknown job step: {step}", status_code=404)
    label, fn, kwargs = dispatched

    job_id = job_runner.launch(f"{slug}/{step}", fn, root, slug, **kwargs)
    job = None
    for _ in range(5):
        job = db.get_job(job_id)
        if job and job["status"] not in ("pending", "running"):
            break
        time.sleep(0.15)
    response = _templates.TemplateResponse(
        request, "releases/workspace/_ws_job.html", _ws_job_ctx(slug, step, label, job)
    )
    if job and job["status"] == "done":
        response.headers["HX-Trigger"] = (
            "releaseSaved, promoterSaved" if step.startswith("promoter-")
            else "releaseSaved")
    return response


@router.get("/releases/{slug}/ws-poll/{job_id}", response_class=HTMLResponse)
async def ws_job_poll(request: Request, slug: str, job_id: str, step: str = ""):
    job = db.get_job(job_id)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    dispatched = _ws_dispatch(step, {})
    label = dispatched[0] if dispatched else step
    response = _templates.TemplateResponse(
        request, "releases/workspace/_ws_job.html", _ws_job_ctx(slug, step, label, job)
    )
    # Completed jobs may have changed release data (status ladder, preview_audio,
    # critic records) — refresh the header badge and stage tabs once. Promoter
    # jobs also refresh the Review & Save panel with the generated text.
    if job["status"] == "done":
        response.headers["HX-Trigger"] = (
            "releaseSaved, promoterSaved" if step.startswith("promoter-")
            else "releaseSaved")
    return response


# --- Critic review edits ------------------------------------------------------

@router.post("/releases/{slug}/critic/review/{track_slug}", response_class=HTMLResponse)
async def critic_review_save(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)
    data = load_structured_record(path)
    artist_id = (data.get("release") or {}).get("artist_id") or ""
    record_id = critic_io.track_record_id(artist_id, track_slug)
    form = dict(await request.form())
    action = form.get("action", "save")
    status = {"approve": "approved", "publishable": "publishable",
              "pending": "pending"}.get(action)
    try:
        critic_io.update_review(
            root, record_id,
            review_text=form.get("review_text"),
            status=status,
        )
    except ValueError as exc:
        return HTMLResponse(f'<div class="flash flash-error">{exc}</div>', status_code=400)
    response = HTMLResponse(
        f'<div class="flash flash-ok">Review saved{" — " + status if status else ""}.</div>'
    )
    response.headers["HX-Refresh"] = "true"
    return response


@router.post("/releases/{slug}/critic/album-review", response_class=HTMLResponse)
async def critic_album_review_save(request: Request, slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)
    data = load_structured_record(path)
    artist_id = (data.get("release") or {}).get("artist_id") or ""
    record_id = critic_io.album_record_id(artist_id, slug)
    form = dict(await request.form())
    action = form.get("action", "save")
    status = {"approve": "approved", "publishable": "publishable",
              "pending": "pending"}.get(action)
    try:
        critic_io.update_review(
            root, record_id,
            review_text=form.get("review_text"),
            status=status,
        )
    except ValueError as exc:
        return HTMLResponse(f'<div class="flash flash-error">{exc}</div>', status_code=400)
    response = HTMLResponse('<div class="flash flash-ok">Album review saved.</div>')
    response.headers["HX-Refresh"] = "true"
    return response


@router.post("/releases/{slug}/critic/context/{track_slug}", response_class=HTMLResponse)
async def critic_context_save(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)
    data = load_structured_record(path)
    artist_id = (data.get("release") or {}).get("artist_id") or ""
    album_id = critic_io.album_record_id(artist_id, slug)
    track_id = critic_io.track_record_id(artist_id, track_slug)
    form = dict(await request.form())
    try:
        critic_io.update_context_review(
            root, album_id, track_id, form.get("review_text") or ""
        )
    except ValueError as exc:
        return HTMLResponse(f'<div class="flash flash-error">{exc}</div>', status_code=400)
    return HTMLResponse('<div class="flash flash-ok">Contextual review saved.</div>')


# --- Promoter save ------------------------------------------------------------

@router.post("/releases/{slug}/promoter/save", response_class=HTMLResponse)
async def promoter_save(request: Request, slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)
    data = load_structured_record(path)
    artist_id = (data.get("release") or {}).get("artist_id") or ""
    artist_path = artist_record_path(root, artist_id)
    if artist_path is None:
        return HTMLResponse(f"Artist <b>{artist_id}</b> not found.", status_code=404)

    artist_data = load_structured_record(artist_path)
    artist = artist_data.get("artist") or {}
    form = dict(await request.form())
    for key in ["promo_blurb", "bio_short", "bio_long"]:
        if key in form:
            artist[key] = str_or_none(form[key])
    if "bio_short" in form or "bio_long" in form:
        artist["bio_auto_generated"] = False  # human-reviewed
    artist_path.write_text(serialize_structured_record(artist_path, artist_data))
    response = HTMLResponse(
        '<div class="flash flash-ok">Artist profile saved (marked human-reviewed).</div>')
    # promoterSaved refreshes the Review & Save panel; releaseSaved the tabs/badge
    response.headers["HX-Trigger"] = "releaseSaved, promoterSaved"
    return response


@router.get("/releases/{slug}/promoter/profile", response_class=HTMLResponse)
async def promoter_profile(request: Request, slug: str):
    """Review & Save panel fragment — re-fetched after promoter jobs and saves."""
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)
    release = (load_structured_record(path)).get("release") or {}
    artist_path = artist_record_path(root, release.get("artist_id") or "")
    artist = {}
    if artist_path is not None:
        artist = load_structured_record(artist_path).get("artist") or {}
    return _templates.TemplateResponse(
        request, "releases/workspace/_promoter_profile.html",
        {"slug": slug, "artist": artist})


@router.get("/releases/{slug}/promoter/kit", response_class=HTMLResponse)
async def promoter_kit(request: Request, slug: str):
    """Promo kit panel fragment — re-fetched after promoter jobs complete."""
    root = get_repo_root()
    kit_path = root / "assets" / "processed" / "promo" / slug / "kit.json"
    kit = None
    if kit_path.exists():
        try:
            kit = json.loads(kit_path.read_text())
        except ValueError:
            kit = None
    return _templates.TemplateResponse(
        request, "releases/workspace/_promo_kit.html",
        {"slug": slug, "kit": kit, "base": f"/processed/promo/{slug}"})


# --- Master audio (streamed to the sampler stage player) ---------------------

_MASTER_MEDIA_TYPES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
    ".aif": "audio/aiff", ".aiff": "audio/aiff", ".m4a": "audio/mp4",
}


@router.get("/releases/{slug}/master-audio/{track_slug}")
async def master_audio(slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.exists():
        return _not_found(slug)
    release = (load_structured_record(path)).get("release") or {}
    unit = next((u for u in track_units(release) if u["slug"] == track_slug), None)
    if unit is None:
        return HTMLResponse(f"Track <b>{track_slug}</b> not found.", status_code=404)
    master = effective_master_path(release, unit["index"], unit["track"])
    if not master or not Path(master).is_file():
        return HTMLResponse(f"Master not found: {master}", status_code=404)
    media_type = _MASTER_MEDIA_TYPES.get(Path(master).suffix.lower(), "application/octet-stream")
    return FileResponse(master, media_type=media_type)


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
    ctx.update({
        "unit": unit,
        "track": unit["track"],
        "track_slug": track_slug,
        "master_fallback": effective_master_path(release, unit["index"], unit["track"]),
        "ws_ctx": _ws_job_ctx,
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

    if "track_hints" in form:
        hints: dict[str, str] = {}
        for line in str(form["track_hints"]).splitlines():
            if ":" not in line:
                continue
            name, _, value = line.partition(":")
            if name.strip() and value.strip():
                hints[name.strip()] = value.strip()
        if hints:
            track["hints"] = hints
        else:
            track.pop("hints", None)

    if any(f"track_credits_{k}" in form for k in
           ["primary_artist", "songwriter", "lyrics", "producer", "mastering"]):
        credits = dict(track.get("credits") or {})
        for k in ["primary_artist", "songwriter", "lyrics", "producer", "mastering"]:
            field = f"track_credits_{k}"
            if field in form:
                credits[k] = str_or_none(form[field])
        track["credits"] = credits

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

    if stage == "critic":
        return _critic_stage(request, root, slug, ctx)
    if stage == "sampler":
        return _sampler_stage(request, root, slug, ctx)
    if stage == "promoter":
        return _promoter_stage(request, root, slug, ctx)
    if stage == "publish":
        return _publish_stage(request, root, slug, ctx)
    if stage == "monitoring":
        return _monitoring_stage(request, root, slug, ctx)

    if stage == "details":
        from mrp.admin.routes.releases import _load_artists
        ctx["artists"] = _load_artists(root)
        return _templates.TemplateResponse(request, "releases/workspace/details.html", ctx)

    if stage == "links":
        release = ctx["release"]
        links = release.get("links") or {}
        na = set((release.get("automation") or {}).get("links_na") or [])
        ctx.update({
            "links": links,
            "links_na": na,
            "link_steps": [{"id": s, "label": LINK_STEP_LABELS[s]} for s in LINK_STEPS],
            "pipeline_status": {
                s: db.get_latest_job_by_command(f"{slug}/{s}") for s in LINK_STEPS
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


# --- Stage builders -----------------------------------------------------------

def _critic_stage(request: Request, root: Path, slug: str, ctx: dict) -> HTMLResponse:
    release = ctx["release"]
    artist_id = release.get("artist_id") or ""
    selected = request.query_params.get("track") or ""

    units = []
    for u in track_units(release):
        record_id = critic_io.track_record_id(artist_id, u["slug"])
        record = critic_io.load_record(root, record_id)
        units.append({
            **u,
            "record_id": record_id,
            "summary": critic_io.review_summary(record),
            "job": db.get_latest_job_by_command(f"{slug}/critic-track/{u['slug']}"),
        })

    editor = None
    if selected:
        unit = next((u for u in units if u["slug"] == selected), None)
        if unit and unit["summary"]["exists"]:
            editor = unit

    album = None
    if release.get("model") == "album":
        album_id = critic_io.album_record_id(artist_id, slug)
        record = critic_io.load_record(root, album_id)
        tics = []
        for tic in (record or {}).get("track_reviews_in_context") or []:
            tid = tic.get("track_id") or ""
            tics.append({
                **tic,
                "tslug": tid.split("--", 1)[-1],
            })
        album = {
            "record_id": album_id,
            "summary": critic_io.review_summary(record),
            "record": record,
            "tics": tics,
            "job": db.get_latest_job_by_command(f"{slug}/critic-album"),
        }

    approved = sum(1 for u in units if u["summary"]["status"] in ("approved", "publishable"))
    if album and album["summary"]["status"] in ("approved", "publishable"):
        approved += 1

    ctx.update({
        "units": units,
        "editor": editor,
        "album": album,
        "approved_count": approved,
        "record_total": len(units) + (1 if album else 0),
        "writeback_job": db.get_latest_job_by_command(f"{slug}/writeback"),
        "critic_all_job": db.get_latest_job_by_command(f"{slug}/critic-all"),
        "ws_ctx": _ws_job_ctx,
    })
    return _templates.TemplateResponse(request, "releases/workspace/critic.html", ctx)


def _sampler_stage(request: Request, root: Path, slug: str, ctx: dict) -> HTMLResponse:
    release = ctx["release"]
    artist_id = release.get("artist_id") or ""
    critic_out = root / "app" / "critic" / "out"

    units = []
    for u in track_units(release):
        t = u["track"]
        master = effective_master_path(release, u["index"], t)
        units.append({
            **u,
            "master_path": master,
            "master_exists": bool(master) and Path(master).is_file(),
            "has_critic_record": (critic_out / f"{artist_id}--{u['slug']}.json").is_file(),
            "preview_audio": t.get("preview_audio"),
            "snip_job": db.get_latest_job_by_command(f"{slug}/snip/{u['slug']}"),
            "auto_job": db.get_latest_job_by_command(f"{slug}/sampler/{u['slug']}"),
        })

    ctx.update({"units": units, "ws_ctx": _ws_job_ctx})
    return _templates.TemplateResponse(request, "releases/workspace/sampler.html", ctx)


def _promoter_stage(request: Request, root: Path, slug: str, ctx: dict) -> HTMLResponse:
    release = ctx["release"]
    artist_id = release.get("artist_id") or ""
    artist_path = artist_record_path(root, artist_id)
    artist = {}
    if artist_path is not None:
        artist = (load_structured_record(artist_path)).get("artist") or {}
    ctx.update({
        "artist": artist,
        "artist_id": artist_id,
        "blurb_job": db.get_latest_job_by_command(f"{slug}/promoter-blurb"),
        "bio_job": db.get_latest_job_by_command(f"{slug}/promoter-bio"),
        "kit_job": db.get_latest_job_by_command(f"{slug}/promoter-kit"),
        "animated_job": db.get_latest_job_by_command(f"{slug}/promoter-animated-cover"),
        "nim_connected": nim.connected(),
        "ws_ctx": _ws_job_ctx,
    })
    return _templates.TemplateResponse(request, "releases/workspace/promoter.html", ctx)


def _publish_stage(request: Request, root: Path, slug: str, ctx: dict) -> HTMLResponse:
    from mrp.core.deploy import load_targets
    from mrp.core.status import status as core_status

    st = core_status(root, release=slug)
    latest = st.get("latest") or {}

    # Rollback reports are repo-wide (core doesn't scope them to a release).
    # Only show one that postdates this release's latest publish — an older
    # rollback is history from a previous publish cycle, not this one.
    rollback = latest.get("rollback")
    pub_report = latest.get("publish")
    if rollback and (not pub_report or (rollback.get("generated_at") or "")
                     <= (pub_report.get("generated_at") or "")):
        latest = {**latest, "rollback": None}

    # Recommended next step: first link in the chain missing or failed
    chain = [
        ("validate", "validation"),
        ("build", "build"),
        ("stage", "staging_deployment"),
        ("verify", "verification"),
        ("approve", "approval"),
        ("publish", "publish"),
    ]
    recommended = None
    if (ctx["release"].get("status") or "") != "live":
        for step_name, report_key in chain:
            report = latest.get(report_key)
            if not report or report.get("status") in ("failed", None):
                recommended = step_name
                break
        else:
            recommended = "publish"

    targets, target_errors = load_targets(root)
    jobs = {s: db.get_latest_job_by_command(f"{slug}/pub-{s}") for s in PUB_STEPS}
    ctx.update({
        "core_status": st,
        "latest_reports": latest,
        "recommended": recommended,
        "targets": sorted(targets.keys()),
        "target_errors": target_errors,
        "pub_steps": PUB_STEPS,
        "pub_jobs": jobs,
        "rollback_available": st.get("rollback_available"),
        "ws_ctx": _ws_job_ctx,
    })
    return _templates.TemplateResponse(request, "releases/workspace/publish.html", ctx)


def _monitoring_stage(request: Request, root: Path, slug: str, ctx: dict) -> HTMLResponse:
    release = ctx["release"]
    links = release.get("links") or {}
    na = set((release.get("automation") or {}).get("links_na") or [])
    missing = [k for k in PLATFORM_KEYS if not links.get(k) and k not in na]
    ctx.update({
        "links": links,
        "links_na": sorted(na),
        "missing": missing,
        "link_steps": [{"id": s, "label": LINK_STEP_LABELS[s]} for s in LINK_STEPS],
        "pipeline_status": {
            s: db.get_latest_job_by_command(f"{slug}/{s}") for s in LINK_STEPS
        },
        "critic_settings": {},
    })
    return _templates.TemplateResponse(request, "releases/workspace/monitoring.html", ctx)
