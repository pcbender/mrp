from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mrp.admin import db
from mrp.admin.routes import apps, jobs, releases, status

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield


app = FastAPI(title="MRP Admin", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(releases.router)
app.include_router(status.router)
app.include_router(jobs.router)
app.include_router(apps.router)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/releases")


def run_server(repo: str | Path, host: str = "127.0.0.1", port: int = 8000) -> None:
    repo_path = Path(repo).resolve()
    os.environ.setdefault("MRP_REPO", str(repo_path))
    pub_dir = repo_path / "site" / "public"
    if pub_dir.is_dir():
        app.mount("/pub", StaticFiles(directory=str(pub_dir)), name="site-public")
    uvicorn.run(app, host=host, port=port, log_level="info")
