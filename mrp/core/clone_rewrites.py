from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from posixpath import normpath
from typing import Any
from urllib.parse import unquote, urlparse

import yaml


LOCAL_HOSTS = {"maricoparecords.com", "www.maricoparecords.com"}
STATIC_ROUTES = {"/", "/about-us/", "/artists/", "/contact/", "/posts/", "/releases/"}
URL_ATTRIBUTE_RE = re.compile(
    r"""\b(?:href|src|poster|action|data-src|data-srcset|data-bg|data-background|data-url|xlink:href)=["']([^"']*)["']""",
    re.IGNORECASE,
)
CSS_URL_RE = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""", re.IGNORECASE)
LOCAL_URL_RE = re.compile(
    r"""(?:https?:)?//(?:www\.)?maricoparecords\.com/[^\s"'<>)\\]+|/(?:wp-content|wp-includes)/[^\s"'<>)\\]+"""
)


def clone_rewrites(repo: str | Path) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "clone-rewrites",
        "repo": str(root),
        "generated_at": generated_at,
    }
    result.update(run_clone_rewrite_review(root))
    result["report_path"] = write_report(root, generated_at, result)
    return result


def run_clone_rewrite_review(root: Path) -> dict[str, Any]:
    routes = route_map(root)
    records = clone_records(root)
    asset_paths = mirrored_asset_paths(root)
    unresolved_routes: dict[tuple[str, str], dict[str, Any]] = {}
    missing_assets: dict[tuple[str, str], dict[str, Any]] = {}
    local_references = 0
    wordpress_asset_references = 0
    external_references = 0

    for record in records:
        references = collect_url_references(record["content_html"])
        for raw in references:
            for reference in split_reference(raw):
                parsed = parse_reference(reference)
                if parsed is None:
                    continue
                if parsed["is_external"]:
                    external_references += 1
                    continue
                local_references += 1
                if parsed["asset_path"]:
                    wordpress_asset_references += 1
                    local_path = f"site/public/assets/wp{parsed['asset_path']}"
                    if local_path not in asset_paths:
                        add_review_item(
                            missing_assets,
                            record,
                            reference,
                            local_path,
                            "Referenced WordPress asset is not mirrored under site/public/assets/wp/.",
                        )
                    continue
                if parsed["route_path"] not in routes:
                    add_review_item(
                        unresolved_routes,
                        record,
                        reference,
                        parsed["route_path"],
                        "Local URL does not match a generated static clone route.",
                    )

    head_missing_assets = review_head_dependencies(root, asset_paths)
    for item in head_missing_assets:
        key = (item["source"], item["url"])
        missing_assets.setdefault(key, item)

    return {
        "status": "completed",
        "stage": "clone_rewrite_review",
        "summary": {
            "clone_records": len(records),
            "local_references": local_references,
            "wordpress_asset_references": wordpress_asset_references,
            "external_references_preserved": external_references,
            "unresolved_local_urls": len(unresolved_routes),
            "missing_assets": len(missing_assets),
            "known_routes": len(routes),
            "mirrored_assets": len(asset_paths),
        },
        "unresolved_local_urls": sorted(unresolved_routes.values(), key=lambda item: (item["source"], item["url"])),
        "missing_assets": sorted(missing_assets.values(), key=lambda item: (item["source"], item["url"])),
        "notes": [
            "WordPress-local route and asset references are reviewed for static hosting.",
            "External provider links are counted but intentionally preserved.",
        ],
    }


def clone_records(root: Path) -> list[dict[str, Any]]:
    records = []
    for directory in (root / "content" / "clone" / "pages", root / "content" / "clone" / "posts"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text()) or {}
            clone = data.get("clone") or {}
            records.append(
                {
                    "source": str(path.relative_to(root)),
                    "title": clone.get("title") or clone.get("id") or path.stem,
                    "canonical_path": normalize_path((clone.get("route") or {}).get("canonical_path") or "/"),
                    "content_html": clone.get("content_html") or "",
                }
            )
    return records


def route_map(root: Path) -> set[str]:
    routes = set(STATIC_ROUTES)
    for directory, key, path_builder in (
        (root / "content" / "artists", "artist", lambda item: f"/artists/{item.get('id')}/"),
        (root / "content" / "releases", "release", lambda item: f"/releases/{item.get('slug')}/"),
        (root / "content" / "pages", "page", lambda item: item.get("normalized_path") or f"/{item.get('slug')}/"),
        (root / "content" / "posts", "post", lambda item: item.get("normalized_path") or f"/{item.get('slug')}/"),
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.json")):
            item = load_record(path).get(key) or {}
            if item:
                routes.add(normalize_path(path_builder(item)))

    for record in clone_records(root):
        routes.add(record["canonical_path"])
        path = root / record["source"]
        data = yaml.safe_load(path.read_text()) or {}
        route = (data.get("clone") or {}).get("route") or {}
        for alias in route.get("aliases") or []:
            routes.add(normalize_path(alias))

    redirects_path = root / "content" / "redirects.yaml"
    if redirects_path.is_file():
        redirects = (yaml.safe_load(redirects_path.read_text()) or {}).get("redirects") or []
        for redirect in redirects:
            if redirect.get("source_path"):
                routes.add(normalize_path(redirect["source_path"]))
            if redirect.get("target_path"):
                routes.add(normalize_path(redirect["target_path"]))
    return routes


def load_record(path: Path) -> dict[str, Any]:
    text = path.read_text()
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text) or {}


