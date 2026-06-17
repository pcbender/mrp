from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

from mrp.core.migration_inventory import COMMERCE_SLUGS, DEFAULT_MIGRATION_SOURCE, resolve_source


NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "excerpt": "http://wordpress.org/export/1.2/excerpt/",
    "wp": "http://wordpress.org/export/1.2/",
}

UNSUPPORTED_TYPES = {
    "cryout_serious_slide",
    "cryout-featured-blob",
    "custom_css",
    "jetpack-portfolio",
    "portfolio",
    "wp_block",
    "wp_global_styles",
    "wp_navigation",
    "wpcf7_contact_form",
}


def wxr_inventory(
    repo: str | Path,
    source: str | Path = DEFAULT_MIGRATION_SOURCE,
    write_report: bool = True,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    try:
        source_paths = resolve_source(source)
        parsed = parse_wxr(source_paths["wxr"])
        capture = load_json(source_paths["capture_manifest"])
    except (FileNotFoundError, ValueError, ElementTree.ParseError) as exc:
        report = {
            "command": "wxr-inventory",
            "status": "failed",
            "stage": "config",
            "repo": str(root),
            "source": str(Path(source).expanduser()),
            "generated_at": generated_at,
            "message": str(exc),
        }
        if write_report:
            report["report_path"] = report_path(root, generated_at)
            write_json(root / report["report_path"], report)
        return report
    pages = capture.get("pages", [])
    assets = capture.get("assets", [])
    classified_items = [classify_wxr_item(item) for item in parsed["items"]]
    routes = [normalize_capture_route(page) for page in pages]

    report = {
        "command": "wxr-inventory",
        "status": "passed",
        "repo": str(root),
        "source": str(source_paths["source_root"]),
        "artifact_root": str(source_paths["artifact_root"]),
        "generated_at": generated_at,
        "source_files": {
            key: str(path) for key, path in source_paths.items() if key not in {"source_root", "artifact_root"}
        },
        "summary": inventory_summary(parsed["items"], classified_items, routes, assets),
        "channel": parsed["channel"],
        "classifications": classified_items,
        "routes": routes,
        "exclusions": exclusion_summary(classified_items),
        "content_checks": {
            "pcbender_mystique": any(
                item["slug"] == "pcbender" and "mystique" in item["content_html"]
                for item in parsed["items"]
            ),
        },
        "notes": [
            "Inventory only; no content records or assets were written.",
            "WordPress WXR content:encoded values are parsed directly and kept as raw HTML text.",
            "Captured pages and assets are supporting evidence for route and media coverage.",
            "Source files under /home/mrose/website-migration were not modified.",
        ],
    }
    if write_report:
        report["report_path"] = report_path(root, generated_at)
        write_json(root / report["report_path"], report)
    return report


def parse_wxr(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    root = ElementTree.parse(source).getroot()
    channel = root.find("channel")
    if channel is None:
        raise ValueError(f"WXR file does not contain an RSS channel: {source}")

    items = [parse_item(item) for item in channel.findall("item")]
    return {
        "source_file": str(source),
        "channel": {
            "title": text(channel, "title"),
            "link": text(channel, "link"),
            "description": text(channel, "description"),
            "wxr_version": text(channel, "wp:wxr_version"),
            "base_site_url": text(channel, "wp:base_site_url"),
            "base_blog_url": text(channel, "wp:base_blog_url"),
        },
        "items": items,
        "summary": {
            "items": len(items),
            "post_types": dict(sorted(Counter(item["post_type"] for item in items).items())),
            "post_statuses": dict(sorted(Counter(item["status"] for item in items).items())),
            "items_with_content": sum(1 for item in items if item["content_html"]),
            "attachments": sum(1 for item in items if item["attachment_url"]),
        },
    }


def parse_item(item: ElementTree.Element) -> dict[str, Any]:
    guid_el = item.find("guid")
    terms = [
        {
            "domain": term.get("domain") or "",
            "nicename": term.get("nicename") or "",
            "name": term.text or "",
        }
        for term in item.findall("category")
    ]
    postmeta = [
        {
            "key": text(meta, "wp:meta_key"),
            "value": text(meta, "wp:meta_value"),
        }
        for meta in item.findall("wp:postmeta", NS)
    ]
    return {
        "id": text(item, "wp:post_id"),
        "title": text(item, "title"),
        "link": text(item, "link"),
        "guid": {
            "value": guid_el.text if guid_el is not None and guid_el.text else "",
            "is_permalink": (guid_el.get("isPermaLink") if guid_el is not None else "") == "true",
        },
        "creator": text(item, "dc:creator"),
        "pub_date": text(item, "pubDate"),
        "post_date": text(item, "wp:post_date"),
        "post_date_gmt": text(item, "wp:post_date_gmt"),
        "modified": text(item, "wp:post_modified"),
        "modified_gmt": text(item, "wp:post_modified_gmt"),
        "post_type": text(item, "wp:post_type") or "unknown",
        "status": text(item, "wp:status"),
        "slug": text(item, "wp:post_name"),
        "parent_id": text(item, "wp:post_parent"),
        "menu_order": integer_text(item, "wp:menu_order"),
        "content_html": text(item, "content:encoded"),
        "excerpt": text(item, "excerpt:encoded"),
        "attachment_url": text(item, "wp:attachment_url"),
        "terms": terms,
        "postmeta": postmeta,
    }


def classify_wxr_item(item: dict[str, Any]) -> dict[str, Any]:
    post_type = item["post_type"]
    status = item["status"]
    slug = item["slug"]
    category = "unsupported"
    reason = "Unsupported WordPress implementation record."

    if post_type == "feedback":
        category = "excluded_feedback"
        reason = "Historical feedback/contact submission records are excluded."
    elif post_type == "product" or slug in COMMERCE_SLUGS:
        category = "excluded_commerce"
        reason = "WooCommerce, cart, checkout, account, and payment content is excluded."
    elif post_type == "nav_menu_item":
        category = "menu_item"
        reason = "Navigation menu record; rendered navigation will be rebuilt from clone routes."
    elif post_type == "attachment":
        category = "attachment"
        reason = "Attachment record; asset copy is handled from the captured asset mirror."
    elif post_type == "post" and status == "publish":
        category = "blog_news_post"
        reason = "Published blog/news content is in clone scope."
    elif post_type == "page" and status == "publish":
        category = public_page_category(item["link"])
        reason = "Published public page is in clone scope."
    elif post_type in UNSUPPORTED_TYPES:
        category = "unsupported"
    elif status != "publish":
        category = "unsupported"
        reason = "Non-published source record is not rendered for staging."

    return {
        "id": item["id"],
        "type": post_type,
        "status": status,
        "slug": slug,
        "title": item["title"],
        "category": category,
        "reason": reason,
        "link": item["link"],
        "content_bytes": len(item["content_html"].encode()),
        "has_content": bool(item["content_html"]),
        "attachment_url": item["attachment_url"] or None,
    }


def public_page_category(link: str) -> str:
    parts = route_parts(link)
    if any(part in COMMERCE_SLUGS for part in parts):
        return "excluded_commerce"
    if len(parts) == 2 and parts[0] == "artists":
        return "artist_page"
    if len(parts) >= 3 and parts[0] == "artists":
        return "release_page"
    return "public_page"


def normalize_capture_route(page: dict[str, Any]) -> dict[str, Any]:
    path = urlparse(page.get("url") or "").path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if path != "/" and not path.endswith("/"):
        path = f"{path}/"
    return {
        "url": page.get("url"),
        "normalized_path": path,
        "capture_path": page.get("path"),
        "status": page.get("status"),
        "content_type": page.get("content_type"),
        "bytes": page.get("bytes"),
    }


def route_parts(url: str) -> list[str]:
    return [part for part in urlparse(url).path.split("/") if part]


def inventory_summary(
    items: list[dict[str, Any]],
    classifications: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "wxr_items": len(items),
        "captured_pages": len(routes),
        "captured_assets": len(assets),
        "post_types": dict(sorted(Counter(item["post_type"] for item in items).items())),
        "post_statuses": dict(sorted(Counter(item["status"] for item in items).items())),
        "categories": dict(sorted(Counter(item["category"] for item in classifications).items())),
        "content_records": sum(1 for item in items if item["content_html"]),
        "captured_routes": len(routes),
    }


def exclusion_summary(classifications: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "commerce": [item for item in classifications if item["category"] == "excluded_commerce"],
        "feedback": [item for item in classifications if item["category"] == "excluded_feedback"],
    }


def text(element: ElementTree.Element, path: str, default: str = "") -> str:
    found = element.find(path, NS)
    if found is None or found.text is None:
        return default
    return found.text


def integer_text(element: ElementTree.Element, path: str) -> int:
    value = text(element, path)
    try:
        return int(value)
    except ValueError:
        return 0


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def report_path(root: Path, generated_at: str) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    return str((root / "reports" / "migration" / f"{timestamp}-wxr-inventory.json").relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_wxr_inventory(report: dict[str, Any]) -> str:
    if report["status"] == "failed":
        return "\n".join(
            [
                "WXR inventory failed",
                f"Stage: {report['stage']}",
                f"Message: {report['message']}",
                f"Report: {report['report_path']}",
            ]
        )
    summary = report["summary"]
    return "\n".join(
        [
            "WXR inventory completed",
            f"WXR items: {summary['wxr_items']}",
            f"Captured pages: {summary['captured_pages']}",
            f"Captured assets: {summary['captured_assets']}",
            f"Content records: {summary['content_records']}",
            f"PCBender mystique check: {report['content_checks']['pcbender_mystique']}",
            f"Report: {report['report_path']}",
        ]
    )
