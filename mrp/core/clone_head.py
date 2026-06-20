from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

import yaml

from mrp.core.clone_assets import wordpress_relative_path
from mrp.core.clone_site import normalize_path
from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE, resolve_source


PAGE_ROOT_RELATIVE = Path("live-capture/raw/pages/www.maricoparecords.com")
MANIFEST_PATH = Path("content/clone/head-manifest.yaml")
SUPPORTED_LINK_RELS = {"stylesheet", "preload", "modulepreload", "preconnect", "dns-prefetch"}
EXCLUDED_EXTERNAL_HOSTS = {"www.google-analytics.com", "www.googletagmanager.com", "stats.wp.com"}


def clone_head(
    repo: str | Path,
    source: str | Path = DEFAULT_MIGRATION_SOURCE,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "clone-head",
        "repo": str(root),
        "source": str(Path(source).expanduser()),
        "generated_at": generated_at,
    }
    try:
        result.update(run_head_extraction(root, source))
    except FileNotFoundError as exc:
        result.update({"status": "failed", "stage": "config", "message": str(exc)})
    result["report_path"] = write_report(root, generated_at, result)
    return result


def run_head_extraction(root: Path, source: str | Path) -> dict[str, Any]:
    source_paths = resolve_source(source)
    page_root = source_paths["artifact_root"] / PAGE_ROOT_RELATIVE
    if not page_root.is_dir():
        raise FileNotFoundError(f"Missing captured page root: {page_root}")

    pages = [page_head_record(path, page_root) for path in sorted(page_root.rglob("*.html"))]
    shared = shared_dependencies(pages)
    manifest = {
        "clone_head": {
            "source": {
                "page_root": str(page_root),
            },
            "shared": shared,
            "pages": pages,
        }
    }
    write_manifest(root, manifest)
    excluded = [item for page in pages for item in page["excluded_external"]]
    return {
        "status": "completed",
        "stage": "clone_head_extraction",
        "source_files": {"page_root": str(page_root)},
        "summary": {
            "pages": len(pages),
            "shared_stylesheets": len(shared["stylesheets"]),
            "shared_scripts": len(shared["scripts"]),
            "shared_preloads": len(shared["preloads"]),
            "shared_inline_styles": len(shared["inline_styles"]),
            "page_stylesheets": sum(len(page["stylesheets"]) for page in pages),
            "page_scripts": sum(len(page["scripts"]) for page in pages),
            "page_preloads": sum(len(page["preloads"]) for page in pages),
            "page_inline_styles": sum(len(page["inline_styles"]) for page in pages),
            "excluded_external": len(excluded),
        },
        "manifest_path": str(MANIFEST_PATH),
        "excluded_external": excluded,
        "notes": [
            "Extracted captured WordPress head dependencies without network access.",
            "WordPress asset URLs are rewritten to /assets/wp/ paths when they point to wp-content or wp-includes.",
            "External analytics/tracking dependencies are excluded and reported.",
        ],
    }


def page_head_record(path: Path, page_root: Path) -> dict[str, Any]:
    parser = HeadParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    capture_path = str(path.relative_to(page_root.parent.parent))
    route = route_from_capture_path(path, page_root)
    return {
        "canonical_path": route,
        "captured_path": capture_path,
        "stylesheets": [
            rewrite_dependency(item)
            for item in parser.links
            if item["kind"] == "stylesheet" and not is_excluded_dependency(item)
        ],
        "preloads": [
            rewrite_dependency(item)
            for item in parser.links
            if item["kind"] == "preload" and not is_excluded_dependency(item)
        ],
        "scripts": [rewrite_dependency(item) for item in parser.scripts if not is_excluded_dependency(item)],
        "inline_styles": inline_styles(parser.inline_styles),
        "excluded_external": parser.excluded_external,
    }


def rewrite_dependency(item: dict[str, Any]) -> dict[str, Any]:
    rewritten = dict(item)
    url = item.get("href") or item.get("src")
    local = local_asset_path(url) if url else None
    if local:
        rewritten["local_path"] = local
    return rewritten


def is_excluded_dependency(item: dict[str, Any]) -> bool:
    url = item.get("href") or item.get("src") or ""
    return is_woocommerce_reference(url)


def is_woocommerce_reference(value: str) -> bool:
    return "woocommerce" in value.lower()


def local_asset_path(value: str) -> str | None:
    normalized = normalize_asset_url(value)
    if not normalized:
        return None
    relative = wordpress_relative_path(urlparse(normalized).path)
    if relative is None:
        return None
    return f"/assets/wp/{relative.as_posix()}"


def normalize_asset_url(value: str) -> str | None:
    if not value:
        return None
    if value.startswith("//"):
        value = f"https:{value}"
    elif value.startswith("/"):
        value = f"https://www.maricoparecords.com{value}"
    parsed = urlparse(value)
    if not parsed.path:
        return None
    scheme = parsed.scheme or "https"
    netloc = (parsed.netloc or "www.maricoparecords.com").lower()
    return urlunparse((scheme, netloc, unquote(parsed.path), "", "", ""))


