from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from mrp.admin import db, video_jobs
from mrp.admin.routes import actors, apps, artists, catalog, changes, identity, jobs, metrics, nim, posts, releases, status, video, workspace

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    video_jobs.recover()
    yield


app = FastAPI(title="MRP Admin", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(releases.router)
app.include_router(catalog.router)
app.include_router(artists.router)
app.include_router(actors.router)
app.include_router(identity.router)
app.include_router(posts.router)
app.include_router(workspace.router)
app.include_router(video.router)
app.include_router(status.router)
app.include_router(changes.router)
app.include_router(metrics.router)
app.include_router(nim.router)
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
    processed_dir = repo_path / "assets" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/processed", StaticFiles(directory=str(processed_dir)), name="processed")
    assets_dir = repo_path / "assets"
    app.mount("/repo-assets", StaticFiles(directory=str(assets_dir)), name="repo-assets")
    uvicorn.run(app, host=host, port=port, log_level="info")
