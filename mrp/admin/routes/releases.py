from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mrp.admin import db, pipeline as pipe
from mrp.admin import jobs as job_runner
from mrp.admin.deps import get_repo_root
from mrp.admin.workspace import (
    PLATFORM_KEYS,
    STATUSES,
    bool_field as _bool_field,
    str_or_none as _str_or_none,
    validate_release_dict as _validate_release_dict,
)
from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.release import infer_distributor, slugify
from mrp.core.validate import validate_repository

router = APIRouter()
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
_templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else {}

PIPELINE_STEPS = [
    ("odesli",       "Streaming Links (Odesli)", pipe.enrich_odesli),
    ("promo",        "Distributor Promo Links",  pipe.enrich_promo_links),
    ("apple-music",  "Apple Music",              pipe.enrich_apple_music),
    ("youtube",      "YouTube",                  pipe.enrich_youtube),
    ("critic",       "Critic",                   pipe.run_critic),
    ("sampler",      "Sampler",                  pipe.run_sampler),
    ("promoter",     "Promoter",                 pipe.run_promoter),
]
_PIPELINE_MAP = {step: (label, fn) for step, label, fn in PIPELINE_STEPS}


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _load_all_releases(root: Path) -> list[dict[str, Any]]:
    releases_dir = root / "content" / "releases"
    rows = []
    for path in sorted(releases_dir.glob("*.yaml")):
        try:
            data = load_structured_record(path)
        except Exception:
            continue
        rel = data.get("release")
        if not isinstance(rel, dict):
            continue
        links = rel.get("links") or {}
        platform_count = sum(1 for k in PLATFORM_KEYS if links.get(k))
        rows.append({
            "slug": path.stem,
            "title": rel.get("title", path.stem),
            "artist_id": rel.get("artist_id", ""),
            "model": rel.get("model", ""),
            "release_type": rel.get("release_type", ""),
            "status": rel.get("status", ""),
            "release_date": rel.get("release_date") or "",
            "platform_count": platform_count,
        })
    rows.sort(key=lambda r: r["release_date"] or "0000", reverse=True)
    return rows


def _filter_releases(rows: list[dict], q: str, status_f: str, model_f: str) -> list[dict]:
    if q:
        q_lower = q.lower()
        rows = [r for r in rows if q_lower in r["title"].lower() or q_lower in r["artist_id"].lower()]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if model_f:
        rows = [r for r in rows if r["model"] == model_f]
    return rows


@router.get("/releases", response_class=HTMLResponse)
async def releases_list(
    request: Request,
    q: str = "",
    status_filter: str = "",
    model_filter: str = "",
):
    root = get_repo_root()
    rows = _load_all_releases(root)
    filtered = _filter_releases(rows, q, status_filter, model_filter)
    ctx = {
        "releases": filtered,
        "total": len(rows),
        "q": q,
        "status_filter": status_filter,
        "model_filter": model_filter,
        "statuses": STATUSES,
    }
    if _is_htmx(request):
        return _templates.TemplateResponse(request, "releases/_table_body.html", ctx)
    return _templates.TemplateResponse(request, "releases/list.html", ctx)


@router.get("/releases/new", response_class=HTMLResponse)
async def release_new(request: Request):
    return _templates.TemplateResponse(request, "releases/new.html", {})


@router.post("/releases", response_class=HTMLResponse)
async def release_create(
    request: Request,
    title: str = Form(...),
    artist_id: str = Form(...),
    release_type: str = Form(...),
):
    model = "song" if release_type == "single" else "album"
    root = get_repo_root()
    slug = slugify(title)
    path = root / "content" / "releases" / f"{slug}.yaml"
    if path.exists():
        return HTMLResponse(
            f'<div class="flash flash-error">A release with slug <code>{slug}</code> already exists.</div>',
            status_code=409,
        )
    skeleton = _new_release_skeleton(slug, title, artist_id, model, release_type)
    path.write_text(serialize_structured_record(path, {"release": skeleton}))
    return RedirectResponse(url=f"/releases/{slug}/details", status_code=303)


@router.get("/releases/new/manual", response_class=HTMLResponse)
async def release_new_manual(request: Request):
    root = get_repo_root()
    artists = _load_artists(root)
    return _templates.TemplateResponse(request, "releases/new_manual.html", {"artists": artists})