def mirrored_asset_paths(root: Path) -> set[str]:
    paths = set()
    manifest_path = root / "content" / "clone" / "assets" / "manifest.yaml"
    if manifest_path.is_file():
        for asset in (yaml.safe_load(manifest_path.read_text()) or {}).get("clone_assets") or []:
            if asset.get("status") == "mirrored" and asset.get("local_path"):
                paths.add(asset["local_path"])
    asset_root = root / "site" / "public" / "assets" / "wp"
    if asset_root.is_dir():
        for path in asset_root.rglob("*"):
            if path.is_file():
                paths.add(str(path.relative_to(root)))
    return paths


def collect_url_references(html: str) -> list[str]:
    references: list[str] = []
    references.extend(URL_ATTRIBUTE_RE.findall(html))
    references.extend(CSS_URL_RE.findall(html))
    references.extend(LOCAL_URL_RE.findall(html))
    return references


def split_reference(raw: str) -> list[str]:
    value = unescape(raw).strip().strip("\"'").rstrip(".,")
    if not value:
        return []
    if "," in value and " " in value:
        return [part.split()[0] for part in value.split(",") if part.strip()]
    return [value]


def parse_reference(value: str) -> dict[str, Any] | None:
    value = unescape(value).strip().strip("\"'")
    if not value or value.startswith("#") or re.match(r"^(?:mailto|tel|sms|javascript|data|blob):", value, re.I):
        return None
    if value.startswith("//"):
        value = f"https:{value}"
    try:
        parsed = urlparse(value if re.match(r"^[a-z][a-z0-9+.-]*:", value, re.I) else f"https://www.maricoparecords.com{value}")
    except ValueError:
        return None
    hostname = (parsed.hostname or "www.maricoparecords.com").lower()
    if hostname not in LOCAL_HOSTS:
        return {"is_external": True, "asset_path": None, "route_path": None}
    path = normalize_url_path(parsed.path or "/")
    asset_path = path if path.startswith("/wp-content/") or path.startswith("/wp-includes/") else None
    return {"is_external": False, "asset_path": asset_path, "route_path": normalize_path(path)}


def add_review_item(
    items: dict[tuple[str, str], dict[str, Any]],
    record: dict[str, Any],
    url: str,
    target: str,
    reason: str,
) -> None:
    items.setdefault(
        (record["source"], url),
        {
            "source": record["source"],
            "canonical_path": record["canonical_path"],
            "title": record["title"],
            "url": url,
            "target": target,
            "reason": reason,
        },
    )


def review_head_dependencies(root: Path, asset_paths: set[str]) -> list[dict[str, Any]]:
    manifest_path = root / "content" / "clone" / "head-manifest.yaml"
    if not manifest_path.is_file():
        return []
    manifest = (yaml.safe_load(manifest_path.read_text()) or {}).get("clone_head") or {}
    dependencies = []
    shared = manifest.get("shared") or {}
    for key in ("stylesheets", "scripts", "preloads"):
        dependencies.extend((f"content/clone/head-manifest.yaml:shared.{key}", dependency_url(item)) for item in shared.get(key) or [])
    dependencies.extend(
        (f"content/clone/head-manifest.yaml:shared.inline_styles", reference)
        for item in shared.get("inline_styles") or []
        for reference in collect_url_references(item.get("content") or "")
    )
    for page in manifest.get("pages") or []:
        for key in ("stylesheets", "scripts", "preloads"):
            dependencies.extend(
                (f"content/clone/head-manifest.yaml:{page.get('canonical_path')}.{key}", dependency_url(item))
                for item in page.get(key) or []
            )
        dependencies.extend(
            (f"content/clone/head-manifest.yaml:{page.get('canonical_path')}.inline_styles", reference)
            for item in page.get("inline_styles") or []
            for reference in collect_url_references(item.get("content") or "")
        )
    missing = []
    for source, url in dependencies:
        parsed = parse_reference(url)
        if not parsed or parsed["is_external"] or not parsed["asset_path"]:
            continue
        local_path = f"site/public/assets/wp{parsed['asset_path']}"
        if local_path not in asset_paths:
            missing.append(
                {
                    "source": source,
                    "canonical_path": None,
                    "title": "Clone head dependency",
                    "url": url,
                    "target": local_path,
                    "reason": "Referenced WordPress head asset is not mirrored under site/public/assets/wp/.",
                }
            )
    return missing


def dependency_url(item: dict[str, Any]) -> str:
    return item.get("url") or item.get("href") or item.get("src") or item.get("local_path") or ""


def normalize_path(path: str) -> str:
    value = str(path or "")
    if not value.startswith("/"):
        value = f"/{value}"
    if value != "/" and not value.endswith("/"):
        value = f"{value}/"
    return value


def normalize_url_path(path: str) -> str:
    normalized = normpath(unquote(path))
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def write_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    path = root / "reports" / "migration" / f"{timestamp}-clone-rewrites.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_clone_rewrites(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            "Clone URL rewrite review completed",
            f"Clone records: {summary['clone_records']}",
            f"Local references: {summary['local_references']}",
            f"WordPress asset references: {summary['wordpress_asset_references']}",
            f"External references preserved: {summary['external_references_preserved']}",
            f"Unresolved local URLs: {summary['unresolved_local_urls']}",
            f"Missing assets: {summary['missing_assets']}",
            f"Report: {report['report_path']}",
        ]
    )
