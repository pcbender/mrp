from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.admin import db
from mrp.admin import jobs as job_runner
from mrp.admin.deps import get_repo_root
from mrp.admin.pipeline import enrich_missing_links

router = APIRouter(prefix="/jobs")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.post("/enrich-links", response_class=HTMLResponse)
async def launch_enrich_links(request: Request):
    root = get_repo_root()
    job_id = job_runner.launch("enrich-missing-links", enrich_missing_links, root)
    return _templates.TemplateResponse(request, "jobs/_result.html", {
        "job": db.get_job(job_id),
    })


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_status(request: Request, job_id: str):
    job = db.get_job(job_id)
    if job is None:
        return HTMLResponse('<div class="flash flash-error">Job not found.</div>', status_code=404)

    output_data = None
    if job["status"] in ("done", "error") and job.get("output"):
        try:
            output_data = json.loads(job["output"])
        except (ValueError, TypeError):
            output_data = job["output"]

    return _templates.TemplateResponse(request, "jobs/_result.html", {
        "job": job,
        "output": output_data,
    })
