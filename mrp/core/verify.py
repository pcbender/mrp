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
    if release:
        releases = [item for item in releases if item.get("id") == release]
        if not releases:
            add_error(result, "release", f"Unknown release: {release}")

    check_required_files(result, target_path)
    check_release_pages(result, target_path, releases)
    check_artist_pages(result, target_path, artists)
    check_cover_images(result, target_path, releases)
    check_internal_links(result, target_path)
    check_placeholders(result, target_path)

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
        scanned += 1
        text = path.read_text(errors="ignore")
        lower = text.lower()
        for pattern in PLACEHOLDER_PATTERNS:
            matched = pattern in text if pattern.isupper() or pattern.endswith("_") else pattern in lower
            if matched:
                add_error(result, "placeholder", f"{path.relative_to(target_path)} contains forbidden token: {pattern}")
    result["checks"].append({"name": "placeholders", "status": "passed", "checked": scanned})


def check_file(result: dict[str, Any], path: Path, relative: str) -> None:
    if path.is_file():
        result["checks"].append({"name": "required_file", "status": "passed", "path": relative})
    else:
        add_error(result, "required_file", f"Missing required file: {relative}")


def should_skip_link(href: str) -> bool:
    if href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return True
    parsed = urlparse(href)
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
