from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_MIGRATION_SOURCE = Path("/home/mrose/website-migration")
ARTIFACT_RELATIVE = Path("import-artifacts/maricoparecords")
WXR_RELATIVE = Path("Assets/maricoparecords.WordPress.2026-06-17.xml")
COMMERCE_SLUGS = {
    "cart",
    "checkout",
    "my-account",
    "account",
    "shop",
    "products",
    "product",
}
UNSUPPORTED_TYPES = {
    "cryout_serious_slide",
    "cryout-featured-blob",
    "nav_menu_item",
    "wp_block",
    "wp_global_styles",
    "wp_navigation",
    "custom_css",
    "wpcf7_contact_form",
}


def migration_inventory(
    repo: str | Path,
    source: str | Path = DEFAULT_MIGRATION_SOURCE,
    write_report: bool = True,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    source_paths = resolve_source(source)
    normalized = load_json(source_paths["normalized_wordpress_content"])
    capture = load_json(source_paths["capture_manifest"])
    posts = normalized["payload"]["posts"]
    pages = capture.get("pages", [])
    assets = capture.get("assets", [])

    classified_posts = [classify_post(post) for post in posts]
    normalized_routes = [normalize_route(page) for page in pages]
    artist_routes, release_routes = classify_artist_release_routes(normalized_routes)
    asset_records = [classify_asset(asset) for asset in assets]

    generated_at = now_utc()
    report = {
        "command": "migration-inventory",
        "status": "passed",
        "repo": str(root),
        "source": str(source_paths["source_root"]),
        "artifact_root": str(source_paths["artifact_root"]),
        "generated_at": generated_at,
        "source_files": {
            key: str(path) for key, path in source_paths.items() if key not in {"source_root", "artifact_root"}
        },
        "summary": summary(posts, pages, assets, classified_posts, normalized_routes, artist_routes, release_routes),
        "classifications": classified_posts,
        "routes": normalized_routes,
        "artist_routes": artist_routes,
        "release_routes": release_routes,
        "assets": asset_records,
        "exclusions": exclusion_summary(classified_posts),
        "notes": [
            "Inventory only; no content records or assets were written.",
            "WordPress WXR-normalized content is authoritative for post records.",
            "Captured pages and assets are supporting evidence for route and media coverage.",
            "Source files under /home/mrose/website-migration were not modified.",
        ],
    }
    if write_report:
        report["report_path"] = report_path(root, generated_at)
        write_json(root / report["report_path"], report)
    return report


def resolve_source(source: str | Path) -> dict[str, Path]:
    candidate = Path(source).expanduser().resolve()
    if (candidate / ARTIFACT_RELATIVE).is_dir():
        source_root = candidate
        artifact_root = candidate / ARTIFACT_RELATIVE
    elif (candidate / "defined-skills/raw/normalized-wordpress-content.json").is_file():
        artifact_root = candidate
        source_root = artifact_root.parents[1]
    else:
        raise FileNotFoundError(f"Could not find website migration artifacts under {candidate}")

    paths = {
        "source_root": source_root,
        "artifact_root": artifact_root,
        "wxr": source_root / WXR_RELATIVE,
        "import_report": artifact_root / "IMPORT_REPORT.md",
        "source_inventory": artifact_root / "defined-skills/raw/source-inventory.json",
        "normalized_wordpress_content": artifact_root
        / "defined-skills/raw/normalized-wordpress-content.json",
        "capture_manifest": artifact_root / "live-capture/capture-manifest.json",
    }
    missing = [str(path) for key, path in paths.items() if key not in {"source_root", "artifact_root"} and not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing migration source files: {', '.join(missing)}")
    return paths


def classify_post(post: dict[str, Any]) -> dict[str, Any]:
    post_type = post.get("type") or "unknown"
    slug = post.get("slug") or ""
    status = post.get("status")
    category = "unsupported"
    reason = "Unsupported WordPress implementation record."

    if post_type == "feedback":
        category = "excluded_feedback"
        reason = "Historical feedback/contact submission records are excluded."
    elif post_type == "product" or slug in COMMERCE_SLUGS:
        category = "excluded_commerce"
        reason = "WooCommerce, cart, checkout, account, and payment content is excluded."
    elif post_type == "attachment":
        category = "attachment"
        reason = "Attachment record; asset copy is handled by curated asset mapping."
    elif post_type == "post" and status == "publish":
        category = "blog_news_post"
        reason = "Published blog/news content is in v0.1.1 scope."
    elif post_type == "page" and status == "publish":
        category = "public_page"
        reason = "Published public page is in v0.1.1 scope."
    elif post_type in UNSUPPORTED_TYPES:
        category = "unsupported"
    elif status != "publish":
        category = "unsupported"
        reason = "Non-published source record is not rendered for staging."

    return {
        "id": post.get("id"),
        "type": post_type,
        "status": status,
        "slug": slug,
        "title": post.get("title"),
        "category": category,
        "reason": reason,
        "published_at": post.get("published_at"),
    }


def normalize_route(page: dict[str, Any]) -> dict[str, Any]:
    url = page.get("url") or ""
    parsed = urlparse(url)
    normalized_path = parsed.path or "/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    if normalized_path != "/" and not normalized_path.endswith("/"):
        normalized_path = f"{normalized_path}/"
    return {
        "url": url,
        "normalized_path": normalized_path,
        "capture_path": page.get("path"),
        "status": page.get("status"),
        "content_type": page.get("content_type"),
        "bytes": page.get("bytes"),
        "category": route_category(normalized_path),
    }


def route_category(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if any(part in COMMERCE_SLUGS for part in parts):
        return "excluded_commerce"
    if not parts:
        return "public_page"
    if parts[0] == "artists":
        if len(parts) == 2:
            return "artist"
        if len(parts) >= 3:
            return "release"
    if parts[0] in {"category", "tag"}:
        return "blog_news_post"
    return "public_page"


def classify_artist_release_routes(routes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    artists: dict[str, dict[str, Any]] = {}
    releases: dict[str, dict[str, Any]] = {}
    for route in routes:
        parts = [part for part in route["normalized_path"].split("/") if part]
        if len(parts) < 2 or parts[0] != "artists":
            continue
        artist_slug = parts[1]
        if len(parts) == 2:
            artists[artist_slug] = {
                "artist": artist_slug,
                "normalized_path": route["normalized_path"],
                "source_url": route["url"],
            }
        elif len(parts) >= 3:
            release_slug = parts[2]
            releases[f"{artist_slug}/{release_slug}"] = {
                "artist": artist_slug,
                "release": release_slug,
                "normalized_path": route["normalized_path"],
                "source_url": route["url"],
            }
    return sorted(artists.values(), key=lambda item: item["artist"]), sorted(
        releases.values(), key=lambda item: (item["artist"], item["release"])
    )


def classify_asset(asset: dict[str, Any]) -> dict[str, Any]:
    path = asset.get("path") or ""
    content_type = asset.get("content_type") or ""
    category = "unsupported_asset"
    if "woocommerce" in path:
        category = "excluded_commerce"
    elif content_type.startswith(("image/", "audio/", "video/")):
        category = "candidate_media"
    return {
        "url": asset.get("url"),
        "path": path,
        "content_type": content_type,
        "bytes": asset.get("bytes"),
        "sha256": asset.get("sha256"),
        "category": category,
    }


def summary(
    posts: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    classifications: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    artist_routes: list[dict[str, Any]],
    release_routes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "source_posts": len(posts),
        "captured_pages": len(pages),
        "captured_assets": len(assets),
        "post_types": dict(sorted(Counter(post.get("type") for post in posts).items())),
        "post_statuses": dict(sorted(Counter(post.get("status") for post in posts).items())),
        "categories": dict(sorted(Counter(item["category"] for item in classifications).items())),
        "route_categories": dict(sorted(Counter(route["category"] for route in routes).items())),
        "asset_categories": dict(sorted(Counter(classify_asset(asset)["category"] for asset in assets).items())),
        "normalized_routes": len(routes),
        "artist_routes": len(artist_routes),
        "release_routes": len(release_routes),
    }


def exclusion_summary(classifications: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "commerce": [
            item for item in classifications if item["category"] == "excluded_commerce"
        ],
        "feedback": [
            item for item in classifications if item["category"] == "excluded_feedback"
        ],
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def report_path(root: Path, generated_at: str) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    return str((root / "reports" / "migration" / f"{timestamp}-inventory.json").relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_migration_inventory(report: dict[str, Any]) -> str:
    summary_data = report["summary"]
    return "\n".join(
        [
            "Migration inventory completed",
            f"Source posts: {summary_data['source_posts']}",
            f"Captured pages: {summary_data['captured_pages']}",
            f"Captured assets: {summary_data['captured_assets']}",
            f"Artist routes: {summary_data['artist_routes']}",
            f"Release routes: {summary_data['release_routes']}",
            f"Report: {report['report_path']}",
        ]
    )
