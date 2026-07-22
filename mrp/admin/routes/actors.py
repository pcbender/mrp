"""Standalone Actor Designer: the reusable spirogram actor library."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.admin.deps import get_repo_root
from mrp.admin.video_casting import (
    CastingEditorError,
    actor_preview_shapes,
    library_actor,
    list_library_actors,
    save_library_actor,
)

router = APIRouter(prefix="/actors")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _library_error(request: Request, problems: tuple[str, ...]) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "releases/_validation.html",
        {
            "errors": [
                {"field": "actor", "message": problem, "severity": "error"}
                for problem in problems
            ]
        },
        status_code=422,
    )


@router.get("", response_class=HTMLResponse)
async def actors_index(request: Request):
    root = get_repo_root()
    try:
        actors = list_library_actors(root)
    except CastingEditorError as exc:
        return _library_error(request, exc.problems)
    for entry in actors:
        entry["shapes"] = actor_preview_shapes(entry["actor"])
    return _templates.TemplateResponse(
        request,
        "actors/index.html",
        {"actors": actors},
    )


@router.get("/new", response_class=HTMLResponse)
async def actors_new(request: Request):
    return _templates.TemplateResponse(
        request,
        "actors/designer.html",
        {"entry": None},
    )


@router.get("/{actor_id}", response_class=HTMLResponse)
async def actors_designer(request: Request, actor_id: str):
    root = get_repo_root()
    try:
        entry = library_actor(root, actor_id)
    except CastingEditorError as exc:
        return _library_error(request, exc.problems)
    if entry is None:
        return HTMLResponse(
            f"Library actor <b>{actor_id}</b> not found.", status_code=404
        )
    return _templates.TemplateResponse(
        request,
        "actors/designer.html",
        {"entry": entry},
    )


@router.post("/save", response_class=HTMLResponse)
async def actors_save(request: Request):
    root = get_repo_root()
    form = await request.form()
    fields = {str(name): form.getlist(name) for name in form.keys()}
    try:
        actor_id = save_library_actor(root, fields)
    except CastingEditorError as exc:
        return _library_error(request, exc.problems)
    response = HTMLResponse('<div class="flash flash-ok">Library actor saved.</div>')
    response.headers["HX-Redirect"] = f"/actors/{actor_id}" if actor_id else "/actors"
    return response
