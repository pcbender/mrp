from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_APP_STUBS = {
    "critic": {
        "name": "Critic",
        "description": "Audio analysis pipeline — evaluates tracks against genre, mood, and sonic fingerprint profiles.",
        "path": "app/critic/",
        "commands": ["critic analyze", "critic report"],
    },
    "promoter": {
        "name": "Promoter",
        "description": "Social promo package generator — creates release announcements, bio blurbs, and promotional copy.",
        "path": "app/promoter/",
        "commands": ["promoter generate", "promoter blurb"],
    },
    "sampler": {
        "name": "Sampler",
        "description": "Preview audio generator — produces 30-second snippets and cover-art thumbnail assets.",
        "path": "app/sampler/",
        "commands": ["sampler clip", "sampler thumb"],
    },
}


@router.get("/critic", response_class=HTMLResponse)
async def critic(request: Request):
    return _templates.TemplateResponse(request, "app_stub.html", {"app": _APP_STUBS["critic"]})


@router.get("/promoter", response_class=HTMLResponse)
async def promoter(request: Request):
    return _templates.TemplateResponse(request, "app_stub.html", {"app": _APP_STUBS["promoter"]})


@router.get("/sampler", response_class=HTMLResponse)
async def sampler(request: Request):
    return _templates.TemplateResponse(request, "app_stub.html", {"app": _APP_STUBS["sampler"]})
