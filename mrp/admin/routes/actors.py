"""Standalone Actor Designer: the reusable spirogram actor library."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from mrp.admin.deps import get_repo_root
from mrp.admin.video_casting import (
    CastingEditorError,
    actor_preview_shapes,
    library_actor,
    list_library_actors,
    save_library_actor,
    split_svg_subpaths,
)

router = APIRouter(prefix="/actors")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _artist_options(root: Path) -> list[dict[str, str]]:
    """Artist ids + display names for the AI-generation panel select."""
    import yaml

    options = []
    for path in sorted((root / "content" / "artists").glob("*.yaml")):
        try:
            record = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        artist = record.get("artist") or {}
        artist_id = artist.get("id") or path.stem
        options.append({"id": artist_id, "name": artist.get("name") or artist_id})
    return options


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
        {"entry": None, "artist_options": _artist_options(get_repo_root())},
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
        {"entry": entry, "artist_options": _artist_options(root)},
    )


@router.post("/svg-generate")
async def actors_svg_generate(request: Request):
    """Generate raw SVG shapes with AI and split them into subpath entries."""
    from mrp.admin import svg_gen

    root = get_repo_root()
    form = await request.form()
    brief = str(form.get("brief") or "").strip()
    artist_id = str(form.get("artist_id") or "").strip()
    try:
        max_subpaths = int(str(form.get("max_subpaths") or "6"))
    except ValueError:
        max_subpaths = 6
    try:
        if artist_id:
            artist_lines = svg_gen.artist_brief(root, artist_id)
            brief = f"{artist_lines}\n{brief}" if brief else artist_lines
        if not brief:
            raise CastingEditorError(
                "svg generation requires a design brief or an artist"
            )
        result = svg_gen.generate_svg_shapes(
            root, brief, max_subpaths=max_subpaths
        )
    except CastingEditorError as exc:
        return JSONResponse({"errors": list(exc.problems)}, status_code=422)
    return JSONResponse(result)


@router.post("/text-outline")
async def actors_text_outline(request: Request):
    """Outline a word in a real font as a single multi-subpath text layer."""
    from mrp.admin import text_outline

    root = get_repo_root()
    form = await request.form()
    text = str(form.get("text") or "").strip()
    try:
        tracking = float(str(form.get("tracking") or "0"))
    except ValueError:
        tracking = 0.0
    try:
        font = text_outline.resolve_font(root, str(form.get("font") or "") or None)
        path_data = text_outline.text_to_path_data(text, font, tracking=tracking)
    except CastingEditorError as exc:
        return JSONResponse({"errors": list(exc.problems)}, status_code=422)
    return JSONResponse({"path_data": path_data})


@router.post("/svg-subpaths")
async def actors_svg_subpaths(request: Request):
    """Split uploaded SVG text (or a bare d attribute) into subpath entries."""
    form = await request.form()
    try:
        subpaths = split_svg_subpaths(str(form.get("svg") or ""))
    except CastingEditorError as exc:
        return JSONResponse({"errors": list(exc.problems)}, status_code=422)
    return JSONResponse({"subpaths": subpaths})


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