def inline_styles(styles: list[str]) -> list[dict[str, Any]]:
    records = []
    for content in styles:
        normalized = content.strip()
        if not normalized:
            continue
        if is_woocommerce_reference(normalized):
            continue
        records.append(
            {
                "id": f"inline-{sha256(normalized.encode()).hexdigest()[:16]}",
                "content": normalized,
            }
        )
    return records


def shared_dependencies(pages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    stylesheets = shared_by_url(pages, "stylesheets", "href")
    scripts = shared_by_url(pages, "scripts", "src")
    preloads = shared_by_url(pages, "preloads", "href")
    inline = shared_inline_styles(pages)
    return {
        "stylesheets": stylesheets,
        "scripts": scripts,
        "preloads": preloads,
        "inline_styles": inline,
    }


def shared_by_url(pages: list[dict[str, Any]], key: str, url_key: str) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    first: dict[str, dict[str, Any]] = {}
    for page in pages:
        seen = set()
        for item in page[key]:
            url = item.get(url_key)
            if not url or url in seen:
                continue
            seen.add(url)
            counts[url] += 1
            first.setdefault(url, item)
    shared = []
    for url, count in counts.items():
        if count < 2:
            continue
        record = dict(first[url])
        record["pages"] = count
        shared.append(record)
    return sorted(shared, key=lambda item: item[url_key])


def shared_inline_styles(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    by_id: dict[str, dict[str, Any]] = {}
    for page in pages:
        seen = set()
        for item in page["inline_styles"]:
            style_id = item["id"]
            if style_id in seen:
                continue
            seen.add(style_id)
            counts[style_id] += 1
            by_id.setdefault(style_id, item)
    return sorted(
        [dict(by_id[style_id], pages=count) for style_id, count in counts.items() if count >= 2],
        key=lambda item: item["id"],
    )


def route_from_capture_path(path: Path, page_root: Path) -> str:
    relative = path.relative_to(page_root)
    parts = list(relative.parts)
    if parts == ["index.html"]:
        return "/"
    if parts[-1] == "index.html":
        parts = parts[:-1]
    elif parts[-1].endswith(".html"):
        parts[-1] = parts[-1][:-5]
    return normalize_path("/" + "/".join(parts))


class HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.in_head = False
        self.in_style = False
        self.current_style: list[str] = []
        self.links: list[dict[str, Any]] = []
        self.scripts: list[dict[str, Any]] = []
        self.inline_styles: list[str] = []
        self.excluded_external: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "head":
            self.in_head = True
            return
        if not self.in_head:
            return
        if tag == "link":
            self.handle_link(attr)
        elif tag == "script":
            self.handle_script(attr)
        elif tag == "style":
            self.in_style = True
            self.current_style = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False
        elif tag == "style" and self.in_style:
            self.inline_styles.append("".join(self.current_style))
            self.in_style = False
            self.current_style = []

    def handle_data(self, data: str) -> None:
        if self.in_head and self.in_style:
            self.current_style.append(data)

    def handle_link(self, attr: dict[str, str]) -> None:
        rels = {part.lower() for part in attr.get("rel", "").split()}
        if not rels.intersection(SUPPORTED_LINK_RELS):
            return
        href = attr.get("href", "")
        if is_excluded_external(href):
            self.excluded_external.append({"tag": "link", "url": href})
            return
        kind = "stylesheet" if "stylesheet" in rels else "preload"
        self.links.append(
            {
                "kind": kind,
                "rel": attr.get("rel", ""),
                "href": href,
                "media": attr.get("media") or None,
                "as": attr.get("as") or None,
                "id": attr.get("id") or None,
            }
        )

    def handle_script(self, attr: dict[str, str]) -> None:
        src = attr.get("src")
        if not src:
            return
        if is_excluded_external(src):
            self.excluded_external.append({"tag": "script", "url": src})
            return
        self.scripts.append(
            {
                "kind": "script",
                "src": src,
                "type": attr.get("type") or None,
                "id": attr.get("id") or None,
                "defer": "defer" in attr,
                "async": "async" in attr,
            }
        )


def is_excluded_external(value: str) -> bool:
    parsed = urlparse(value if not value.startswith("//") else f"https:{value}")
    return parsed.netloc.lower() in EXCLUDED_EXTERNAL_HOSTS


def write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    path = root / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False))


def write_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    path = root / "reports" / "migration" / f"{timestamp}-clone-head.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_clone_head(report: dict[str, Any]) -> str:
    if report["status"] == "failed":
        return "\n".join(
            [
                "Clone head extraction failed",
                f"Stage: {report['stage']}",
                f"Message: {report['message']}",
                f"Report: {report['report_path']}",
            ]
        )
    summary = report["summary"]
    return "\n".join(
        [
            "Clone head extraction completed",
            f"Pages: {summary['pages']}",
            f"Shared stylesheets: {summary['shared_stylesheets']}",
            f"Shared scripts: {summary['shared_scripts']}",
            f"Shared preloads: {summary['shared_preloads']}",
            f"Excluded external: {summary['excluded_external']}",
            f"Report: {report['report_path']}",
        ]
    )
