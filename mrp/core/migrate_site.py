from __future__ import annotations

import json
import re
import unicodedata
from html import unescape
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from mrp.core.import_site import title_from_slug
from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE, migration_inventory


def migrate_site(
    repo: str | Path,
    source: str | Path = DEFAULT_MIGRATION_SOURCE,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "migrate-site",
        "repo": str(root),
        "source": str(Path(source).expanduser()),
        "generated_at": generated_at,
        "dry_run": dry_run,
    }

    if not dry_run:
        result.update(run_migration(root, source))
        result["report_path"] = write_migration_report(root, generated_at, result)
        return result

    try:
        inventory = migration_inventory(root, source, write_report=False)
    except FileNotFoundError as exc:
        result.update(
            {
                "status": "failed",
                "stage": "config",
                "message": str(exc),
            }
        )
        result["report_path"] = write_migration_report(root, generated_at, result)
        return result

    result.update(
        {
            "status": "planned",
            "stage": "dry_run",
            "summary": inventory["summary"],
            "source_files": inventory["source_files"],
            "planned_writes": planned_writes(inventory),
            "exclusions": {
                "commerce": len(inventory["exclusions"]["commerce"]),
                "feedback": len(inventory["exclusions"]["feedback"]),
            },
            "notes": [
                "Dry-run only; no content records or assets were written.",
                "Mutation mode is reserved for later v0.1.1 packets.",
            ],
        }
    )
    result["report_path"] = write_migration_report(root, generated_at, result)
    return result


def run_migration(root: Path, source: str | Path) -> dict[str, Any]:
    try:
        inventory = migration_inventory(root, source, write_report=False)
    except FileNotFoundError as exc:
        return {
            "status": "failed",
            "stage": "config",
            "message": str(exc),
        }

    posts_by_slug = posts_by_slug_from_inventory_source(inventory["source_files"]["normalized_wordpress_content"])
    created: list[str] = []
    skipped: list[dict[str, str]] = []
    review_needed: list[dict[str, str]] = []
    routes_by_slug = {slug_from_path(route["normalized_path"]): route for route in inventory["routes"]}

    for page in sorted(
        (item for item in inventory["classifications"] if item["category"] == "public_page"),
        key=lambda item: (item["slug"], item["id"]),
    ):
        source_slug = page["slug"]
        slug = safe_slug(source_slug)
        if not source_slug or not slug:
            continue
        path = root / "content" / "pages" / f"{slug}.yaml"
        post = posts_by_slug.get(source_slug, {})
        route = routes_by_slug.get(source_slug) or routes_by_slug.get(slug)
        record = page_record(slug, page, route, post)
        write_generated_yaml(root, path, record, created, skipped)

    for post in sorted(
        (item for item in inventory["classifications"] if item["category"] == "blog_news_post"),
        key=lambda item: item["slug"],
    ):
        path = root / "content" / "posts" / f"{post['slug']}.yaml"
        source_post = posts_by_slug.get(post["slug"], {})
        record = post_record(post, source_post)
        write_generated_yaml(root, path, record, created, skipped)

    for artist in inventory["artist_routes"]:
        path = root / "content" / "artists" / f"{artist['artist']}.yaml"
        record = artist_record(artist)
        write_generated_yaml(root, path, record, created, skipped)

    for release in inventory["release_routes"]:
        path = root / "content" / "releases" / f"{release['release']}.yaml"
        source_post = posts_by_slug.get(release["release"], {})
        record = release_record(release, source_post)
        write_generated_yaml(root, path, record, created, skipped)
        if not source_post:
            review_needed.append(
                {
                    "path": str(path.relative_to(root)),
                    "reason": "No matching WXR post found for captured release route.",
                }
            )

    redirects_path = root / "content" / "redirects.yaml"
    redirects = {
        "redirects": [
            {
                "source_path": source_path(route["url"]),
                "normalized_path": route["normalized_path"],
                "status": "normalized",
                "notes": "Generated from captured public URL.",
            }
            for route in inventory["routes"]
        ]
    }
    redirects_path.parent.mkdir(parents=True, exist_ok=True)
    redirects_path.write_text(yaml.safe_dump(redirects, sort_keys=False, allow_unicode=False))
    created.append(str(redirects_path.relative_to(root)))

    return {
        "status": "completed",
        "stage": "content_generation",
        "summary": inventory["summary"],
        "planned_writes": planned_writes(inventory),
        "created": sorted(created),
        "skipped": sorted(skipped, key=lambda item: item["path"]),
        "review_needed": sorted(review_needed, key=lambda item: item["path"]),
        "notes": [
            "Generated staging content records only; migrated media copy is reserved for MRP-105.",
            "Existing content records were not overwritten.",
        ],
    }


def planned_writes(inventory: dict[str, Any]) -> dict[str, Any]:
    categories = inventory["summary"]["categories"]
    asset_categories = inventory["summary"]["asset_categories"]
    return {
        "pages": categories.get("public_page", 0),
        "posts": categories.get("blog_news_post", 0),
        "artist_records": inventory["summary"]["artist_routes"],
        "release_records": inventory["summary"]["release_routes"],
        "assets": asset_categories.get("candidate_media", 0),
        "normalized_urls": inventory["summary"]["normalized_routes"],
    }


def posts_by_slug_from_inventory_source(path: str) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    posts = data["payload"]["posts"]
    return {post.get("slug"): post for post in posts if post.get("slug")}


