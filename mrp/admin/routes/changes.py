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

LADDER_TEMPLATE = "changes/_publish_ladder.html"
PANEL_TEMPLATE = "changes/_panel.html"


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
        "affected": publish_state.affected_pages(changes, ""),
        "flash": flash,
        "validation_errors": validation_errors or [],
    }


def _ladder_ctx(root: Path, stage_job: dict | None = None, stage_job_id: str | None = None,
                prod_job: dict | None = None, prod_job_id: str | None = None,
                verify_error: str | None = None, error: str | None = None) -> dict:
    """Context for the publish ladder snippet (recomputes live workflow state)."""
    changes = gitops.data_changes(root)
    changes_meta.annotate_changes(root, changes)

    def _result(job: dict | None) -> dict:
        if job and job.get("status") == "done" and job.get("output"):
            try:
                return json.loads(job["output"])
            except (ValueError, TypeError):
                return {}
        return {}

    return {
        "changes": changes,
        "generated_message": changes_meta.generate_commit_message(changes),
        "can_stage": changes_meta.eligibility_summary(changes)["all_eligible"],
        "workflow": publish_state.workflow_status(root),
        "affected": publish_state.affected_pages(changes, ""),
        "stage_job": stage_job, "stage_job_id": stage_job_id, "stage_result": _result(stage_job),
        "prod_job": prod_job, "prod_job_id": prod_job_id, "prod_result": _result(prod_job),
        "verify_error": verify_error,
        "error": error,
    }


def _await_job(job_id: str) -> dict | None:
    """Give a launched job a brief head start so fast failures render inline."""
    job = db.get_job(job_id)
    for _ in range(5):
        job = db.get_job(job_id)
        if job and job["status"] not in ("pending", "running"):
            break
        time.sleep(0.15)
    return job


@router.get("", response_class=HTMLResponse)
async def changes_page(request: Request):
    root = get_repo_root()
    return _templates.TemplateResponse(request, "changes.html", _panel_context(root))


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


# --- Staging -----------------------------------------------------------------

@router.post("/stage", response_class=HTMLResponse)
async def changes_stage(request: Request):
    """Build the whole site and deploy the working tree to staging (no commit)."""
    root = get_repo_root()
    changes = gitops.data_changes(root)
    changes_meta.annotate_changes(root, changes)
    if not changes:
        return _templates.TemplateResponse(request, LADDER_TEMPLATE,
                                           _ladder_ctx(root, error="Nothing to stage — the working tree is clean."))
    eligibility = changes_meta.eligibility_summary(changes)
    if not eligibility["all_eligible"]:
        blocked = ", ".join(eligibility["blocked_releases"].keys())
        return _templates.TemplateResponse(request, LADDER_TEMPLATE, _ladder_ctx(
            root, error=f"Blocked — make eligible (approved/live) or discard first: {blocked}"))

    signature = publish_state.working_signature(root)
    job_id = job_runner.launch("changes/stage", publish_state.run_staging_deploy, str(root), signature)
    job = _await_job(job_id)
    return _templates.TemplateResponse(request, LADDER_TEMPLATE,
                                       _ladder_ctx(root, stage_job=job, stage_job_id=job_id))


@router.get("/stage/poll/{job_id}", response_class=HTMLResponse)
async def changes_stage_poll(request: Request, job_id: str):
    root = get_repo_root()
    job = db.get_job(job_id)
    if job is None:
        return HTMLResponse('<div class="flash flash-error">Job not found.</div>', status_code=404)
    return _templates.TemplateResponse(request, LADDER_TEMPLATE,
                                       _ladder_ctx(root, stage_job=job, stage_job_id=job_id))


@router.post("/verify-staging", response_class=HTMLResponse)
async def changes_verify_staging(request: Request):
    root = get_repo_root()
    ok = publish_state.mark_staging_verified(root, publish_state.working_signature(root))
    err = None if ok else "Could not verify — staging is out of date. Redeploy to staging first."
    return _templates.TemplateResponse(request, LADDER_TEMPLATE, _ladder_ctx(root, verify_error=err))


# --- Production --------------------------------------------------------------