@router.post("/releases/import/preview", response_class=HTMLResponse)
async def release_import_preview(request: Request, spotify_url: str = Form(...)):
    root = get_repo_root()
    try:
        from mrp.core.import_spotify import build_track
        from mrp.core.spotify_client import SpotifyClient
        spotify = SpotifyClient.from_env(repo=root)
        album_id = _spotify_album_id(spotify_url, spotify)
        album = spotify.get_album(album_id)
        simplified = album.get("tracks", {}).get("items", [])
        full_tracks = {t["id"]: t for t in spotify.get_tracks([t["id"] for t in simplified])} if simplified else {}
        tracks = [
            build_track(i + 1, full_tracks.get(t["id"], t))
            for i, t in enumerate(simplified)
        ]
        artist_name = (album.get("artists") or [{}])[0].get("name") or "Unknown Artist"
        is_single = len(tracks) == 1
        release_type = "single" if is_single else ("ep" if len(tracks) <= 6 else "album")
        images = album.get("images") or []
    except Exception as exc:
        return HTMLResponse(f'<div class="flash flash-error">{exc}</div>', status_code=400)

    return _templates.TemplateResponse(request, "releases/_import_step2.html", {
        "album_id": album_id,
        "title": album.get("name", ""),
        "artist_name": artist_name,
        "release_type": release_type,
        "release_date": album.get("release_date"),
        "cover_url": images[0]["url"] if images else None,
        "tracks": tracks,
        "is_single": is_single,
    })


@router.post("/releases/import", response_class=HTMLResponse)
async def release_import(
    request: Request,
    album_id: str = Form(...),
    track_count: int = Form(...),
):
    root = get_repo_root()
    form = await request.form()
    per_track = [
        {
            "style": str(form.get(f"track_{i}_style", "")).strip() or None,
            "lyrics_raw": str(form.get(f"track_{i}_lyrics_raw", "")).strip() or None,
            "master_path": str(form.get(f"track_{i}_master_path", "")).strip() or None,
        }
        for i in range(track_count)
    ]
    try:
        slug = _do_spotify_import(root, album_id, per_track)
    except Exception as exc:
        return HTMLResponse(f'<div class="flash flash-error">{exc}</div>', status_code=400)
    # This form is submitted via hx-post into #step2, so a 303 would be
    # followed by htmx and the target page (nav included) swapped into the
    # panel. Use HX-Redirect for a real browser navigation to the workspace.
    response = HTMLResponse('<div class="flash flash-ok">Release created.</div>')
    response.headers["HX-Redirect"] = f"/releases/{slug}/details"
    return response


@router.get("/releases/{slug}/edit", response_class=HTMLResponse)
async def release_edit(request: Request, slug: str):
    # Legacy URL — the giant edit form was replaced by the workspace.
    return RedirectResponse(url=f"/releases/{slug}/details", status_code=303)


@router.post("/releases/{slug}/delete", response_class=HTMLResponse)
async def release_delete(request: Request, slug: str):
    root = get_repo_root()
    path = root / "content" / "releases" / f"{slug}.yaml"
    if not path.exists():
        return HTMLResponse(f"Release <b>{slug}</b> not found.", status_code=404)
    data = load_structured_record(path)
    status = data.get("release", {}).get("status", "")
    if status == "live":
        return HTMLResponse(
            '<div class="flash flash-error">Cannot delete a live release.</div>',
            status_code=403,
        )
    path.unlink()
    response = RedirectResponse(url="/releases", status_code=303)
    return response


@router.get("/releases/{slug}/validate", response_class=HTMLResponse)
async def release_validate(request: Request, slug: str):
    root = get_repo_root()
    result = validate_repository(root, release=slug)
    errors = result.get("errors") or []
    return _templates.TemplateResponse(request, "releases/_validation.html", {
        "errors": errors,
        "status": result.get("status"),
    })


