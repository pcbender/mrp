from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.admin.deps import get_repo_root
from mrp.core.status import status as get_status

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/status", response_class=HTMLResponse)
async def status_view(request: Request):
    root = get_repo_root()
    result = get_status(root)
    return _templates.TemplateResponse(request, "status.html", {
        "result": result,
        "latest": result.get("latest") or {},
    })