def write_generated_yaml(
    root: Path,
    path: Path,
    record: dict[str, Any],
    created: list[str],
    skipped: list[dict[str, str]],
) -> None:
    if path.exists() or path.with_suffix(".json").exists():
        skipped.append(
            {
                "path": str(path.relative_to(root)),
                "reason": "Existing record was not overwritten.",
            }
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=False))
    created.append(str(path.relative_to(root)))


def page_record(
    slug: str,
    page: dict[str, Any],
    route: dict[str, Any] | None,
    post: dict[str, Any],
) -> dict[str, Any]:
    title = unescape(post.get("title") or page.get("title") or title_from_slug(slug))
    normalized_path = route["normalized_path"] if route else f"/{slug}/"
    return {
        "page": {
            "id": slug,
            "slug": slug,
            "title": title,
            "status": "draft",
            "normalized_path": normalized_path,
            "source_url": (route["url"] if route else f"https://www.maricoparecords.com/{slug}/"),
            "content_html": post.get("content") or "",
            "excerpt": post.get("excerpt") or None,
            "seo": {
                "title": title,
                "description": None,
            },
            "source": {
                "system": "wordpress",
                "id": str(post.get("id") or page.get("id") or slug),
                "type": post.get("type") or page.get("type"),
                "status": post.get("status") or page.get("status"),
                "captured_path": route.get("capture_path") if route else None,
            },
        }
    }


def post_record(post: dict[str, Any], source_post: dict[str, Any]) -> dict[str, Any]:
    categories = [
        term["name"]
        for term in source_post.get("terms", [])
        if term.get("taxonomy") == "category" and term.get("name")
    ]
    return {
        "post": {
            "id": post["slug"],
            "slug": post["slug"],
            "title": unescape(post.get("title") or title_from_slug(post["slug"])),
            "status": "draft",
            "normalized_path": f"/{post['slug']}/",
            "source_url": f"https://www.maricoparecords.com/{post['slug']}/",
            "published_at": post.get("published_at"),
            "content_html": source_post.get("content") or "",
            "excerpt": source_post.get("excerpt") or None,
            "categories": categories,
            "seo": {
                "title": unescape(post.get("title") or title_from_slug(post["slug"])),
                "description": None,
            },
            "source": {
                "system": "wordpress",
                "id": str(post["id"]),
                "type": post.get("type"),
                "status": post.get("status"),
                "captured_path": None,
            },
        }
    }


def artist_record(artist: dict[str, Any]) -> dict[str, Any]:
    return {
        "artist": {
            "id": artist["artist"],
            "name": title_from_slug(artist["artist"]),
            "sort_name": title_from_slug(artist["artist"]),
            "type": "project",
            "label": "Maricopa Records",
            "default_publisher": "Maricopa Publishing",
            "bio_short": "",
            "bio_long": "",
            "image": None,
            "links": {
                "website": artist["source_url"],
                "spotify": None,
                "apple_music": None,
                "youtube": None,
                "bandcamp": None,
                "instagram": None,
            },
            "visibility": "draft",
        }
    }


def release_record(release: dict[str, Any], source_post: dict[str, Any]) -> dict[str, Any]:
    title = unescape(source_post.get("title") or title_from_slug(release["release"]))
    return {
        "release": {
            "id": release["release"],
            "slug": release["release"],
            "title": title,
            "artist_id": release["artist"],
            "model": "song",
            "release_type": "single",
            "status": "draft",
            "release_date": date_part(source_post.get("published_at")),
            "label": "Maricopa Records",
            "publisher": "Maricopa Publishing",
            "upc": None,
            "catalog_number": None,
            "cover_image": f"assets/releases/{release['release']}/cover.jpg",
            "hero_image": None,
            "summary": source_post.get("excerpt") or "",
            "description": "",
            "credits": {
                "primary_artist": title_from_slug(release["artist"]),
                "songwriter": None,
                "producer": None,
                "mastering": None,
            },
            "links": {
                "spotify": None,
                "apple_music": None,
                "youtube_music": None,
                "bandcamp": None,
                "soundcloud": None,
                "landing_page": release["source_url"],
            },
            "seo": {
                "title": f"{title} by {title_from_slug(release['artist'])}",
                "description": f"{title} by {title_from_slug(release['artist'])} on Maricopa Records.",
            },
            "automation": {"allow_auto_publish": False},
            "song": {
                "number": None,
                "title": title,
                "slug": release["release"],
                "isrc": None,
                "duration": None,
                "explicit": False,
                "preview_audio": None,
                "lyrics_excerpt": None,
            },
        }
    }


def slug_from_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    return parts[-1] if parts else "home"


def safe_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def source_path(url: str) -> str:
    path = urlparse(url).path or "/"
    return path if path.startswith("/") else f"/{path}"


def date_part(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(" ", 1)[0]


def write_migration_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    suffix = "dry-run" if result.get("dry_run") else "content-generation"
    report_path = root / "reports" / "migration" / f"{timestamp}-{suffix}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_migrate_site(result: dict[str, Any]) -> str:
    lines = [
        f"Migrate-site {result['status']}",
        f"Report: {result['report_path']}",
    ]
    if result.get("planned_writes"):
        planned = result["planned_writes"]
        lines.extend(
            [
                f"Pages: {planned['pages']}",
                f"Posts: {planned['posts']}",
                f"Assets: {planned['assets']}",
            ]
        )
    if result.get("message"):
        lines.append(result["message"])
    return "\n".join(lines)