@router.post("/releases/{slug}/pipeline/{step}", response_class=HTMLResponse)
async def pipeline_launch(request: Request, slug: str, step: str):
    if step not in _PIPELINE_MAP:
        return HTMLResponse(f'<div class="flash flash-error">Unknown pipeline step: {step}</div>', status_code=400)
    label, fn = _PIPELINE_MAP[step]
    root = get_repo_root()

    kwargs: dict = {}
    if step == "critic":
        form = await request.form()
        kwargs["model"] = str(form.get("critic_model", "dev"))
        kwargs["persona"] = str(form.get("critic_persona", "default"))
        kwargs["target"] = str(form.get("critic_target", "blurb"))
        tier = form.get("critic_target_tier", "")
        if tier:
            try:
                kwargs["target_tier"] = int(str(tier))
            except ValueError:
                pass

    job_id = job_runner.launch(f"{slug}/{step}", fn, root, slug, **kwargs)
    # Brief wait for fast steps (e.g. Apple Music) that finish before the response goes out
    for _ in range(5):
        job = db.get_job(job_id)
        if job and job["status"] not in ("pending", "running"):
            break
        time.sleep(0.15)
    response = _templates.TemplateResponse(request, "releases/_pipeline_step.html", {
        "slug": slug,
        "step": step,
        "step_label": label,
        "job": job,
        "critic_settings": kwargs if step == "critic" else {},
    })
    if job and job["status"] == "done":
        response.headers["HX-Trigger"] = "releaseSaved"
    return response


@router.get("/releases/{slug}/pipeline/{step}/poll/{job_id}", response_class=HTMLResponse)
async def pipeline_poll(request: Request, slug: str, step: str, job_id: str):
    if step not in _PIPELINE_MAP:
        return HTMLResponse('<div class="flash flash-error">Unknown step</div>', status_code=400)
    label = _PIPELINE_MAP[step][0]
    job = db.get_job(job_id)
    if job is None:
        return HTMLResponse('<div class="flash flash-error">Job not found</div>', status_code=404)
    critic_settings: dict = {}
    if step == "critic" and job.get("output"):
        try:
            out = json.loads(job["output"])
            critic_settings = {
                "critic_model":   out.get("model", "dev"),
                "critic_persona": out.get("persona", "default"),
                "critic_target":  out.get("target", "blurb"),
            }
        except (ValueError, TypeError):
            pass
    response = _templates.TemplateResponse(request, "releases/_pipeline_step.html", {
        "slug": slug,
        "step": step,
        "step_label": label,
        "job": job,
        "critic_settings": critic_settings,
    })
    if job["status"] == "done":
        response.headers["HX-Trigger"] = "releaseSaved"
    return response


@router.get("/missing-links", response_class=HTMLResponse)
async def missing_links(request: Request):
    root = get_repo_root()
    releases_dir = root / "content" / "releases"
    rows = []
    for path in sorted(releases_dir.glob("*.yaml")):
        try:
            data = load_structured_record(path)
        except Exception:
            continue
        rel = data.get("release")
        if not isinstance(rel, dict):
            continue
        links = rel.get("links") or {}
        na = set((rel.get("automation") or {}).get("links_na") or [])
        missing = [k for k in PLATFORM_KEYS if not links.get(k) and k not in na]
        if missing:
            rows.append({
                "slug": path.stem,
                "title": rel.get("title", path.stem),
                "artist_id": rel.get("artist_id", ""),
                "missing": missing,
                "present": [k for k in PLATFORM_KEYS if links.get(k)],
                "na": sorted(na),
            })
    return _templates.TemplateResponse(request, "missing_links.html", {
        "rows": rows,
        "platform_keys": PLATFORM_KEYS,
    })


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_artists(root: Path) -> list[dict[str, Any]]:
    artists_dir = root / "content" / "artists"
    result = []
    # Artist records are YAML; tolerate legacy JSON records too
    # (load_structured_record handles both).
    for path in sorted(list(artists_dir.glob("*.yaml")) + list(artists_dir.glob("*.json"))):
        try:
            data = load_structured_record(path)
        except Exception:
            continue
        a = data.get("artist", {})
        result.append({"id": a.get("id", path.stem), "name": a.get("name", path.stem)})
    return result


def _spotify_album_id(url: str, spotify: Any) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) >= 2:
        kind, sid = parts[0], parts[1]
        if kind == "album":
            return sid
        if kind == "track":
            tracks = spotify.get_tracks([sid])
            if tracks and tracks[0].get("album", {}).get("id"):
                return tracks[0]["album"]["id"]
    raise ValueError(f"Cannot parse a Spotify album ID from: {url}")


