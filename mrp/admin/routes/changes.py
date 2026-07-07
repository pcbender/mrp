from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.admin import gitops
from mrp.admin.deps import get_repo_root
from mrp.core.validate import validate_repository

router = APIRouter(prefix="/changes")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

MAX_FLASH_ERRORS = 8


def _panel_context(root: Path, flash: dict[str, str] | None = None,
                   validation_errors: list[dict[str, str]] | None = None) -> dict:
    branch = gitops.current_branch(root)
    changes = gitops.data_changes(root)
    for change in changes:
        try:
            change["diff"] = gitops.file_diff(root, change["path"], change["untracked"])
        except gitops.GitError as exc:
            change["diff"] = {"binary": False, "lines": [{"cls": "meta", "text": str(exc)}], "truncated": False}
    return {
        "branch": branch,
        "on_main": branch == gitops.COMMIT_BRANCH,
        "commit_branch": gitops.COMMIT_BRANCH,
        "changes": changes,
        "flash": flash,
        "validation_errors": validation_errors or [],
    }


@router.get("", response_class=HTMLResponse)
async def changes_page(request: Request):
    root = get_repo_root()
    context = _panel_context(root)
    return _templates.TemplateResponse(request, "changes.html", context)


@router.post("/approve", response_class=HTMLResponse)
async def changes_approve(request: Request):
    root = get_repo_root()
    form = await request.form()
    files = [str(f) for f in form.getlist("files")]
    message = str(form.get("message") or "").strip() or "admin: content updates"

    if not files:
        context = _panel_context(root, flash={"cls": "warn", "text": "No files selected."})
        return _templates.TemplateResponse(request, "changes/_panel.html", context)

    if any(f.startswith("content/") for f in files):
        validation = validate_repository(root)
        if validation["status"] != "passed":
            context = _panel_context(
                root,
                flash={"cls": "error", "text": "Validation failed — nothing was committed."},
                validation_errors=validation["errors"][:MAX_FLASH_ERRORS],
            )
            return _templates.TemplateResponse(request, "changes/_panel.html", context)

    try:
        result = gitops.approve(root, files, message)
    except gitops.GitError as exc:
        context = _panel_context(root, flash={"cls": "error", "text": str(exc)})
        return _templates.TemplateResponse(request, "changes/_panel.html", context)

    parts = [f"Committed {result['commit']} ({len(files)} file{'s' if len(files) != 1 else ''})"]
    cls = "ok"
    if result["push"] is None:
        parts.append("pushed to origin/main.")
    else:
        parts.append(f"push failed: {result['push']} — the commit is safe locally; approve again later to retry.")
        cls = "warn"
    if result["pull"]:
        parts.append(f"(pre-pull note: {result['pull']})")
    context = _panel_context(root, flash={"cls": cls, "text": " ".join(parts)})
    return _templates.TemplateResponse(request, "changes/_panel.html", context)


@router.post("/discard", response_class=HTMLResponse)
async def changes_discard(request: Request):
    root = get_repo_root()
    form = await request.form()
    path = str(form.get("discard_path") or "")
    entry = next((c for c in gitops.data_changes(root) if c["path"] == path), None)
    if entry is None:
        flash = {"cls": "warn", "text": f"{path} has no pending change."}
    else:
        try:
            gitops.discard(root, path, entry["untracked"])
            flash = {"cls": "ok", "text": f"Discarded {path}."}
        except (gitops.GitError, ValueError, OSError) as exc:
            flash = {"cls": "error", "text": f"Could not discard {path}: {exc}"}
    context = _panel_context(root, flash=flash)
    return _templates.TemplateResponse(request, "changes/_panel.html", context)
