from __future__ import annotations

import json
import re
import shutil
import uuid
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mrp.admin import db, nim
from mrp.admin import jobs as job_runner
from mrp.admin.deps import get_repo_root
from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.validate import validate_schema

router = APIRouter(prefix="/artists")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_SCHEMA_PATH = Path(__file__).parents[2] / "schemas" / "artist.schema.json"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_IDENTITY_ROOT = Path("assets/processed/identity")


class IdentityRefreshError(RuntimeError):
    pass


def _safe_slug(value: str, label: str) -> str:
    if not _SLUG_RE.fullmatch(value):
        raise IdentityRefreshError(f"Invalid {label}: {value!r}.")
    return value


def _artist_path(root: Path, artist_id: str) -> Path:
    return root / "content" / "artists" / f"{_safe_slug(artist_id, 'artist id')}.yaml"


def _load_artist(root: Path, artist_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = _artist_path(root, artist_id)
    if not path.is_file():
        raise IdentityRefreshError(f"Artist {artist_id!r} was not found.")
    data = load_structured_record(path)
    artist = data.get("artist") or {}
    return path, data, artist


def _member(artist: dict[str, Any], slug: str) -> dict[str, Any] | None:
    return next((m for m in artist.get("members") or [] if m.get("slug") == slug), None)


def _target_key(target_member: str | None) -> str:
    return f"member-{_safe_slug(target_member, 'member slug')}" if target_member else "artist"


def _job_target_member(job: dict[str, Any]) -> str | None:
    target = str(job.get("command") or "").rsplit("/", 1)[-1]
    return target.removeprefix("member-") if target.startswith("member-") else None


def _run_root(root: Path, artist_id: str, target_member: str | None, request_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise IdentityRefreshError("Invalid identity request id.")
    return root / _IDENTITY_ROOT / _safe_slug(artist_id, "artist id") / _target_key(target_member) / request_id


def _repo_relative_path(root: Path, value: str, label: str) -> Path:
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise IdentityRefreshError(f"{label} must be a repository-relative path.")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise IdentityRefreshError(f"{label} escapes the repository.") from exc
    if not candidate.is_file():
        raise IdentityRefreshError(f"{label} was not found: {value}.")
    if candidate.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise IdentityRefreshError(f"{label} is not a supported image: {value}.")
    return candidate


def _resolve_references(
    root: Path,
    artist: dict[str, Any],
    member_slugs: list[str],
    uploaded_references: list[str],
    target_member: str | None,
) -> tuple[list[Path], list[dict[str, Any]]]:
    references: list[Path] = []
    subjects: list[dict[str, Any]] = []

    if target_member:
        selected = _member(artist, _safe_slug(target_member, "member slug"))
        if selected is None:
            raise IdentityRefreshError(f"Member {target_member!r} was not found.")
        subjects = [selected]
    elif artist.get("type") == "band":
        seen: set[str] = set()
        for slug in member_slugs:
            slug = _safe_slug(slug, "member slug")
            if slug in seen:
                continue
            seen.add(slug)
            selected = _member(artist, slug)
            if selected is None:
                raise IdentityRefreshError(f"Member {slug!r} was not found.")
            subjects.append(selected)

        if not subjects and not uploaded_references:
            raise IdentityRefreshError("Select at least one band member with a reference image.")
    else:
        subjects = [artist]

    for subject in subjects:
        value = str(subject.get("reference_image") or "").strip()
        if not value:
            name = subject.get("name") or subject.get("slug") or artist.get("name") or "Subject"
            raise IdentityRefreshError(f"{name} does not have a reference image.")
        references.append(_repo_relative_path(root, value, "Reference image"))

    for value in uploaded_references:
        references.append(_repo_relative_path(root, value, "Uploaded reference"))

    if not references:
        raise IdentityRefreshError("Add at least one reference image before generating.")
    if len(references) > nim.MAX_IMAGE_REFERENCES:
        raise IdentityRefreshError(
            f"A generation can use at most {nim.MAX_IMAGE_REFERENCES} reference images.")
    return references, subjects


def assemble_identity_prompt(
    artist: dict[str, Any],
    subjects: list[dict[str, Any]],
    custom_prompt: str = "",
    target_member: str | None = None,
) -> str:
    artist_name = str(artist.get("name") or artist.get("id") or "the artist")
    custom_prompt = custom_prompt.strip()

    if target_member:
        subject = subjects[0]
        name = str(subject.get("name") or target_member)
        notes = str(subject.get("likeness_notes") or "").strip()
        opening = (
            f"Create a polished square public artist portrait of {name}, a member of {artist_name}. "
            "Maintain the person's facial identity and recognizable likeness from every reference image."
        )
        context = f" Likeness details: {notes}" if notes else ""
    elif artist.get("type") == "band":
        names = ", ".join(str(s.get("name") or s.get("slug")) for s in subjects)
        notes = "; ".join(
            f"{s.get('name') or s.get('slug')}: {str(s.get('likeness_notes') or '').strip()}"
            for s in subjects if str(s.get("likeness_notes") or "").strip()
        )
        opening = (
            f"Create a polished square group shot of {artist_name}: {names}. "
            "Maintain each person's distinct facial identity and recognizable likeness from the reference images."
        )
        context = f" Likeness details: {notes}" if notes else ""
    else:
        notes = str(artist.get("likeness_notes") or "").strip()
        opening = (
            f"Create a polished square public artist portrait of {artist_name}. "
            "Maintain the subject's facial identity and recognizable likeness from every reference image."
        )
        context = f" Likeness details: {notes}" if notes else ""

    direction = f" Creative direction: {custom_prompt}" if custom_prompt else ""
    return opening + context + direction + " No text, logos, borders, watermarks, or extra people."


async def _store_uploaded_references(
    root: Path,
    artist_id: str,
    target_member: str | None,
    request_id: str,
    uploads: list[Any],
) -> list[str]:
    stored: list[str] = []
    directory = _run_root(root, artist_id, target_member, request_id) / "references"
    for index, upload in enumerate(uploads, start=1):
        filename = str(getattr(upload, "filename", "") or "")
        if not filename:
            continue
        ext = Path(filename).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        if ext not in _IMAGE_EXTENSIONS:
            raise IdentityRefreshError(
                f"Unsupported reference image type: {ext or '(none)'}; use jpg, png, webp, or gif.")
        contents = await upload.read()
        if not contents:
            raise IdentityRefreshError(f"Reference upload {filename!r} is empty.")
        directory.mkdir(parents=True, exist_ok=True)
        dest = directory / f"upload-{index}{ext}"
        dest.write_bytes(contents)
        stored.append(dest.relative_to(root).as_posix())
    return stored


def run_identity_generation(
    root: str | Path,
    artist_id: str,
    member_slugs: list[str],
    prompt: str,
    *,
    count: int = 1,
    uploaded_references: list[str] | None = None,
    target_member: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    request_id = request_id or uuid.uuid4().hex
    _, _, artist = _load_artist(root, artist_id)
    references, subjects = _resolve_references(
        root, artist, member_slugs, uploaded_references or [], target_member)
    final_prompt = assemble_identity_prompt(artist, subjects, prompt, target_member)
    output_dir = _run_root(root, artist_id, target_member, request_id) / "candidates"
    try:
        generated = nim.generate_identity_image(
            repo=root,
            references=references,
            output_dir=output_dir,
            prompt=final_prompt,
            count=count,
        )
    except Exception:
        shutil.rmtree(output_dir.parent, ignore_errors=True)
        raise

    candidates = []
    for item in generated.get("candidates") or []:
        candidate = Path(str(item.get("file") or "")).resolve()
        try:
            rel = candidate.relative_to(root).as_posix()
            candidate.relative_to(output_dir.resolve())
        except ValueError as exc:
            raise IdentityRefreshError("Nim returned a candidate outside the identity staging area.") from exc
        candidates.append({**item, "file": rel})

    return {
        **generated,
        "artist_id": artist_id,
        "target_member": target_member,
        "member_slugs": [str(s.get("slug") or "") for s in subjects],
        "prompt": final_prompt,
        "references": len(references),
        "request_id": request_id,
        "candidates": candidates,
    }


def _candidate_path(
    root: Path,
    artist_id: str,
    value: str,
    target_member: str | None,
) -> Path:
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise IdentityRefreshError("Candidate path must be repository-relative.")
    candidate = (root / rel).resolve()
    base = (root / _IDENTITY_ROOT / _safe_slug(artist_id, "artist id") /
            _target_key(target_member)).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise IdentityRefreshError("Candidate path is outside this identity refresh target.") from exc
    if not candidate.is_file() or candidate.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise IdentityRefreshError("Identity candidate was not found or is not a supported image.")
    return candidate


def _cleanup_run(candidate: Path) -> None:
    # candidates/<file> -> <request-id>/; remove unselected siblings and uploads.
    run_dir = candidate.parent.parent
    shutil.rmtree(run_dir, ignore_errors=True)


def publish_identity_candidate(
    root: Path,
    artist_id: str,
    candidate_path: str,
    target_member: str | None = None,
) -> dict[str, str]:
    root = root.resolve()
    candidate = _candidate_path(root, artist_id, candidate_path, target_member)
    path, data, artist = _load_artist(root, artist_id)

    public_slug = artist_id
    target: dict[str, Any] = artist
    if target_member:
        target_member = _safe_slug(target_member, "member slug")
        selected = _member(artist, target_member)
        if selected is None:
            raise IdentityRefreshError(f"Member {target_member!r} was not found.")
        public_slug = target_member
        target = selected

    public_ext = ".jpg" if candidate.suffix.lower() == ".jpeg" else candidate.suffix.lower()
    public_rel = Path("site/public/assets/artists") / artist_id / f"{public_slug}{public_ext}"
    target["image"] = "/" + public_rel.relative_to("site/public").as_posix()
    data["artist"] = artist
    errors = validate_schema(path, data, _SCHEMA_PATH)
    if errors:
        detail = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors[:3])
        raise IdentityRefreshError(f"Artist validation failed: {detail}")

    generated_dir = root / "assets" / "artists" / artist_id / "generated"
    archive_name = candidate.name if not target_member else f"{target_member}-{candidate.name}"
    archive = generated_dir / archive_name
    public = root / public_rel
    generated_dir.mkdir(parents=True, exist_ok=True)
    public.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, archive)
    shutil.copy2(candidate, public)

    for ext in _IMAGE_EXTENSIONS:
        old = public.parent / f"{public_slug}{ext}"
        if old != public:
            old.unlink(missing_ok=True)

    path.write_text(serialize_structured_record(path, data), encoding="utf-8")
    _cleanup_run(candidate)
    return {
        "archive": archive.relative_to(root).as_posix(),
        "public": public.relative_to(root).as_posix(),
        "image": str(target["image"]),
    }


def discard_identity_candidate(
    root: Path,
    artist_id: str,
    candidate_path: str,
    target_member: str | None = None,
) -> None:
    candidate = _candidate_path(root.resolve(), artist_id, candidate_path, target_member)
    candidate.unlink()
    candidates_dir = candidate.parent
    if not any(candidates_dir.iterdir()):
        _cleanup_run(candidate)


def _refresh_url(artist_id: str, target_member: str | None = None) -> str:
    url = f"/artists/{artist_id}/refresh"
    return f"{url}?member={target_member}" if target_member else url


def _page_context(
    artist: dict[str, Any],
    target_member: str | None,
    flash: dict[str, str] | None = None,
) -> dict[str, Any]:
    selected = _member(artist, target_member) if target_member else None
    members = []
    for member in artist.get("members") or []:
        members.append({
            **member,
            "has_reference": bool(member.get("reference_image")),
            "selected": bool(member.get("reference_image") and member.get("status") != "former"),
        })
    return {
        "artist": artist,
        "members": members,
        "target_member": selected,
        "nim_connected": nim.connected(),
        "model_name": nim.DEFAULT_IMAGE_MODEL_NAME,
        "image_aspect": nim.DEFAULT_IMAGE_MODEL_ASPECT,
        "image_resolution": nim.DEFAULT_IMAGE_MODEL_RESOLUTION,
        "credits_per_image": nim.DEFAULT_IMAGE_MODEL_CREDITS,
        "max_candidates": nim.MAX_IMAGE_BATCH,
        "return_to": _refresh_url(str(artist.get("id")), target_member),
        "flash": flash,
    }


def _job_output(job: dict[str, Any]) -> Any:
    value = job.get("output")
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _review_context(root: Path, artist_id: str, job: dict[str, Any]) -> dict[str, Any]:
    output = _job_output(job)
    candidates = []
    if job.get("status") == "done" and isinstance(output, dict):
        target_member = output.get("target_member")
        for item in output.get("candidates") or []:
            try:
                candidate = _candidate_path(root, artist_id, str(item.get("file") or ""), target_member)
            except IdentityRefreshError:
                continue
            processed_root = (root / "assets" / "processed").resolve()
            candidates.append({
                **item,
                "file": candidate.relative_to(root).as_posix(),
                "url": "/processed/" + candidate.relative_to(processed_root).as_posix(),
            })
    target_member = (
        output.get("target_member") if isinstance(output, dict) and "target_member" in output
        else _job_target_member(job)
    )
    return {
        "job": job,
        "output": output,
        "candidates": candidates,
        "artist_id": artist_id,
        "target_member": target_member,
        "return_to": _refresh_url(artist_id, target_member),
    }


@router.get("/{artist_id}/refresh", response_class=HTMLResponse)
async def identity_page(
    request: Request,
    artist_id: str,
    member: str = "",
    published: str = "",
):
    root = get_repo_root()
    try:
        _, _, artist = _load_artist(root, artist_id)
        target_member = _safe_slug(member, "member slug") if member else None
        if target_member and _member(artist, target_member) is None:
            raise IdentityRefreshError(f"Member {target_member!r} was not found.")
    except IdentityRefreshError as exc:
        return HTMLResponse(escape(str(exc)), status_code=404)
    flash = {"cls": "ok", "text": f"Published {published}."} if published else None
    return _templates.TemplateResponse(
        request, "identity/page.html", _page_context(artist, target_member, flash))


@router.post("/{artist_id}/refresh/generate", response_class=HTMLResponse)
async def identity_generate(request: Request, artist_id: str):
    root = get_repo_root()
    form = await request.form()
    target_member = str(form.get("target_member") or "").strip() or None
    request_id = uuid.uuid4().hex
    try:
        _load_artist(root, artist_id)
        if target_member:
            _safe_slug(target_member, "member slug")
        count = int(str(form.get("count") or "1"))
        if not 1 <= count <= nim.MAX_IMAGE_BATCH:
            raise IdentityRefreshError(f"Candidate count must be 1-{nim.MAX_IMAGE_BATCH}.")
        member_slugs = [str(value) for value in form.getlist("member_slugs")]
        uploads = [u for u in form.getlist("reference_files") if getattr(u, "filename", "")]
        uploaded = await _store_uploaded_references(
            root, artist_id, target_member, request_id, uploads)
    except (IdentityRefreshError, ValueError) as exc:
        try:
            shutil.rmtree(_run_root(root, artist_id, target_member, request_id), ignore_errors=True)
        except IdentityRefreshError:
            pass
        return HTMLResponse(
            f'<div class="flash flash-error">{escape(str(exc))}</div>', status_code=422)

    command = f"identity/{artist_id}/{_target_key(target_member)}"
    job_id = job_runner.launch(
        command,
        run_identity_generation,
        str(root),
        artist_id,
        member_slugs,
        str(form.get("prompt") or ""),
        count=count,
        uploaded_references=uploaded,
        target_member=target_member,
        request_id=request_id,
    )
    job = db.get_job(job_id)
    return _templates.TemplateResponse(
        request, "identity/_review.html", _review_context(root, artist_id, job or {
            "id": job_id, "command": command, "status": "pending", "output": None,
        }))


@router.get("/{artist_id}/refresh/poll/{job_id}", response_class=HTMLResponse)
async def identity_poll(request: Request, artist_id: str, job_id: str):
    root = get_repo_root()
    job = db.get_job(job_id)
    expected = f"identity/{artist_id}/"
    if job is None or not str(job.get("command") or "").startswith(expected):
        return HTMLResponse('<div class="flash flash-error">Identity job not found.</div>', status_code=404)
    return _templates.TemplateResponse(
        request, "identity/_review.html", _review_context(root, artist_id, job))


@router.post("/{artist_id}/refresh/publish")
async def identity_publish(request: Request, artist_id: str):
    root = get_repo_root()
    form = await request.form()
    target_member = str(form.get("target_member") or "").strip() or None
    try:
        result = publish_identity_candidate(
            root, artist_id, str(form.get("candidate") or ""), target_member)
    except IdentityRefreshError as exc:
        return HTMLResponse(
            f'<div class="flash flash-error">{escape(str(exc))}</div>', status_code=422)
    label = target_member or artist_id
    return RedirectResponse(
        f"{_refresh_url(artist_id, target_member)}{'&' if target_member else '?'}published={label}",
        status_code=303,
        headers={"X-MRP-Identity-Archive": result["archive"]},
    )


@router.post("/{artist_id}/refresh/discard", response_class=HTMLResponse)
async def identity_discard(request: Request, artist_id: str):
    root = get_repo_root()
    form = await request.form()
    target_member = str(form.get("target_member") or "").strip() or None
    try:
        discard_identity_candidate(
            root, artist_id, str(form.get("candidate") or ""), target_member)
    except IdentityRefreshError as exc:
        return HTMLResponse(
            f'<div class="flash flash-error">{escape(str(exc))}</div>', status_code=422)
    return HTMLResponse('<div class="flash flash-ok">Candidate discarded.</div>')
