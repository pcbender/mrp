from __future__ import annotations

import json
import mimetypes
import re
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
from pathlib import Path
from posixpath import normpath
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

import yaml

from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE, resolve_source


ASSET_ROOT_RELATIVE = Path("live-capture/raw/assets/www.maricoparecords.com")
PAGE_ROOT_RELATIVE = Path("live-capture/raw/pages/www.maricoparecords.com")
DESTINATION_ROOT = Path("site/public/assets/wp")
MANIFEST_PATH = Path("content/clone/assets/manifest.yaml")
OVERSIZED_ASSET_BYTES = 5_000_000
ASSET_REFERENCE_RE = re.compile(
    r"""(?:src|href|srcset)=["']([^"']+)["']|url\(([^)]+)\)|(https?://[^\s"'<>]+/(?:wp-content|wp-includes)/[^\s"'<>]+|/(?:wp-content|wp-includes)/[^\s"'<>]+)"""
)


def clone_assets(
    repo: str | Path,
    source: str | Path = DEFAULT_MIGRATION_SOURCE,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    generated_at = now_utc()
    result = {
        "command": "clone-assets",
        "repo": str(root),
        "source": str(Path(source).expanduser()),
        "generated_at": generated_at,
    }
    try:
        result.update(run_asset_mirror(root, source))
    except FileNotFoundError as exc:
        result.update({"status": "failed", "stage": "config", "message": str(exc)})
    result["report_path"] = write_report(root, generated_at, result)
    return result


def run_asset_mirror(root: Path, source: str | Path) -> dict[str, Any]:
    source_paths = resolve_source(source)
    artifact_root = source_paths["artifact_root"]
    asset_root = artifact_root / ASSET_ROOT_RELATIVE
    page_root = artifact_root / PAGE_ROOT_RELATIVE
    if not asset_root.is_dir():
        raise FileNotFoundError(f"Missing captured asset root: {asset_root}")
    if not page_root.is_dir():
        raise FileNotFoundError(f"Missing captured page root: {page_root}")

    references = collect_asset_references(root, page_root)
    copied: list[dict[str, Any]] = []
    skipped_existing: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    oversized: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    duplicates: list[dict[str, str]] = []
    manifest_records: list[dict[str, Any]] = []
    destinations: dict[str, str] = {}
    total_bytes = 0

    for source_url, referenced_by in sorted(references.items()):
        parsed = urlparse(source_url)
        relative_path = wordpress_relative_path(parsed.path)
        if relative_path is None:
            unsupported.append(
                {
                    "source_url": source_url,
                    "referenced_by": sorted(referenced_by),
                    "reason": "Reference is not under wp-content or wp-includes.",
                }
            )
            continue
        source_path = asset_root / relative_path
        dest_rel = DESTINATION_ROOT / relative_path
        previous = destinations.get(str(dest_rel))
        if previous and previous != source_url:
            duplicates.append({"path": str(dest_rel), "source_url": source_url, "duplicate_of": previous})
            continue
        destinations[str(dest_rel)] = source_url
        if not source_path.is_file():
            missing.append(
                {
                    "source_url": source_url,
                    "referenced_by": sorted(referenced_by),
                    "reason": "Referenced asset was not found in captured raw assets.",
                }
            )
            manifest_records.append(asset_manifest_record(source_url, dest_rel, None, referenced_by, "missing"))
            continue

        size = source_path.stat().st_size
        if size > OVERSIZED_ASSET_BYTES:
            oversized.append(
                {
                    "source_url": source_url,
                    "local_path": str(dest_rel),
                    "referenced_by": sorted(referenced_by),
                    "bytes": size,
                    "threshold": OVERSIZED_ASSET_BYTES,
                }
            )

        dest_path = root / dest_rel
        if dest_path.exists():
            skipped_existing.append({"path": str(dest_rel), "source_url": source_url, "bytes": size})
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)
            copied.append({"path": str(dest_rel), "source_url": source_url, "bytes": size})
            total_bytes += size
        manifest_records.append(asset_manifest_record(source_url, dest_rel, source_path, referenced_by, "mirrored"))

    write_manifest(root, manifest_records)
    return {
        "status": "completed",
        "stage": "clone_asset_mirror",
        "source_files": {
            "capture_manifest": str(source_paths["capture_manifest"]),
            "asset_root": str(asset_root),
            "page_root": str(page_root),
        },
        "summary": {
            "referenced": len(references),
            "mirrored": len(manifest_records) - len(missing),
            "copied": len(copied),
            "skipped_existing": len(skipped_existing),
            "missing": len(missing),
            "unsupported": len(unsupported),
            "duplicates": len(duplicates),
            "oversized": len(oversized),
            "total_bytes_copied": total_bytes,
        },
        "copied": copied,
        "skipped_existing": skipped_existing,
        "missing": missing,
        "unsupported": unsupported,
        "duplicates": duplicates,
        "oversized": oversized,
        "manifest_path": str(MANIFEST_PATH),
        "notes": [
            "Mirrored captured WordPress assets without network access.",
            "Relative wp-content and wp-includes paths are preserved under site/public/assets/wp/.",
            "Oversized assets are copied and reported for review.",
        ],
    }


