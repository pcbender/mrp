"""Optional per-track music-video workspace and process-job routes."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.admin import db, video_jobs
from mrp.admin.deps import get_repo_root
from mrp.admin.video_casting import (
    CastingEditorError,
    load_casting,
    previews_path,
    save_casting,
)
from mrp.admin.video_timing import TimingEditorError, load_timing, save_timing
from mrp.admin.video_workspace import (
    STEM_ROLES,
    resolve_asset,
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
    if job and job.get("kind") == "frame":
        marker, separator, value = str(job.get("command") or "").rpartition("@")
        if separator and marker:
            preview_time = value
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
        result = save_timing(root, release, unit["track"], fields)
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
    path.write_text(serialize_structured_record(path, data), encoding="utf-8")
    response = HTMLResponse(
        '<div class="flash flash-ok">Timing and review state saved.</div>'
    )
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/timing"
    )
    return response


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
        )
    except CastingEditorError as exc:
        casting = None
        casting_error = list(exc.problems)
    status = str((unit["track"].get("music_video") or {}).get("status") or "draft")
    ctx.update(
        {
            "unit": unit,
            "track": unit["track"],
            "track_slug": track_slug,
            "track_key": key,
            "casting": casting,
            "casting_error": casting_error,
            "cast_status_ok": status in {"timed", "cast", "previewed", "rendered"},
            "frame_job": db.get_latest_video_job(key, "frame"),
            "contact_job": db.get_latest_video_job(key, "contact"),
        }
    )
    return _templates.TemplateResponse(request, "releases/workspace/video_casting.html", ctx)


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
    response.headers["HX-Redirect"] = (
        f"/releases/{slug}/tracks/{track_slug}/video/casting"
        f"?section={selected.id}&scope={result['scope']}"
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


@router.post("/releases/{slug}/tracks/{track_slug}/video/assets", response_class=HTMLResponse)
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
    try:
        job_id = video_jobs.launch(
            root,
            slug,
            track_slug,
            key,
            kind,
            time_seconds=time_seconds,
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
