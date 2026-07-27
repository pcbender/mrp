"""Optional per-track music-video workspace and process-job routes."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from mrp.admin import db, video_jobs
from mrp.admin.deps import get_repo_root
from mrp.admin.video_casting import (
    CastingEditorError,
    load_casting,
    previews_path,
    save_casting,
    save_track_actor,
)
from mrp.admin.video_rendering import (
    VideoRenderingError,
    approve_render,
    discard_draft,
    load_rendering,
    render_launch_problems,
    renders_path,
)
from mrp.admin.video_live_preview import (
    LivePreviewError,
    build_live_preview_document,
)
from mrp.admin.video_publication import (
    VideoPublicationError,
    apply_publication,
    load_publication,
    plan_publication,
    public_media_available,
    record_opt_in,
)
from mrp.admin.video_timing import (
    TimingEditorError,
    add_section,
    fill_gaps,
    load_timing,
    persist_timing,
    validate_timing,
)
from mrp.admin.video_workspace import (
    STEM_ROLES,
    StemImportError,
    resolve_asset,
    scan_stem_directory,
    track_key,
    validate_assets,
    video_track_rows,
)
from mrp.admin.workspace import (
    STAGES,
    STATUSES,
    effective_master_path,
    stage_statuses,
    track_units,
    validate_release_dict,
)
from mrp.core.migrate_site import load_structured_record, serialize_structured_record

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
_STEM_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_AUDIO_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".m4a": "audio/mp4",
}


def _release_path(root: Path, slug: str) -> Path:
    return root / "content" / "releases" / f"{slug}.yaml"


def _context(root: Path, slug: str) -> dict | None:
    path = _release_path(root, slug)
    if not path.is_file():
        return None
    release = load_structured_record(path).get("release") or {}
    return {
        "slug": slug,
        "release": release,
        "stages": STAGES,
        "stage_status": stage_statuses(root, slug, release),
        "active_stage": "video",
        "statuses": STATUSES,
    }


def _unit(release: dict, track_slug: str) -> dict | None:
    return next((item for item in track_units(release) if item["slug"] == track_slug), None)


def _not_found(value: str) -> HTMLResponse:
    return HTMLResponse(f"Music-video track <b>{value}</b> not found.", status_code=404)


def _touch_video_preflight(root: Path, release: dict, track: dict) -> None:
    preflight = (
        root
        / "assets"
        / "processed"
        / "video"
        / track_key(release, track)
        / "logs"
        / "preflight.json"
    )
    if preflight.is_file():
        preflight.touch()


def _job_template(
    request: Request,
    job: dict | None,
    *,
    slug: str = "",
    track_slug: str = "",
    kind: str = "",
    error: str | None = None,
) -> HTMLResponse:
    preview_time = None
    draft_start = None
    draft_end = None
    if job and job.get("kind") == "frame":
        marker, separator, value = str(job.get("command") or "").rpartition("@")
        if separator and marker:
            preview_time = value
    if job and job.get("kind") == "draft":
        marker, separator, value = str(job.get("command") or "").rpartition("@")
        if separator and marker and ":" in value:
            draft_start, draft_end = value.split(":", 1)
    return _templates.TemplateResponse(
        request,
        "releases/workspace/_video_job.html",
        {
            "job": job,
            "job_error": error,
            "slug": slug,
            "track_slug": track_slug,
            "kind": kind,
            "preview_time": preview_time,
            "draft_start": draft_start,
            "draft_end": draft_end,
        },
        status_code=409 if error else 200,
    )


def video_stage(request: Request, root: Path, slug: str, ctx: dict) -> HTMLResponse:
    ctx["video_rows"] = video_track_rows(root, slug, ctx["release"])
    return _templates.TemplateResponse(request, "releases/workspace/video.html", ctx)


@router.get("/releases/{slug}/tracks/{track_slug}/video", response_class=HTMLResponse)
async def video_track(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    key = track_key(ctx["release"], unit["track"])
    ctx.update(
        {
            "unit": unit,
            "track": unit["track"],
            "track_slug": track_slug,
            "track_key": key,
            "master_fallback": effective_master_path(
                ctx["release"], unit["index"], unit["track"]
            ),
            "stem_roles": STEM_ROLES,
            "asset_report": validate_assets(root, ctx["release"], unit),
            "video_jobs": {
                kind: db.get_latest_video_job(key, kind)
                for kind in ("prepare", "analyze", "align", "render")
            },
        }
    )
    return _templates.TemplateResponse(request, "releases/workspace/video_track.html", ctx)


@router.get(
    "/releases/{slug}/tracks/{track_slug}/video/timing",
    response_class=HTMLResponse,
)
async def video_timing(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    key = track_key(ctx["release"], unit["track"])
    timing_error = None
    try:
        timing = load_timing(root, ctx["release"], unit["track"])
    except TimingEditorError as exc:
        timing = None
        timing_error = list(exc.problems)
    master = resolve_asset(root, unit["track"].get("master_path"))
    ctx.update(
        {
            "unit": unit,
            "track": unit["track"],
            "track_slug": track_slug,
            "track_key": key,
            "timing": timing,
            "timing_error": timing_error,
            "audio_available": bool(master and master.is_file()),
            "align_job": db.get_latest_video_job(key, "align"),
        }
    )
    return _templates.TemplateResponse(request, "releases/workspace/video_timing.html", ctx)


@router.get("/releases/{slug}/tracks/{track_slug}/video/audio")
async def video_audio(slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    master = resolve_asset(root, unit["track"].get("master_path"))
    if master is None or not master.is_file():
        return HTMLResponse("Track master is not available.", status_code=404)
    media_type = _AUDIO_MEDIA_TYPES.get(
        master.suffix.casefold(), "application/octet-stream"
    )
    return FileResponse(master, media_type=media_type)


def _etag_matches(header: object, etag: str) -> bool:
    """Whether an If-None-Match header covers this entity tag.

    Accepts any object so a direct call that never went through FastAPI's
    header binding is simply treated as sending no validator.
    """
    if not isinstance(header, str) or not header:
        return False
    for candidate in header.split(","):
        value = candidate.strip()
        if value == "*":
            return True
        if value.startswith("W/"):
            value = value[2:]
        if value.strip('"') == etag:
            return True
    return False


@router.get(
    "/releases/{slug}/tracks/{track_slug}/video/live-preview",
    response_class=HTMLResponse,
)
async def video_live_preview(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    key = track_key(ctx["release"], unit["track"])
    master = resolve_asset(root, unit["track"].get("master_path"))
    ctx.update(
        {
            "unit": unit,
            "track": unit["track"],
            "track_slug": track_slug,
            "track_key": key,
            "audio_available": bool(master and master.is_file()),
            "frame_job": db.get_latest_video_job(key, "frame"),
        }
    )
    return _templates.TemplateResponse(
        request,
        "releases/workspace/video_live_preview.html",
        ctx,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get(
    "/releases/{slug}/tracks/{track_slug}/video/live-preview/data",
    response_class=Response,
)
async def video_live_preview_data(
    slug: str,
    track_slug: str,
    if_none_match: str | None = Header(default=None),
):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return JSONResponse(
            {
                "error": {
                    "code": "release_not_found",
                    "message": f"Release not found: {slug}",
                }
            },
            status_code=404,
        )
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return JSONResponse(
            {
                "error": {
                    "code": "track_not_found",
                    "message": f"Track not found: {track_slug}",
                }
            },
            status_code=404,
        )
    try:
        document = build_live_preview_document(
            root,
            slug,
            ctx["release"],
            track_slug,
            unit["track"],
        )
    except LivePreviewError as exc:
        return JSONResponse(exc.payload(), status_code=exc.status_code)
    headers = {
        "Cache-Control": "private, no-store",
        "ETag": f'"{document.etag}"',
        "X-Content-Type-Options": "nosniff",
    }
    # The browser re-checks this resource whenever the tab regains focus, so a
    # matching validator answers with no body at all.
    if _etag_matches(if_none_match, document.etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=document.body,
        media_type="application/json",
        headers=headers,
    )


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/timing",
    response_class=HTMLResponse,
)
async def video_timing_save(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.is_file():
        return _not_found(track_slug)
    data = load_structured_record(path)
    release = data.get("release") or {}
    unit = _unit(release, track_slug)
    if unit is None:
        return _not_found(track_slug)
    form = await request.form()
    field_names = (
        "section_id",
        "section_start",
        "section_end",
        "section_reviewed",
        "line_key",
        "line_start",
        "line_end",
        "line_reviewed",
    )
    fields = {name: form.getlist(name) for name in field_names}
    try:
        result = validate_timing(root, release, unit["track"], fields)
    except TimingEditorError as exc:
        errors = [
            {"field": "timing", "message": problem, "severity": "error"}
            for problem in exc.problems
        ]
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {"errors": errors},
            status_code=422,
        )

    video = dict(unit["track"].get("music_video") or {})
    video.setdefault(
        "project",
        f"assets/source/video/{track_key(release, unit['track'])}/project.yaml",
    )
    current_status = str(video.get("status") or "draft")
    if current_status in {"draft", "timed"}:
        video["status"] = (
            "timed" if result["summary"]["review_complete"] else "draft"
        )
    unit["track"]["music_video"] = video
    errors = validate_release_dict(data)
    if errors:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {"errors": errors},
            status_code=422,
        )
    persist_timing(root, release, unit["track"], result["document"])
    path.write_text(serialize_structured_record(path, data), encoding="utf-8")
    response = HTMLResponse(
        '<div class="flash flash-ok">Timing and review state saved.</div>'
    )
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/timing"
    )
    return response


def _timing_errors(request: Request, exc: TimingEditorError) -> HTMLResponse:
    errors = [
        {"field": "timing", "message": problem, "severity": "error"}
        for problem in exc.problems
    ]
    return _templates.TemplateResponse(
        request, "releases/_validation.html", {"errors": errors}, status_code=422
    )


def _timing_redirect(
    request: Request, slug: str, track_slug: str, message: str
) -> HTMLResponse:
    response = HTMLResponse(f'<div class="flash flash-ok">{message}</div>')
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/timing"
    )
    return response


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/timing/fill-gaps",
    response_class=HTMLResponse,
)
async def video_timing_fill_gaps(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    try:
        result = fill_gaps(root, ctx["release"], unit["track"])
    except TimingEditorError as exc:
        return _timing_errors(request, exc)
    if result["filled"] == 0:
        message = "No gaps to fill — the timeline is already contiguous."
    else:
        plural = "" if result["filled"] == 1 else "s"
        message = f"Filled {result['filled']} gap{plural}."
    return _timing_redirect(request, slug, track_slug, message)


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/timing/section",
    response_class=HTMLResponse,
)
async def video_timing_add_section(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    form = await request.form()
    try:
        result = add_section(
            root,
            ctx["release"],
            unit["track"],
            section_type=str(form.get("section_type") or ""),
            start=str(form.get("section_start") or ""),
            end=str(form.get("section_end") or ""),
            label=str(form.get("section_label") or "") or None,
        )
    except TimingEditorError as exc:
        return _timing_errors(request, exc)
    return _timing_redirect(
        request, slug, track_slug, f"Added scene {result['section_id']}."
    )


@router.get(
    "/releases/{slug}/tracks/{track_slug}/video/casting",
    response_class=HTMLResponse,
)
async def video_casting(
    request: Request,
    slug: str,
    track_slug: str,
    section: str | None = None,
    scope: str = "type",
    actor: str | None = None,
):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    key = track_key(ctx["release"], unit["track"])
    casting_error = None
    try:
        casting = load_casting(
            root,
            ctx["release"],
            unit["track"],
            section_id=section,
            scope=scope,
            actor_id=actor,
        )
    except CastingEditorError as exc:
        casting = None
        casting_error = list(exc.problems)
    status = str((unit["track"].get("music_video") or {}).get("status") or "draft")
    master = resolve_asset(root, unit["track"].get("master_path"))
    ctx.update(
        {
            "unit": unit,
            "track": unit["track"],
            "track_slug": track_slug,
            "track_key": key,
            "casting": casting,
            "casting_error": casting_error,
            "cast_status_ok": status in {"timed", "cast", "previewed", "rendered"},
            "audio_available": bool(master and master.is_file()),
            "frame_job": db.get_latest_video_job(key, "frame"),
            "contact_job": db.get_latest_video_job(key, "contact"),
        }
    )
    return _templates.TemplateResponse(request, "releases/workspace/video_casting.html", ctx)


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/actors",
    response_class=HTMLResponse,
)
async def video_actor_save(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.is_file():
        return _not_found(track_slug)
    data = load_structured_record(path)
    release = data.get("release") or {}
    unit = _unit(release, track_slug)
    if unit is None:
        return _not_found(track_slug)
    form = await request.form()
    fields = {str(name): form.getlist(name) for name in form.keys()}
    try:
        actor_id = save_track_actor(root, release, unit["track"], fields)
    except CastingEditorError as exc:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {"field": "actor", "message": problem, "severity": "error"}
                    for problem in exc.problems
                ]
            },
            status_code=422,
        )
    section = str(form.get("return_section") or "")
    scope = str(form.get("return_scope") or "type")
    query = f"?scope={scope}"
    if section:
        query += f"&section={section}"
    if actor_id:
        query += f"&actor={actor_id}"
    response = HTMLResponse('<div class="flash flash-ok">Track actor saved.</div>')
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/casting{query}"
        "#track-actor-designer"
    )
    return response


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/actors/title-generate",
    response_class=HTMLResponse,
)
async def video_title_generate(request: Request, slug: str, track_slug: str):
    from mrp.admin import actor_gen
    from mrp.admin import jobs as job_runner

    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.is_file():
        return _not_found(track_slug)
    release = load_structured_record(path).get("release") or {}
    if _unit(release, track_slug) is None:
        return _not_found(track_slug)
    job_id = job_runner.launch(
        f"actor-title/{slug}/{track_slug}",
        actor_gen.generate_title_actor,
        root,
        slug,
        track_slug,
        only_if_missing=False,
    )
    return _templates.TemplateResponse(
        request, "jobs/_result.html", {"job": db.get_job(job_id)}
    )


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/casting",
    response_class=HTMLResponse,
)
async def video_casting_save(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.is_file():
        return _not_found(track_slug)
    data = load_structured_record(path)
    release = data.get("release") or {}
    unit = _unit(release, track_slug)
    if unit is None:
        return _not_found(track_slug)
    current_status = str(
        (unit["track"].get("music_video") or {}).get("status") or "draft"
    )
    if current_status not in {"timed", "cast", "previewed", "rendered"}:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {
                        "field": "casting",
                        "message": "Finish and review section timing before saving a cast.",
                        "severity": "error",
                    }
                ]
            },
            status_code=409,
        )
    form = await request.form()
    fields = {str(name): form.getlist(name) for name in form.keys()}
    try:
        result = save_casting(root, release, unit["track"], fields)
    except CastingEditorError as exc:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {"field": "casting", "message": problem, "severity": "error"}
                    for problem in exc.problems
                ]
            },
            status_code=422,
        )
    video = dict(unit["track"].get("music_video") or {})
    video.setdefault(
        "project",
        f"assets/source/video/{track_key(release, unit['track'])}/project.yaml",
    )
    video["status"] = "cast"
    unit["track"]["music_video"] = video
    errors = validate_release_dict(data)
    if errors:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {"errors": errors},
            status_code=422,
        )
    path.write_text(serialize_structured_record(path, data), encoding="utf-8")
    selected = result["selected_section"]
    response = HTMLResponse('<div class="flash flash-ok">Section cast saved.</div>')
    # HX-Redirect is a full page load, so without the anchor the editor reopens
    # at the top of the page and the scene the user was working on scrolls away.
    # The selected actor rides along for the same reason.
    actor = str(form.get("return_actor") or "")
    query = f"?section={selected.id}&scope={result['scope']}"
    if actor:
        query += f"&actor={actor}"
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/casting{query}#scene-casting"
    )
    return response


@router.get(
    "/releases/{slug}/tracks/{track_slug}/video/previews/{name}",
)
async def video_preview_image(slug: str, track_slug: str, name: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    if Path(name).name != name or Path(name).suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
        return HTMLResponse("Preview image not found.", status_code=404)
    path = previews_path(root, ctx["release"], unit["track"]) / name
    if not path.is_file():
        return HTMLResponse("Preview image not found.", status_code=404)
    media_type = "image/png" if path.suffix.casefold() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media_type)


@router.get(
    "/releases/{slug}/tracks/{track_slug}/video/rendering",
    response_class=HTMLResponse,
)
async def video_rendering(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    key = track_key(ctx["release"], unit["track"])
    plan_job = db.get_latest_video_job(key, "render_plan")
    rendering_error = None
    try:
        rendering = load_rendering(
            root,
            ctx["release"],
            unit["track"],
            plan_job=plan_job,
        )
    except VideoRenderingError as exc:
        rendering = None
        rendering_error = list(exc.problems)
    ctx.update(
        {
            "unit": unit,
            "track": unit["track"],
            "track_slug": track_slug,
            "track_key": key,
            "rendering": rendering,
            "rendering_error": rendering_error,
            "draft_job": db.get_latest_video_job(key, "draft"),
            "plan_job": plan_job,
            "render_job": db.get_latest_video_job(key, "render"),
            "publication": load_publication(root, ctx["release"], unit["track"]),
        }
    )
    return _templates.TemplateResponse(request, "releases/workspace/video_rendering.html", ctx)


@router.get(
    "/releases/{slug}/tracks/{track_slug}/video/renders/{group}/{name}",
)
async def video_render_file(slug: str, track_slug: str, group: str, name: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    if (
        group not in {"drafts", "full"}
        or Path(name).name != name
        or Path(name).suffix.casefold() != ".mp4"
    ):
        return HTMLResponse("Rendered video not found.", status_code=404)
    path = renders_path(root, ctx["release"], unit["track"]) / group / name
    if not path.is_file():
        return HTMLResponse("Rendered video not found.", status_code=404)
    return FileResponse(path, media_type="video/mp4")


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/rendering/drafts/{draft_id}/discard",
    response_class=HTMLResponse,
)
async def video_draft_discard(
    request: Request,
    slug: str,
    track_slug: str,
    draft_id: str,
):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    try:
        discard_draft(root, ctx["release"], unit["track"], draft_id)
    except VideoRenderingError as exc:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {"field": "draft", "message": problem, "severity": "error"}
                    for problem in exc.problems
                ]
            },
            status_code=422,
        )
    response = HTMLResponse('<div class="flash flash-ok">Draft discarded.</div>')
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/rendering"
    )
    return response


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/rendering/approve",
    response_class=HTMLResponse,
)
async def video_render_approve(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.is_file():
        return _not_found(track_slug)
    data = load_structured_record(path)
    release = data.get("release") or {}
    unit = _unit(release, track_slug)
    if unit is None:
        return _not_found(track_slug)
    form = await request.form()
    artifact_path = str(form.get("artifact_path") or "")
    video = dict(unit["track"].get("music_video") or {})
    video["status"] = "approved"
    unit["track"]["music_video"] = video
    errors = validate_release_dict(data)
    if errors:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {"errors": errors},
            status_code=422,
        )
    try:
        approve_render(root, release, unit["track"], artifact_path)
    except VideoRenderingError as exc:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {"field": "approval", "message": problem, "severity": "error"}
                    for problem in exc.problems
                ]
            },
            status_code=409,
        )
    path.write_text(serialize_structured_record(path, data), encoding="utf-8")
    _touch_video_preflight(root, release, unit["track"])
    response = HTMLResponse('<div class="flash flash-ok">Full render approved.</div>')
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/rendering"
    )
    return response


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/rendering/publish",
    response_class=HTMLResponse,
)
async def video_render_publish(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.is_file():
        return _not_found(track_slug)
    data = load_structured_record(path)
    release = data.get("release") or {}
    unit = _unit(release, track_slug)
    if unit is None:
        return _not_found(track_slug)
    form = await request.form()
    if str(form.get("opt_in") or "").casefold() not in {"1", "true", "on", "yes"}:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {
                        "field": "music_video.opt_in",
                        "message": "Check Opt In before publishing this video publicly.",
                        "severity": "error",
                    }
                ]
            },
            status_code=422,
        )
    try:
        plan = plan_publication(root, release, unit["track"])
    except VideoPublicationError as exc:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {"field": "publication", "message": problem, "severity": "error"}
                    for problem in exc.problems
                ]
            },
            status_code=409,
        )
    video = dict(unit["track"].get("music_video") or {})
    video.update(
        {
            "status": "published",
            "opt_in": True,
            "public_url": plan.public_url,
            "poster": plan.poster_url,
        }
    )
    unit["track"]["music_video"] = video
    errors = validate_release_dict(data)
    if errors:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {"errors": errors},
            status_code=422,
        )
    try:
        apply_publication(plan)
    except VideoPublicationError as exc:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {"field": "publication", "message": problem, "severity": "error"}
                    for problem in exc.problems
                ]
            },
            status_code=409,
        )
    path.write_text(serialize_structured_record(path, data), encoding="utf-8")
    _touch_video_preflight(root, release, unit["track"])
    response = HTMLResponse(
        '<div class="flash flash-ok">Approved video published with public display opted in.</div>'
    )
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/rendering"
    )
    return response


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/rendering/visibility",
    response_class=HTMLResponse,
)
async def video_render_visibility(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.is_file():
        return _not_found(track_slug)
    data = load_structured_record(path)
    release = data.get("release") or {}
    unit = _unit(release, track_slug)
    if unit is None:
        return _not_found(track_slug)
    video = unit["track"].get("music_video")
    if not isinstance(video, dict) or video.get("status") != "published":
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {
                        "field": "music_video.status",
                        "message": "Publish an approved video before changing its public Opt In.",
                        "severity": "error",
                    }
                ]
            },
            status_code=409,
        )
    form = await request.form()
    opt_in = str(form.get("opt_in") or "").casefold() in {"1", "true", "on", "yes"}
    if opt_in and not public_media_available(root, unit["track"]):
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {
                "errors": [
                    {
                        "field": "music_video.opt_in",
                        "message": "Durable public video or poster is missing; republish before opting in.",
                        "severity": "error",
                    }
                ]
            },
            status_code=409,
        )
    video = dict(video)
    video["opt_in"] = opt_in
    unit["track"]["music_video"] = video
    errors = validate_release_dict(data)
    if errors:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {"errors": errors},
            status_code=422,
        )
    path.write_text(serialize_structured_record(path, data), encoding="utf-8")
    record_opt_in(root, release, unit["track"], opt_in)
    _touch_video_preflight(root, release, unit["track"])
    state = "opted in" if opt_in else "opted out"
    response = HTMLResponse(
        f'<div class="flash flash-ok">Public video display {state}.</div>'
    )
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/rendering"
    )
    return response


@router.post("/releases/{slug}/tracks/{track_slug}/video/stems/import")
async def video_stems_import(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return JSONResponse({"detail": f"Release not found: {slug}"}, status_code=404)
    if _unit(ctx["release"], track_slug) is None:
        return JSONResponse({"detail": f"Track not found: {track_slug}"}, status_code=404)
    form = await request.form()
    try:
        stems = scan_stem_directory(root, form.get("stem_directory"))
    except (OSError, StemImportError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=422)
    return JSONResponse({"count": len(stems), "stems": stems})


@router.post(
    "/releases/{slug}/tracks/{track_slug}/video/assets",
    response_class=HTMLResponse,
)
async def video_assets_save(request: Request, slug: str, track_slug: str):
    root = get_repo_root()
    path = _release_path(root, slug)
    if not path.is_file():
        return _not_found(track_slug)
    data = load_structured_record(path)
    release = data.get("release") or {}
    unit = _unit(release, track_slug)
    if unit is None:
        return _not_found(track_slug)
    form = await request.form()
    track = unit["track"]
    if "master_path" in form:
        master = str(form.get("master_path") or "").strip()
        track["master_path"] = master or None

    ids = form.getlist("stem_id")
    labels = form.getlist("stem_label")
    roles = form.getlist("stem_role")
    paths = form.getlist("stem_path")
    enabled = form.getlist("stem_enabled")
    stems: list[dict] = []
    form_errors: list[dict] = []
    seen: set[str] = set()
    track_prefix = (
        "release.song"
        if release.get("model") == "song"
        else f"release.tracks.{unit['index']}"
    )
    for index, (stem_id, label, role, stem_path, is_enabled) in enumerate(
        zip(ids, labels, roles, paths, enabled)
    ):
        stem_id = str(stem_id).strip()
        label = str(label).strip()
        role = str(role).strip()
        stem_path = str(stem_path).strip()
        if not any((stem_id, label, stem_path)):
            continue
        field = f"{track_prefix}.stems.{index}"
        if not _STEM_ID.fullmatch(stem_id):
            form_errors.append({"field": f"{field}.id", "message": "Use a lowercase slug-like stem id.", "severity": "error"})
        elif stem_id in seen:
            form_errors.append({"field": f"{field}.id", "message": f"Duplicate stem id: {stem_id}", "severity": "error"})
        seen.add(stem_id)
        if role not in STEM_ROLES:
            form_errors.append({"field": f"{field}.role", "message": f"Unsupported stem role: {role}", "severity": "error"})
        if not stem_path:
            form_errors.append({"field": f"{field}.path", "message": "Stem path is required.", "severity": "error"})
        stem = {
            "id": stem_id,
            "role": role,
            "path": stem_path,
            "enabled": str(is_enabled) == "true",
        }
        if label:
            stem["label"] = label
        stems.append(stem)
    if stems:
        track["stems"] = stems
    else:
        track.pop("stems", None)

    errors = [*form_errors, *validate_release_dict(data)]
    if errors:
        return _templates.TemplateResponse(
            request,
            "releases/_validation.html",
            {"errors": errors},
            status_code=422,
        )
    path.write_text(serialize_structured_record(path, data), encoding="utf-8")
    response = HTMLResponse('<div class="flash flash-ok">Video assets saved.</div>')
    response.headers["HX-Redirect"] = f"/releases/{slug}/tracks/{track_slug}/video"
    return response


@router.post("/releases/{slug}/tracks/{track_slug}/video/jobs/{kind}", response_class=HTMLResponse)
async def video_job_launch(request: Request, slug: str, track_slug: str, kind: str):
    root = get_repo_root()
    ctx = _context(root, slug)
    if ctx is None:
        return _not_found(track_slug)
    unit = _unit(ctx["release"], track_slug)
    if unit is None:
        return _not_found(track_slug)
    key = track_key(ctx["release"], unit["track"])
    if kind in {"frame", "contact"}:
        status = str(
            (unit["track"].get("music_video") or {}).get("status") or "draft"
        )
        if status not in {"cast", "previewed", "rendered"}:
            return _job_template(
                request,
                None,
                slug=slug,
                track_slug=track_slug,
                kind=kind,
                error="Save a reviewed section cast before rendering previews.",
            )
    time_seconds = None
    start_seconds = None
    end_seconds = None
    expected_fingerprint = None
    if kind == "frame":
        form = await request.form()
        try:
            time_seconds = float(str(form.get("time_seconds") or ""))
        except ValueError:
            return _job_template(
                request,
                None,
                slug=slug,
                track_slug=track_slug,
                kind=kind,
                error="Frame time must be a number.",
            )
    if kind == "draft":
        form = await request.form()
        section_id = str(form.get("section_id") or "").strip()
        try:
            state = load_rendering(root, ctx["release"], unit["track"])
            selected = next(
                (item for item in state["sections"] if item["id"] == section_id),
                None,
            )
            if section_id and selected is None:
                raise ValueError("Unknown section")
            if selected is not None:
                start_seconds = float(selected["start"])
                end_seconds = float(selected["end"])
            else:
                start_seconds = float(str(form.get("start_seconds") or ""))
                end_seconds = float(str(form.get("end_seconds") or ""))
        except (ValueError, VideoRenderingError) as exc:
            return _job_template(
                request,
                None,
                slug=slug,
                track_slug=track_slug,
                kind=kind,
                error=f"Invalid draft range: {exc}",
            )
    if kind in {"draft", "render_plan", "render"}:
        plan_job = db.get_latest_video_job(key, "render_plan")
        try:
            problems = render_launch_problems(
                root,
                ctx["release"],
                unit["track"],
                plan_job=plan_job,
                require_plan=kind == "render",
            )
        except VideoRenderingError as exc:
            problems = exc.problems
        if problems:
            return _job_template(
                request,
                None,
                slug=slug,
                track_slug=track_slug,
                kind=kind,
                error="; ".join(problems),
            )
        if kind == "render":
            try:
                state = load_rendering(
                    root,
                    ctx["release"],
                    unit["track"],
                    plan_job=plan_job,
                )
                expected_fingerprint = str(state["plan"]["input_fingerprint"])
            except (VideoRenderingError, KeyError, TypeError) as exc:
                return _job_template(
                    request,
                    None,
                    slug=slug,
                    track_slug=track_slug,
                    kind=kind,
                    error=f"Cannot pin full-render inputs: {exc}",
                )
    try:
        job_id = video_jobs.launch(
            root,
            slug,
            track_slug,
            key,
            kind,
            time_seconds=time_seconds,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            expected_fingerprint=expected_fingerprint,
        )
    except (video_jobs.VideoJobConflict, video_jobs.VideoJobError) as exc:
        return _job_template(
            request,
            None,
            slug=slug,
            track_slug=track_slug,
            kind=kind,
            error=str(exc),
        )
    return _job_template(
        request,
        db.get_video_job(job_id),
        slug=slug,
        track_slug=track_slug,
        kind=kind,
    )


@router.get("/releases/{slug}/tracks/{track_slug}/video/jobs/{job_id}", response_class=HTMLResponse)
async def video_job_poll(request: Request, slug: str, track_slug: str, job_id: str):
    job = db.get_video_job(job_id)
    if job is None or job["release_slug"] != slug or job["track_slug"] != track_slug:
        return _not_found(track_slug)
    return _job_template(request, job)


@router.post("/releases/{slug}/tracks/{track_slug}/video/jobs/{job_id}/cancel", response_class=HTMLResponse)
async def video_job_cancel(request: Request, slug: str, track_slug: str, job_id: str):
    job = db.get_video_job(job_id)
    if job is None or job["release_slug"] != slug or job["track_slug"] != track_slug:
        return _not_found(track_slug)
    try:
        updated = video_jobs.request_cancel(job_id)
    except video_jobs.VideoJobError as exc:
        return _job_template(request, job, error=str(exc))
    return _job_template(request, updated)
