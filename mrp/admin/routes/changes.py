from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.admin import changes_meta, db, gitops, publish_state
from mrp.admin import jobs as job_runner
from mrp.admin.deps import get_repo_root
from mrp.core.validate import validate_repository

router = APIRouter(prefix="/changes")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

MAX_FLASH_ERRORS = 8


def _panel_context(root: Path, flash: dict[str, str] | None = None,
                   validation_errors: list[dict[str, str]] | None = None) -> dict:
    branch = gitops.current_branch(root)
    changes = gitops.data_changes(root)
    changes_meta.annotate_changes(root, changes)
    for change in changes:
        try:
            change["diff"] = gitops.file_diff(root, change["path"], change["untracked"])
        except gitops.GitError as exc:
            change["diff"] = {"binary": False, "lines": [{"cls": "meta", "text": str(exc)}], "truncated": False}
    eligibility = changes_meta.eligibility_summary(changes)
    return {
        "branch": branch,
        "on_main": branch == gitops.COMMIT_BRANCH,
        "commit_branch": gitops.COMMIT_BRANCH,
        "changes": changes,
        "eligibility": eligibility,
        "can_stage": eligibility["all_eligible"],
        "generated_message": changes_meta.generate_commit_message(changes),
        "workflow": publish_state.workflow_status(root),
        "affected_pages": publish_state.affected_pages(changes, publish_state.STAGING_URL),
        "flash": flash,
        "validation_errors": validation_errors or [],
    }


def _stage_ctx(root: Path, job: dict | None = None, job_id: str | None = None,
               verify_error: str | None = None) -> dict:
    """Context for the staging status/job snippets (recomputes live state)."""
    changes = gitops.data_changes(root)
    changes_meta.annotate_changes(root, changes)
    job_result: dict = {}
    if job and job.get("status") == "done" and job.get("output"):
        try:
            job_result = json.loads(job["output"])
        except (ValueError, TypeError):
            job_result = {}
    return {
        "job": job,
        "job_id": job_id,
        "job_result": job_result,
        "verify_error": verify_error,
        "can_stage": changes_meta.eligibility_summary(changes)["all_eligible"],
        "workflow": publish_state.workflow_status(root),
        "affected_pages": publish_state.affected_pages(changes, publish_state.STAGING_URL),
    }


@router.get("", response_class=HTMLResponse)
async def changes_page(request: Request):
    root = get_repo_root()
    context = _panel_context(root)
    return _templates.TemplateResponse(request, "changes.html", context)


@router.get("/badge", response_class=HTMLResponse)
async def changes_badge(request: Request):
    """Nav indicator: managed-change count, or empty when the tree is clean."""
    root = get_repo_root()
    try:
        count = len(gitops.data_changes(root))
    except gitops.GitError:
        count = 0
    if not count:
        return HTMLResponse("")
    return HTMLResponse(f'<span class="nav-badge">{count}</span>')


@router.post("/stage", response_class=HTMLResponse)
async def changes_stage(request: Request):
    """Build the whole site and deploy the working tree to staging (no commit)."""
    root = get_repo_root()
    changes = gitops.data_changes(root)
    changes_meta.annotate_changes(root, changes)
    if not changes:
        ctx = _panel_context(root, flash={"cls": "warn", "text": "Nothing to stage — the working tree is clean."})
        return _templates.TemplateResponse(request, "changes/_panel.html", ctx)

    eligibility = changes_meta.eligibility_summary(changes)
    if not eligibility["all_eligible"]:
        blocked = ", ".join(eligibility["blocked_releases"].keys())
        ctx = _panel_context(root, flash={
            "cls": "error",
            "text": f"Blocked — make eligible (approved/live) or discard first: {blocked}",
        })
        return _templates.TemplateResponse(request, "changes/_panel.html", ctx)

    signature = publish_state.working_signature(root)
    job_id = job_runner.launch("changes/stage", publish_state.run_staging_deploy, str(root), signature)
    for _ in range(5):
        job = db.get_job(job_id)
        if job and job["status"] not in ("pending", "running"):
            break
        time.sleep(0.15)
    return _templates.TemplateResponse(request, "changes/_stage_job.html",
                                       _stage_ctx(root, job=job, job_id=job_id))


@router.get("/stage/poll/{job_id}", response_class=HTMLResponse)
async def changes_stage_poll(request: Request, job_id: str):
    root = get_repo_root()
    job = db.get_job(job_id)
    if job is None:
        return HTMLResponse('<div class="flash flash-error">Job not found.</div>', status_code=404)
    return _templates.TemplateResponse(request, "changes/_stage_job.html",
                                       _stage_ctx(root, job=job, job_id=job_id))


@router.post("/verify-staging", response_class=HTMLResponse)
async def changes_verify_staging(request: Request):
    root = get_repo_root()
    signature = publish_state.working_signature(root)
    ok = publish_state.mark_staging_verified(root, signature)
    err = None if ok else "Could not verify — staging is out of date. Redeploy to staging first."
    return _templates.TemplateResponse(request, "changes/_stage_status.html",
                                       _stage_ctx(root, verify_error=err))


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