@router.post("/production", response_class=HTMLResponse)
async def changes_production(request: Request):
    """Promote the staged+verified build to production (same build), then verify."""
    root = get_repo_root()
    workflow = publish_state.workflow_status(root)
    if not workflow["staging_verified"]:
        return _templates.TemplateResponse(request, LADDER_TEMPLATE, _ladder_ctx(
            root, error="Deploy and verify staging before pushing to production."))
    job_id = job_runner.launch("changes/production", publish_state.run_production_deploy,
                               str(root), workflow["signature"], workflow["staged_build_id"])
    job = _await_job(job_id)
    return _templates.TemplateResponse(request, LADDER_TEMPLATE,
                                       _ladder_ctx(root, prod_job=job, prod_job_id=job_id))


@router.get("/production/poll/{job_id}", response_class=HTMLResponse)
async def changes_production_poll(request: Request, job_id: str):
    root = get_repo_root()
    job = db.get_job(job_id)
    if job is None:
        return HTMLResponse('<div class="flash flash-error">Job not found.</div>', status_code=404)
    return _templates.TemplateResponse(request, LADDER_TEMPLATE,
                                       _ladder_ctx(root, prod_job=job, prod_job_id=job_id))


@router.post("/verify-production", response_class=HTMLResponse)
async def changes_verify_production(request: Request):
    root = get_repo_root()
    ok = publish_state.mark_production_verified(root, publish_state.working_signature(root))
    err = None if ok else "Could not verify — production is out of date. Redeploy to production first."
    return _templates.TemplateResponse(request, LADDER_TEMPLATE, _ladder_ctx(root, verify_error=err))


# --- Approve, Commit, and Push (final rung) ---------------------------------

@router.post("/approve", response_class=HTMLResponse)
async def changes_approve(request: Request):
    root = get_repo_root()
    form = await request.form()
    changes = gitops.data_changes(root)
    changes_meta.annotate_changes(root, changes)
    message = str(form.get("message") or "").strip() or changes_meta.generate_commit_message(changes)

    if not changes:
        ctx = _panel_context(root, flash={"cls": "warn", "text": "Nothing to commit — the working tree is clean."})
        return _templates.TemplateResponse(request, PANEL_TEMPLATE, ctx)

    workflow = publish_state.workflow_status(root)
    if not workflow["can_commit"]:
        ctx = _panel_context(root, flash={
            "cls": "error",
            "text": "Deploy and verify staging and production before committing.",
        })
        return _templates.TemplateResponse(request, PANEL_TEMPLATE, ctx)

    eligibility = changes_meta.eligibility_summary(changes)
    if not eligibility["all_eligible"]:
        blocked = ", ".join(eligibility["blocked_releases"].keys())
        ctx = _panel_context(root, flash={"cls": "error", "text": f"Blocked — not eligible: {blocked}"})
        return _templates.TemplateResponse(request, PANEL_TEMPLATE, ctx)

    validation = validate_repository(root)
    if validation["status"] != "passed":
        ctx = _panel_context(
            root,
            flash={"cls": "error", "text": "Validation failed — nothing was committed."},
            validation_errors=validation["errors"][:MAX_FLASH_ERRORS],
        )
        return _templates.TemplateResponse(request, PANEL_TEMPLATE, ctx)

    files = [c["path"] for c in changes]
    try:
        result = gitops.approve(root, files, message)
    except gitops.GitError as exc:
        ctx = _panel_context(root, flash={"cls": "error", "text": str(exc)})
        return _templates.TemplateResponse(request, PANEL_TEMPLATE, ctx)

    publish_state.clear_state(root)
    parts = [f"Committed {result['commit']} ({len(files)} file{'s' if len(files) != 1 else ''})"]
    cls = "ok"
    if result["push"] is None:
        parts.append("pushed to origin/main.")
    else:
        parts.append(f"push failed: {result['push']} — the commit is safe locally; approve again later to retry.")
        cls = "warn"
    if result["pull"]:
        parts.append(f"(pre-pull note: {result['pull']})")
    ctx = _panel_context(root, flash={"cls": cls, "text": " ".join(parts)})
    return _templates.TemplateResponse(request, PANEL_TEMPLATE, ctx)


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
    return _templates.TemplateResponse(request, PANEL_TEMPLATE, _panel_context(root, flash=flash))