def collect_asset_references(root: Path, page_root: Path) -> dict[str, set[str]]:
    references: dict[str, set[str]] = {}
    for directory in (root / "content" / "clone" / "pages", root / "content" / "clone" / "posts"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text()) or {}
            html = (data.get("clone") or {}).get("content_html") or ""
            add_references(references, html, str(path.relative_to(root)))

    for path in sorted(page_root.rglob("*.html")):
        html = path.read_text(errors="ignore")
        add_references(references, html, str(path.relative_to(page_root.parent.parent)))
    return references


def add_references(references: dict[str, set[str]], html: str, source_label: str) -> None:
    for match in ASSET_REFERENCE_RE.findall(html):
        raw = next((part for part in match if part), "")
        for reference in split_asset_reference(raw):
            normalized = normalize_asset_url(reference)
            if normalized:
                references.setdefault(normalized, set()).add(source_label)


def split_asset_reference(raw: str) -> list[str]:
    value = unescape(raw).strip().strip("\"'").rstrip(".,")
    if not value:
        return []
    if "," in value and " " in value:
        return [part.split()[0] for part in value.split(",") if part.strip()]
    return [value]


def normalize_asset_url(value: str) -> str | None:
    value = unescape(value).strip().strip("\"'").rstrip(".,")
    if not value:
        return None
    if value.startswith("//"):
        value = f"https:{value}"
    elif value.startswith("/"):
        value = f"https://www.maricoparecords.com{value}"
    parsed = urlparse(value)
    if not parsed.path or not is_wordpress_asset_path(parsed.path):
        return None
    scheme = parsed.scheme or "https"
    netloc = (parsed.netloc or "www.maricoparecords.com").lower()
    return urlunparse((scheme, netloc, unquote(parsed.path), "", "", ""))


def is_wordpress_asset_path(path: str) -> bool:
    return path.startswith("/wp-content/") or path.startswith("/wp-includes/")


def wordpress_relative_path(path: str) -> Path | None:
    normalized = normpath(unquote(path))
    if normalized.startswith("../") or normalized == "..":
        return None
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if not is_wordpress_asset_path(normalized):
        return None
    return Path(normalized.lstrip("/"))


def asset_manifest_record(
    source_url: str,
    dest_rel: Path,
    source_path: Path | None,
    referenced_by: set[str],
    status: str,
) -> dict[str, Any]:
    content_type = mimetypes.guess_type(urlparse(source_url).path)[0]
    return {
        "id": f"wp-{sha256(source_url.encode()).hexdigest()[:16]}",
        "source_url": source_url,
        "local_path": str(dest_rel),
        "type": asset_type(content_type, urlparse(source_url).path),
        "status": status,
        "required": True,
        "content_type": content_type,
        "bytes": source_path.stat().st_size if source_path else None,
        "sha256": file_sha256(source_path) if source_path else None,
        "used_by": sorted(referenced_by),
    }


def asset_type(content_type: str | None, path: str) -> str:
    if content_type:
        if content_type.startswith("image/"):
            return "image"
        if content_type.startswith("audio/"):
            return "audio"
        if content_type.startswith("video/"):
            return "video"
        if content_type in {"text/css"}:
            return "style"
        if content_type in {"application/javascript", "text/javascript"}:
            return "script"
        if content_type == "application/pdf":
            return "document"
        if content_type.startswith("font/"):
            return "font"
    suffix = Path(path).suffix.lower()
    if suffix in {".woff", ".woff2", ".ttf", ".otf", ".eot"}:
        return "font"
    if suffix == ".js":
        return "script"
    if suffix == ".css":
        return "style"
    return "other"


def file_sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(root: Path, records: list[dict[str, Any]]) -> None:
    path = root / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"clone_assets": sorted(records, key=lambda item: item["source_url"])}
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False))


def write_report(root: Path, generated_at: str, result: dict[str, Any]) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    path = root / "reports" / "migration" / f"{timestamp}-clone-assets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return str(path.relative_to(root))


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_clone_assets(report: dict[str, Any]) -> str:
    if report["status"] == "failed":
        return "\n".join(
            [
                "Clone asset mirror failed",
                f"Stage: {report['stage']}",
                f"Message: {report['message']}",
                f"Report: {report['report_path']}",
            ]
        )
    summary = report["summary"]
    return "\n".join(
        [
            "Clone asset mirror completed",
            f"Referenced: {summary['referenced']}",
            f"Mirrored: {summary['mirrored']}",
            f"Copied: {summary['copied']}",
            f"Missing: {summary['missing']}",
            f"Oversized: {summary['oversized']}",
            f"Report: {report['report_path']}",
        ]
    )
