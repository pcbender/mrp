from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE, resolve_source
from mrp.core.wxr import classify_wxr_item, parse_wxr


RENDERABLE_CATEGORIES = {"artist_page", "release_page", "public_page", "blog_news_post"}
CLONE_KIND_BY_CATEGORY = {
    "artist_page": "artist_page",
    "release_page": "release_page",
    "public_page": "static_page",
    "blog_news_post": "blog_post",
}


def clone_site(
    repo: str | Path,
    source: str | Path = DEFAULT_MIGRATION_SOURCE,
    regenerate: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "clone-site",
        "repo": str(root),
        "source": str(Path(source).expanduser()),
        "generated_at": generated_at,
        "regenerate": regenerate,
    }

    try:
        result.update(run_clone_generation(root, source, regenerate))
    except (FileNotFoundError, ValueError) as exc:
        result.update(
            {
                "status": "failed",
                "stage": "config",
                "message": str(exc),
            }
        )
    result["report_path"] = write_report(root, generated_at, result)
    return result


def run_clone_generation(root: Path, source: str | Path, regenerate: bool) -> dict[str, Any]:
    source_paths = resolve_source(source)
    wxr = parse_wxr(source_paths["wxr"])
    capture = load_json(source_paths["capture_manifest"])
    routes = capture_routes(capture.get("pages", []))
    created: list[str] = []
    skipped: list[dict[str, str]] = []
    overwritten: list[str] = []
    review_needed: list[dict[str, str]] = []

    renderable = [
        (item, classification)
        for item in wxr["items"]
        for classification in [classify_wxr_item(item)]
        if classification["category"] in RENDERABLE_CATEGORIES
    ]

    for item, classification in sorted(renderable, key=lambda pair: canonical_path(pair[0])):
        record = clone_record(item, classification, routes)
        directory = root / "content" / "clone" / ("posts" if record["clone"]["kind"] == "blog_post" else "pages")
        path = directory / f"{record['clone']['id']}.yaml"
        write_clone_record(root, path, record, regenerate, created, skipped, overwritten)
        if not item["content_html"]:
            review_needed.append(
                {
                    "path": str(path.relative_to(root)),
                    "reason": "WXR record has empty content_html.",
                }
            )

    return {
        "status": "completed",
        "stage": "clone_record_generation",
        "source_files": {
            "wxr": str(source_paths["wxr"]),
            "capture_manifest": str(source_paths["capture_manifest"]),
        },
        "summary": {
            "wxr_items": len(wxr["items"]),
            "renderable_records": len(renderable),
            "pages": sum(1 for _, classification in renderable if classification["category"] != "blog_news_post"),
            "posts": sum(1 for _, classification in renderable if classification["category"] == "blog_news_post"),
            "created": len(created),
            "skipped": len(skipped),
            "overwritten": len(overwritten),
            "review_needed": len(review_needed),
        },
        "created": sorted(created),
        "skipped": sorted(skipped, key=lambda item: item["path"]),
        "overwritten": sorted(overwritten),
        "review_needed": sorted(review_needed, key=lambda item: item["path"]),
        "notes": [
            "Generated clone records from WordPress WXR content:encoded HTML.",
            "Existing clone records were preserved unless --regenerate was supplied.",
        ],
    }


def clone_record(
    item: dict[str, Any],
    classification: dict[str, Any],
    routes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    path = canonical_path(item)
    route = routes.get(path)
    aliases = aliases_for_path(path, routes)
    title = unescape(item["title"] or item["slug"] or path.strip("/") or "Home")
    return {
        "clone": {
            "id": clone_id(path, item),
            "kind": CLONE_KIND_BY_CATEGORY[classification["category"]],
            "title": title,
            "status": "review",
            "route": {
                "canonical_path": path,
                "aliases": aliases,
            },
            "source": {
                "system": "wordpress",
                "id": item["id"],
                "post_type": item["post_type"],
                "post_status": item["status"],
                "slug": item["slug"],
                "link": item["link"],
                "guid": item["guid"]["value"] or None,
                "captured_path": route["capture_path"] if route else None,
            },
            "content_html": item["content_html"],
            "excerpt": item["excerpt"] or None,
            "seo": {
                "title": title,
                "description": item["excerpt"] or None,
            },
            "assets": [],
            "notes": [
                "Generated from WordPress WXR content:encoded.",
            ],
        }
    }


def capture_routes(pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for page in pages:
        path = normalize_path(urlparse(page.get("url") or "").path or "/")
        routes.setdefault(
            path,
            {
                "url": page.get("url"),
                "normalized_path": path,
                "capture_path": page.get("path"),
            },
        )
    return routes


def aliases_for_path(path: str, routes: dict[str, dict[str, Any]]) -> list[str]:
    aliases = []
    if path != "/":
        aliases.append(path.rstrip("/"))
    for route_path in sorted(routes):
        if route_path.lower() == path.lower() and route_path != path:
            aliases.append(route_path)
            if route_path != "/":
                aliases.append(route_path.rstrip("/"))
    return sorted(set(aliases))


def canonical_path(item: dict[str, Any]) -> str:
    parsed_path = urlparse(item["link"]).path
    if parsed_path:
        return normalize_path(parsed_path)
    if item["slug"]:
        return normalize_path(f"/{item['slug']}/")
    return "/"


def normalize_path(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    if path != "/" and not path.endswith("/"):
        path = f"{path}/"
    return path


def clone_id(path: str, item: dict[str, Any]) -> str:
    if path == "/":
        return "home"
    slug = "-".join(part for part in path.split("/") if part)
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    return slug or item["slug"] or str(item["id"])


def write_clone_record(
    root: Path,
    path: Path,
    record: dict[str, Any],
    regenerate: bool,
    created: list[str],
    skipped: list[dict[str, str]],
    overwritten: list[str],
) -> None:
    relative = str(path.relative_to(root))
    if path.exists() and not regenerate:
        skipped.append({"path": relative, "reason": "Existing clone record was not overwritten."})
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    path.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=False))
    if existed:
        overwritten.append(relative)
    else:
        created.append(relative)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    path = root / "reports" / "migration" / f"{timestamp}-clone-site.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_clone_site(report: dict[str, Any]) -> str:
    if report["status"] == "failed":
        return "\n".join(
            [
                "Clone generation failed",
                f"Stage: {report['stage']}",
                f"Message: {report['message']}",
                f"Report: {report['report_path']}",
            ]
        )
    summary = report["summary"]
    return "\n".join(
        [
            "Clone generation completed",
            f"Renderable records: {summary['renderable_records']}",
            f"Pages: {summary['pages']}",
            f"Posts: {summary['posts']}",
            f"Created: {summary['created']}",
            f"Skipped: {summary['skipped']}",
            f"Overwritten: {summary['overwritten']}",
            f"Review needed: {summary['review_needed']}",
            f"Report: {report['report_path']}",
        ]
    )
