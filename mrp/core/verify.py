from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from mrp.core.deploy import load_targets, validate_target


CONTENT_EXTENSIONS = {".yaml", ".yml", ".json"}
PLACEHOLDER_PATTERNS = ["TODO", "TBD", "FIXME", "lorem ipsum", "example.com", "INSERT_", "PLACEHOLDER"]
TEXT_EXTENSIONS = {".html", ".css", ".js", ".json", ".xml", ".txt", ".php"}
EXCLUDED_MIGRATION_PATHS = ["cart", "checkout", "my-account", "account", "payment", "shop"]
BASELINE_V01_ROUTES = {"/", "/about-us/", "/artists/", "/catalog/", "/contact/", "/posts/", "/releases/"}
CLONE_KNOWN_MARKERS = [
    {
        "route": "/artists/pcbender/",
        "marker": "mystique",
        "description": "PCBender artist bio",
    },
    {
        "route": "/artists/pcbender/circuiting/",
        "marker": "Circuiting is not just an album",
        "description": "Circuiting release page",
    },
]


def verify_target(repo: str | Path, target: str | None = None, release: str | None = None) -> dict[str, Any]:
    root = Path(repo).resolve()
    target_name = normalize_target(target)
    generated_at = now_utc()
    result = {
        "command": "verify",
        "repo": str(root),
        "target": target_name,
        "requested_target": target,
        "release": release,
        "generated_at": generated_at,
        "checks": [],
        "errors": [],
    }

    targets, config_errors = load_targets(root)
    if config_errors:
        add_error(result, "config", "; ".join(config_errors))
        return finish(root, generated_at, result)
    if target_name not in targets:
        add_error(result, "config", f"Unknown verify target: {target_name}")
        return finish(root, generated_at, result)

    safety = validate_target(root, target_name, targets[target_name])
    result["target_path"] = safety.get("target_path")
    result["environment"] = safety.get("environment")
    if safety["status"] != "passed":
        add_error(result, "safety", safety["message"])
        return finish(root, generated_at, result)

    target_path = root / safety["target_path"]
    deployment = latest_deployment(root, target_name)
    result["build_id"] = deployment.get("build_id")
    result["build_report_path"] = deployment.get("build_report_path")
    result["deployment_report_path"] = deployment.get("report_path")
    releases = load_records(root / "content" / "releases", "release")
    artists = load_records(root / "content" / "artists", "artist")
    pages = load_records(root / "content" / "pages", "page")
    posts = load_records(root / "content" / "posts", "post")
    clone_pages = load_records(root / "content" / "clone" / "pages", "clone")
    clone_posts = load_records(root / "content" / "clone" / "posts", "clone")
    if release:
        releases = [item for item in releases if item.get("id") == release]
        if not releases:
            add_error(result, "release", f"Unknown release: {release}")
        artist_ids = {item.get("artist_id") for item in releases}
        artists = [item for item in artists if item.get("id") in artist_ids]

    check_required_files(result, target_path)
    check_release_pages(result, target_path, releases)
    check_artist_pages(result, target_path, artists)
    check_cover_images(result, target_path, releases)
    check_internal_links(result, target_path)
    check_placeholders(result, target_path)
    check_migration_surface(result, root, target_path, pages, posts, artists, releases)
    check_clone_surface(result, root, target_path, clone_pages, clone_posts)

    return finish(root, generated_at, result)


def normalize_target(target: str | None) -> str:
    if target in {None, "staging"}:
        return "local-staging"
    if target == "production":
        return "local-production"
    return target


def check_required_files(result: dict[str, Any], target_path: Path) -> None:
    for relative in ["index.html", "sitemap.xml", "feed.xml"]:
        check_file(result, target_path / relative, relative)


def check_release_pages(result: dict[str, Any], target_path: Path, releases: list[dict[str, Any]]) -> None:
    for release in releases:
        if release.get("status") == "draft":
            continue
        relative = f"releases/{release['slug']}/index.html"
        check_file(result, target_path / relative, relative)


def check_artist_pages(result: dict[str, Any], target_path: Path, artists: list[dict[str, Any]]) -> None:
    for artist in artists:
        if artist.get("visibility") != "public":
            continue
        slug = artist.get("slug") or artist["id"]
        relative = f"artists/{slug}/index.html"
        check_file(result, target_path / relative, relative)


def check_cover_images(result: dict[str, Any], target_path: Path, releases: list[dict[str, Any]]) -> None:
    for release in releases:
        if release.get("status") == "draft":
            continue
        cover = release.get("cover_image")
        if not cover:
            add_error(result, "release.cover_image", f"Missing cover image field for {release['id']}")
            continue
        relative = cover.removeprefix("site/public/")
        check_file(result, target_path / relative, relative)


