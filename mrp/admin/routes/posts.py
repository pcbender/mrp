from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from mrp.admin.deps import get_repo_root
from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.release import slugify
from mrp.core.validate import validate_schema

router = APIRouter(prefix="/posts")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_SCHEMA_PATH = Path(__file__).parents[2] / "schemas" / "post.schema.json"

POST_STATUSES = ["draft", "review", "ready", "archived"]


def _post_path(root: Path, slug: str) -> Path:
    return root / "content" / "posts" / f"{slug}.yaml"


def _form_context(post: dict[str, Any], flash: dict[str, str] | None = None,
                  errors: list | None = None) -> dict[str, Any]:
    return {
        "post": post,
        "statuses": POST_STATUSES,
        "categories_text": ", ".join(post.get("categories") or []),
        "flash": flash,
        "errors": errors or [],
    }


@router.get("", response_class=HTMLResponse)
async def posts_list(request: Request):
    root = get_repo_root()
    rows = []
    for path in sorted((root / "content" / "posts").glob("*.yaml")):
        try:
            post = load_structured_record(path).get("post") or {}
        except Exception:
            continue
        rows.append({
            "slug": post.get("slug", path.stem),
            "title": post.get("title", path.stem),
            "status": post.get("status", ""),
            "published_at": str(post.get("published_at") or "")[:10],
            "path": post.get("normalized_path", ""),
            "source": (post.get("source") or {}).get("system", ""),
        })
    rows.sort(key=lambda r: r["published_at"], reverse=True)
    return _templates.TemplateResponse(request, "posts/list.html", {"rows": rows})


@router.get("/new", response_class=HTMLResponse)
async def post_new(request: Request):
    return _templates.TemplateResponse(request, "posts/new.html", {})


@router.post("", response_class=HTMLResponse)
async def post_create(request: Request, title: str = Form(...)):
    root = get_repo_root()
    if not title.strip():
        return HTMLResponse('<div class="flash flash-error">Title is required.</div>', status_code=400)
    slug = slugify(title)
    path = _post_path(root, slug)
    if path.exists():
        return HTMLResponse(
            f'<div class="flash flash-error">A post with slug <code>{slug}</code> already exists.</div>',
            status_code=409,
        )
    record = {
        "post": {
            "id": slug,
            "slug": slug,
            "title": title.strip(),
            "status": "draft",
            "normalized_path": f"/{slug}/",
            "source_url": None,
            "published_at": None,
            "content_html": "",
            "excerpt": None,
            "categories": [],
            "seo": {"title": title.strip(), "description": None},
            "source": {"system": "admin", "id": slug, "type": "post", "status": "draft", "captured_path": None},
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_structured_record(path, record))
    return RedirectResponse(url=f"/posts/{slug}", status_code=303)


@router.get("/{slug}", response_class=HTMLResponse)
async def post_edit(request: Request, slug: str):
    root = get_repo_root()
    path = _post_path(root, slug)
    if not path.exists():
        return HTMLResponse(f"Post <b>{slug}</b> not found.", status_code=404)
    post = load_structured_record(path).get("post") or {}
    return _templates.TemplateResponse(request, "posts/form.html", _form_context(post))


@router.post("/{slug}", response_class=HTMLResponse)
async def post_save(request: Request, slug: str):
    root = get_repo_root()
    path = _post_path(root, slug)
    if not path.exists():
        return HTMLResponse(f"Post <b>{slug}</b> not found.", status_code=404)
    form = await request.form()

    data = load_structured_record(path)
    post = data.get("post") or {}
    post["title"] = str(form.get("title") or "").strip() or post.get("title") or slug
    status = str(form.get("status") or "draft")
    post["status"] = status if status in POST_STATUSES else "draft"
    post["published_at"] = str(form.get("published_at") or "").strip() or None
    post["excerpt"] = str(form.get("excerpt") or "").strip() or None
    post["content_html"] = str(form.get("content_html") or "")
    post["categories"] = [c.strip() for c in str(form.get("categories") or "").split(",") if c.strip()]
    seo = dict(post.get("seo") or {})
    seo["title"] = str(form.get("seo_title") or "").strip() or None
    seo["description"] = str(form.get("seo_description") or "").strip() or None
    post["seo"] = seo
    data["post"] = post

    errors = validate_schema(path, data, _SCHEMA_PATH)
    if errors:
        context = _form_context(
            post,
            flash={"cls": "error", "text": "Not saved — the record failed schema validation."},
            errors=errors,
        )
        return _templates.TemplateResponse(request, "posts/form.html", context, status_code=422)

    path.write_text(serialize_structured_record(path, data))
    context = _form_context(post, flash={"cls": "ok", "text": f"Saved {slug}."})
    return _templates.TemplateResponse(request, "posts/form.html", context)


@router.post("/{slug}/delete", response_class=HTMLResponse)
async def post_delete(request: Request, slug: str):
    root = get_repo_root()
    path = _post_path(root, slug)
    if not path.exists():
        return HTMLResponse(f"Post <b>{slug}</b> not found.", status_code=404)
    path.unlink()
    return RedirectResponse(url="/posts", status_code=303)
