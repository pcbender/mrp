from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from mrp.admin import nim
from mrp.admin.deps import get_repo_root

router = APIRouter(prefix="/nim")


def _base_url(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


@router.get("/connect")
async def connect(request: Request, return_to: str = "/releases"):
    try:
        url = nim.begin_oauth(get_repo_root(), _base_url(request), return_to)
    except nim.NimConfigurationError as exc:
        return HTMLResponse(
            '<div class="flash flash-error">'
            f"<strong>Could not connect to Nim.</strong> {str(exc)}"
            "<p style='margin:.35rem 0 0;font-size:12px'>Nim registers this admin "
            "automatically — no client id to configure. Check the network and retry.</p>"
            "</div>",
            status_code=502,
        )
    return RedirectResponse(url)


@router.get("/credits")
async def credits(request: Request):
    try:
        balance = nim.credit_balance(get_repo_root())
    except nim.NimAuthRequiredError:
        return HTMLResponse('<span class="badge badge-failed">not connected</span>')
    except (nim.NimConfigurationError, nim.NimGenerationError) as exc:
        return HTMLResponse(
            f'<span class="badge badge-failed" title="{html.escape(str(exc))}">credits unavailable</span>')
    total = int(balance.get("totalAvailableCredits") or 0)
    subscription = balance.get("subscriptionCredits") or {}
    sub_max = int(subscription.get("max") or 0)
    detail = f"{total:,} / {sub_max:,}" if sub_max else f"{total:,}"
    renders = total // nim.DEFAULT_MODEL_CREDITS
    return HTMLResponse(
        f'<span class="badge badge-live" title="≈ {renders} animated covers at '
        f'{nim.DEFAULT_MODEL_CREDITS} credits each">{detail} credits</span>')


@router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = "", state: str = ""):
    if not code or not state:
        return HTMLResponse('<div class="flash flash-error">Nim did not return an OAuth code.</div>', status_code=400)
    try:
        return_to = nim.finish_oauth(code, state)
    except nim.NimConfigurationError as exc:
        return HTMLResponse(f'<div class="flash flash-error">{str(exc)}</div>', status_code=400)
    return RedirectResponse(return_to)