def _do_spotify_import(
    root: Path,
    album_id: str,
    per_track: list[dict],
) -> str:
    from mrp.core.import_spotify import build_release_candidate
    from mrp.core.spotify_client import SpotifyClient

    spotify = SpotifyClient.from_env(repo=root)
    album = spotify.get_album(album_id)
    slug = slugify(album.get("name") or album_id)
    artist_name = (album.get("artists") or [{}])[0].get("name") or "unknown"
    artist_id = slugify(artist_name)

    path = root / "content" / "releases" / f"{slug}.yaml"
    if path.exists():
        raise ValueError(f"Release '{slug}' already exists — open the edit page instead.")

    mapped = build_release_candidate(artist_id, slug, album, spotify)
    release = mapped["release"]

    release.pop("review_status", None)
    release.pop("notes", None)

    release["label"] = "Maricopa Records"
    release["publisher"] = "Maricopa Publishing"
    release["distributor"] = infer_distributor(release.get("upc"))
    release["status"] = "draft"

    title = release.get("title", "")
    release.setdefault("seo", {"title": title, "description": f"{title} on Maricopa Records."})

    from mrp.core.lyrics_text import clean_lyrics, extract_primary_section

    def _clean(raw: str | None) -> str | None:
        if not raw:
            return None
        return clean_lyrics(extract_primary_section(raw)) or None

    if release.get("model") == "song" and isinstance(release.get("song"), dict):
        t = per_track[0] if per_track else {}
        song = release["song"]
        song["style"] = t.get("style")
        song["lyrics_raw"] = t.get("lyrics_raw")
        song["lyrics_text"] = _clean(t.get("lyrics_raw"))
        song.setdefault("lyrics_source", None)
        song.setdefault("hints", {})
        automation: dict[str, Any] = {"allow_auto_publish": False}
        if t.get("master_path"):
            automation["master_path"] = t["master_path"]
        release["automation"] = automation
    else:
        for i, track in enumerate(release.get("tracks") or []):
            t = per_track[i] if i < len(per_track) else {}
            track["style"] = t.get("style")
            track["lyrics_raw"] = t.get("lyrics_raw")
            track["lyrics_text"] = _clean(t.get("lyrics_raw"))
            track.setdefault("lyrics_source", None)
            track.setdefault("hints", {})
        master_paths = [t.get("master_path") for t in per_track if t.get("master_path")]
        automation = {"allow_auto_publish": False}
        if master_paths:
            automation["master_path"] = master_paths[0] if len(master_paths) == 1 else master_paths
        release["automation"] = automation

    cover_url = mapped.get("cover_url")
    if cover_url:
        cover_rel = f"site/public/assets/releases/{slug}/cover.jpg"
        cover_abs = root / cover_rel
        cover_abs.parent.mkdir(parents=True, exist_ok=True)
        cover_abs.write_bytes(spotify.download(cover_url))
        release["cover_image"] = cover_rel

    path.write_text(serialize_structured_record(path, {"release": release}))
    return slug


def _new_release_skeleton(
    slug: str, title: str, artist_id: str, model: str, release_type: str
) -> dict[str, Any]:
    skeleton: dict[str, Any] = {
        "id": slug,
        "slug": slug,
        "title": title,
        "artist_id": artist_id,
        "model": model,
        "release_type": release_type,
        "status": "draft",
        "release_date": None,
        "label": None,
        "publisher": None,
        "distributor": None,
        "upc": None,
        "catalog_number": None,
        "cover_image": f"site/public/assets/releases/{slug}/cover.jpg",
        "hero_image": None,
        "summary": None,
        "description": None,
        "credits": {
            "primary_artist": None,
            "songwriter": None,
            "lyrics": None,
            "producer": None,
            "mastering": None,
        },
        "links": {k: None for k in PLATFORM_KEYS},
        "seo": {
            "title": f"{title}",
            "description": f"{title} on Maricopa Records.",
        },
        "automation": {"allow_auto_publish": False},
    }
    if model == "song":
        skeleton["song"] = {
            "number": 1,
            "title": title,
            "slug": slug,
            "isrc": None,
            "duration": None,
            "explicit": False,
            "instrumental": False,
            "preview_audio": None,
            "lyrics_text": None,
            "lyrics_raw": None,
            "lyrics_source": None,
            "style": None,
            "links": {k: None for k in PLATFORM_KEYS},
            "hints": {},
        }
    else:
        skeleton["tracks"] = []
    return skeleton