def check_internal_links(result: dict[str, Any], target_path: Path) -> None:
    checked = 0
    for html_path in sorted(target_path.rglob("*.html")):
        text = html_path.read_text(errors="ignore")
        for href in re.findall(r'href=["\']([^"\']+)["\']', text):
            if should_skip_link(href):
                continue
            link_path = link_to_path(target_path, href)
            checked += 1
            if not link_path.exists():
                relative_source = html_path.relative_to(target_path)
                add_error(result, "internal_link", f"{relative_source} links to missing path: {href}")
    result["checks"].append({"name": "internal_links", "status": "passed", "checked": checked})


def check_placeholders(result: dict[str, Any], target_path: Path) -> None:
    scanned = 0
    for path in sorted(target_path.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_EXTENSIONS:
            continue
        if is_mirrored_wordpress_asset(target_path, path):
            continue
        scanned += 1
        text = path.read_text(errors="ignore")
        lower = text.lower()
        for pattern in PLACEHOLDER_PATTERNS:
            matched = pattern in text if pattern.isupper() or pattern.endswith("_") else pattern in lower
            if matched:
                add_error(result, "placeholder", f"{path.relative_to(target_path)} contains forbidden token: {pattern}")
    result["checks"].append({"name": "placeholders", "status": "passed", "checked": scanned})


def is_mirrored_wordpress_asset(target_path: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(target_path)
    except ValueError:
        return False
    return len(relative.parts) >= 2 and relative.parts[0] == "assets" and relative.parts[1] == "wp"


def check_migration_surface(
    result: dict[str, Any],
    root: Path,
    target_path: Path,
    pages: list[dict[str, Any]],
    posts: list[dict[str, Any]],
    artists: list[dict[str, Any]],
    releases: list[dict[str, Any]],
) -> None:
    pages = [page for page in pages if page.get("content_html")]
    posts = [post for post in posts if post.get("content_html")]
    routes = migrated_route_paths(root, pages, posts)
    enabled = bool(pages or posts) and target_has_migration_surface(target_path, routes, artists, releases)
    migration = {
        "enabled": enabled,
        "pages": len(pages),
        "posts": len(posts),
        "routes_checked": 0,
        "asset_records_checked": 0,
        "excluded_paths_checked": EXCLUDED_MIGRATION_PATHS,
    }
    result["migration"] = migration
    if not enabled:
        return
    migration["routes_checked"] = check_migrated_routes(result, target_path, routes)
    migration["asset_records_checked"] = check_migrated_assets(result, root, target_path)
    check_excluded_migration_paths(result, target_path)


def check_migrated_routes(
    result: dict[str, Any],
    target_path: Path,
    routes: set[str],
) -> int:
    for route in sorted(routes):
        relative = route_to_html_relative(route)
        check_file(result, target_path / relative, relative)
    result["checks"].append({"name": "migrated_routes", "status": "passed", "checked": len(routes)})
    return len(routes)


def migrated_route_paths(root: Path, pages: list[dict[str, Any]], posts: list[dict[str, Any]]) -> set[str]:
    routes = {normalized_route_path(item) for item in [*pages, *posts] if item.get("slug")}
    routes.update(migrated_post_aliases(root, posts))
    return routes


def target_has_migration_surface(
    target_path: Path,
    routes: set[str],
    artists: list[dict[str, Any]],
    releases: list[dict[str, Any]],
) -> bool:
    baseline = {
        *BASELINE_V01_ROUTES,
        *(
            f"/artists/{artist.get('slug') or artist.get('id')}/"
            for artist in artists
            if artist.get("visibility") == "public"
        ),
        *(
            f"/releases/{release.get('slug')}/"
            for release in releases
            if release.get("status") != "draft" and release.get("slug")
        ),
    }
    for route in routes:
        if route in baseline:
            continue
        if (target_path / route_to_html_relative(route)).is_file():
            return True
    return False


def migrated_post_aliases(root: Path, posts: list[dict[str, Any]]) -> set[str]:
    aliases: set[str] = set()
    slugs = {post.get("slug") for post in posts if post.get("slug")}
    redirects = load_redirects(root)
    for redirect in redirects:
        source = normalize_route_path(redirect.get("source_path") or "")
        if any(source.endswith(f"/{slug}/") for slug in slugs):
            aliases.add(source)
    return aliases


def check_migrated_assets(result: dict[str, Any], root: Path, target_path: Path) -> int:
    manifest = load_asset_manifest(root)
    assets = [
        asset
        for asset in manifest.get("assets", [])
        if asset.get("required") and "migrated_content" in set(asset.get("usage") or [])
    ]
    for asset in assets:
        relative = str(asset.get("path", "")).removeprefix("site/public/")
        check_file(result, target_path / relative, relative)
    result["checks"].append({"name": "migrated_assets", "status": "passed", "checked": len(assets)})
    return len(assets)


def check_excluded_migration_paths(result: dict[str, Any], target_path: Path) -> None:
    for path in EXCLUDED_MIGRATION_PATHS:
        html_path = target_path / path / "index.html"
        if html_path.exists():
            add_error(result, "migration.excluded_path", f"Excluded migration path was rendered: /{path}/")
    result["checks"].append(
        {"name": "migration_exclusions", "status": "passed", "checked": len(EXCLUDED_MIGRATION_PATHS)}
    )


def check_clone_surface(
    result: dict[str, Any],
    root: Path,
    target_path: Path,
    clone_pages: list[dict[str, Any]],
    clone_posts: list[dict[str, Any]],
) -> None:
    clone_records = [
        record
        for record in [*clone_pages, *clone_posts]
        if (record.get("route") or {}).get("canonical_path")
    ]
    enabled = bool(clone_records) and target_has_clone_surface(target_path, clone_records)
    clone = {
        "enabled": enabled,
        "pages": len(clone_pages),
        "posts": len(clone_posts),
        "routes_checked": 0,
        "asset_records_checked": 0,
        "rendered_wp_asset_refs_checked": 0,
        "known_markers_checked": 0,
        "excluded_paths_checked": EXCLUDED_MIGRATION_PATHS,
    }
    result["clone"] = clone
    if not enabled:
        return

    clone["routes_checked"] = check_clone_routes(result, target_path, clone_records)
    clone["asset_records_checked"] = check_clone_asset_manifest(result, root, target_path)
    clone["rendered_wp_asset_refs_checked"] = check_rendered_wordpress_assets(result, target_path)
    clone["known_markers_checked"] = check_clone_known_markers(result, target_path)
    check_excluded_clone_paths(result, target_path)
    result["checks"].append({"name": "clone_verification", "status": "passed", "checked": len(clone_records)})


def target_has_clone_surface(target_path: Path, clone_records: list[dict[str, Any]]) -> bool:
    for html_path in sorted(target_path.rglob("*.html")):
        text = html_path.read_text(errors="ignore")
        if 'data-clone-kind="' in text or "wp-clone-content" in text:
            return True
    return False


def check_clone_routes(result: dict[str, Any], target_path: Path, clone_records: list[dict[str, Any]]) -> int:
    checked = 0
    for record in sorted(clone_records, key=lambda item: (item.get("route") or {}).get("canonical_path") or ""):
        route = normalize_route_path((record.get("route") or {}).get("canonical_path") or "")
        relative = route_to_html_relative(route)
        check_file(result, target_path / relative, relative)
        checked += 1
    result["checks"].append({"name": "clone_routes", "status": "passed", "checked": checked})
    return checked


def check_clone_asset_manifest(result: dict[str, Any], root: Path, target_path: Path) -> int:
    manifest = load_clone_asset_manifest(root)
    checked = 0
    for asset in manifest.get("clone_assets", []):
        if not asset.get("required") or asset.get("status") != "mirrored":
            continue
        relative = str(asset.get("local_path", "")).removeprefix("site/public/")
        check_file(result, target_path / relative, relative)
        checked += 1
    result["checks"].append({"name": "clone_asset_manifest", "status": "passed", "checked": checked})
    return checked


def check_rendered_wordpress_assets(result: dict[str, Any], target_path: Path) -> int:
    checked = 0
    seen: set[tuple[str, str]] = set()
    for html_path in sorted(target_path.rglob("*.html")):
        text = html_path.read_text(errors="ignore")
        for reference in rendered_wordpress_asset_refs(text):
            relative = reference.lstrip("/").split("?", 1)[0].split("#", 1)[0]
            key = (str(html_path.relative_to(target_path)), relative)
            if key in seen:
                continue
            seen.add(key)
            checked += 1
            if not (target_path / relative).is_file():
                add_error(
                    result,
                    "clone.asset",
                    f"{html_path.relative_to(target_path)} references missing WordPress asset: {reference}",
                )
    result["checks"].append({"name": "clone_rendered_wp_assets", "status": "passed", "checked": checked})
    return checked


def rendered_wordpress_asset_refs(text: str) -> set[str]:
    references = set(re.findall(r"""["'(](/assets/wp/[^"')\s<>]+)""", text))
    references.update(re.findall(r"""\b(?:href|src)=["'](/assets/wp/[^"']+)["']""", text))
    return references


def check_clone_known_markers(result: dict[str, Any], target_path: Path) -> int:
    checked = 0
    for marker in CLONE_KNOWN_MARKERS:
        html_path = target_path / route_to_html_relative(marker["route"])
        checked += 1
        if not html_path.is_file():
            add_error(result, "clone.marker", f"Missing marker page for {marker['description']}: {marker['route']}")
            continue
        text = html_path.read_text(errors="ignore")
        if marker["marker"] not in text:
            add_error(
                result,
                "clone.marker",
                f"{html_path.relative_to(target_path)} is missing known content marker: {marker['marker']}",
            )
    result["checks"].append({"name": "clone_known_markers", "status": "passed", "checked": checked})
    return checked


def check_excluded_clone_paths(result: dict[str, Any], target_path: Path) -> None:
    for path in EXCLUDED_MIGRATION_PATHS:
        html_path = target_path / path / "index.html"
        if html_path.exists():
            add_error(result, "clone.excluded_path", f"Excluded clone path was rendered: /{path}/")
    result["checks"].append({"name": "clone_exclusions", "status": "passed", "checked": len(EXCLUDED_MIGRATION_PATHS)})


def normalized_route_path(record: dict[str, Any]) -> str:
    return normalize_route_path(record.get("normalized_path") or f"/{record.get('slug', '')}/")


def normalize_route_path(path: str) -> str:
    value = f"/{str(path).strip('/')}/"
    return "/" if value == "//" else value


def route_to_html_relative(route: str) -> str:
    if route == "/":
        return "index.html"
    return f"{route.strip('/')}/index.html"


def load_redirects(root: Path) -> list[dict[str, Any]]:
    path = root / "content" / "redirects.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("redirects", [])


def load_asset_manifest(root: Path) -> dict[str, Any]:
    path = root / "content" / "assets" / "manifest.yaml"
    if not path.is_file():
        return {"assets": []}
    return yaml.safe_load(path.read_text()) or {"assets": []}


def load_clone_asset_manifest(root: Path) -> dict[str, Any]:
    path = root / "content" / "clone" / "assets" / "manifest.yaml"
    if not path.is_file():
        return {"clone_assets": []}
    return yaml.safe_load(path.read_text()) or {"clone_assets": []}


def check_file(result: dict[str, Any], path: Path, relative: str) -> None:
    if path.is_file():
        result["checks"].append({"name": "required_file", "status": "passed", "path": relative})
    else:
        add_error(result, "required_file", f"Missing required file: {relative}")


def should_skip_link(href: str) -> bool:
    if href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return True
    parsed = urlparse(href)
    if parsed.netloc:
        return True
    return bool(parsed.scheme and parsed.scheme not in {"", "file"})


def link_to_path(target_path: Path, href: str) -> Path:
    parsed = urlparse(href)
    path = parsed.path or "/"
    if path.endswith("/"):
        return target_path / path.removeprefix("/") / "index.html"
    candidate = target_path / path.removeprefix("/")
    if candidate.suffix:
        return candidate
    return candidate / "index.html"


def load_records(directory: Path, root_key: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not directory.is_dir():
        return records
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix not in CONTENT_EXTENSIONS:
            continue
        data = json.loads(path.read_text()) if path.suffix == ".json" else yaml.safe_load(path.read_text())
        record = data.get(root_key, {})
        records.append(record)
    return records


def latest_deployment(root: Path, target: str) -> dict[str, Any]:
    reports = sorted((root / "reports" / "deployment").glob(f"*-{target}-*.json"))
    for report_path in reversed(reports):
        data = json.loads(report_path.read_text())
        if data.get("status") == "passed":
            data["report_path"] = str(report_path.relative_to(root))
            return data
    return {}


def add_error(result: dict[str, Any], field: str, message: str) -> None:
    result["errors"].append({"field": field, "message": message, "severity": "error"})


def finish(root: Path, generated_at: str, result: dict[str, Any]) -> dict[str, Any]:
    result["status"] = "passed" if not result["errors"] else "failed"
    result["summary"] = {
        "checks": len(result["checks"]),
        "errors": len(result["errors"]),
    }
    result["report_path"] = write_verification_report(root, generated_at, result)
    return result


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_verification_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    target = result.get("target") or "unknown-target"
    report_path = root / "reports" / "verification" / f"{timestamp}-{target}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def format_verification(result: dict[str, Any]) -> str:
    lines = [
        f"Verification {result['status']}",
        f"Target: {result['target']}",
        f"Report: {result['report_path']}",
        f"Errors: {result['summary']['errors']}",
    ]
    for error in result["errors"]:
        lines.append(f"- {error['field']}: {error['message']}")
    return "\n".join(lines)
