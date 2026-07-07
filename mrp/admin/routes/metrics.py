from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mrp.core import metrics

router = APIRouter(prefix="/metrics")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _drop_folder() -> str:
    return os.environ.get("MRP_METRICS_DROP", "/mnt/c/Docs")


def _page_context(result: dict | None = None, flash: dict | None = None,
                  folder: str | None = None) -> dict:
    conn = metrics.open_db()
    try:
        return {
            "folder": folder or _drop_folder(),
            "result": result,
            "flash": flash,
            "artists": metrics.streams_by_artist(conn),
            "imports": metrics.recent_imports(conn),
        }
    finally:
        conn.close()


@router.get("", response_class=HTMLResponse)
async def metrics_page(request: Request):
    return _templates.TemplateResponse(request, "metrics.html", _page_context())


@router.post("/import", response_class=HTMLResponse)
async def metrics_import(request: Request, folder: str = Form("")):
    folder = folder.strip() or _drop_folder()
    conn = metrics.open_db()
    try:
        result = metrics.import_folder(conn, Path(folder))
    except ValueError as exc:
        return _templates.TemplateResponse(
            request, "metrics.html",
            _page_context(flash={"cls": "error", "text": str(exc)}, folder=folder),
            status_code=400,
        )
    finally:
        conn.close()

    if not result["files"] and not result["errors"]:
        flash = {"cls": "warn", "text": "No LANDR/Amuse report files found in the folder."}
    elif result["errors"]:
        flash = {"cls": "warn", "text": f"Imported with errors — {result['inserted']} new rows, {result['skipped']} duplicates skipped."}
    else:
        flash = {"cls": "ok", "text": f"Imported {result['inserted']} new rows ({result['skipped']} duplicates skipped)."}
    return _templates.TemplateResponse(
        request, "metrics.html", _page_context(result=result, flash=flash, folder=folder)
    )
