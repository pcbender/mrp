from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


DEFAULT_SOURCE = Path("/home/mrose/website-migration/import-artifacts/maricoparecords")
ARTIST_ROOT = "artists"
SKIP_SLUGS = {"artists"}


def import_site(repo: str | Path, source: str | Path = DEFAULT_SOURCE) -> dict[str, Any]:
    root = Path(repo).resolve()
    source_root = Path(source).resolve()
    normalized = load_json(source_root / "defined-skills/raw/normalized-wordpress-content.json")
    capture = load_json(source_root / "live-capture/capture-manifest.json")

    posts = normalized["payload"]["posts"]
    posts_by_slug = preferred_posts_by_slug(posts)
    page_records = capture.get("pages", [])
    artists, releases = candidates_from_pages(page_records, posts_by_slug)
    assets = candidate_assets(capture.get("assets", []))

    review_dir = root / "content" / "import-review"
    review_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(review_dir / "artists.yaml", {"candidates": artists})
    write_yaml(review_dir / "releases.yaml", {"candidates": releases})
    write_yaml(review_dir / "assets.yaml", {"candidates": assets})

    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report = {
        "command": "import-site",
        "status": "passed",
        "repo": str(root),
        "source": str(source_root),
        "generated_at": generated_at,
        "source_files": {
            "normalized_wordpress_content": str(
                source_root / "defined-skills/raw/normalized-wordpress-content.json"
            ),
            "capture_manifest": str(source_root / "live-capture/capture-manifest.json"),
        },
        "summary": {
            "source_posts": len(posts),
            "captured_pages": len(page_records),
            "captured_assets": len(capture.get("assets", [])),
            "external_references": len(capture.get("external_references", [])),
            "artist_candidates": len(artists),
            "release_candidates": len(releases),
            "asset_candidates": len(assets),
        },
        "outputs": [
            "content/import-review/artists.yaml",
            "content/import-review/releases.yaml",
            "content/import-review/assets.yaml",
        ],
        "notes": [
            "WXR-normalized content is treated as authoritative when sources disagree.",
            "Imported source files were not modified.",
            "Candidates are draft review records and require human/CP review before promotion.",
        ],
    }
    report["report_path"] = report_path(root, generated_at)
    write_json(root / report["report_path"], report)
    return report


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False))


def report_path(root: Path, generated_at: str) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "").replace("Z", "Z")
    return str((root / "reports" / "import" / f"{timestamp}.json").relative_to(root))


def preferred_posts_by_slug(posts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    priority = {
        "page": 0,
        "jetpack-portfolio": 1,
        "portfolio": 2,
        "post": 3,
        "cryout_serious_slide": 4,
        "attachment": 5,
    }
    by_slug: dict[str, dict[str, Any]] = {}
    for post in posts:
        slug = post.get("slug")
        if not slug:
            continue
        current = by_slug.get(slug)
        if current is None or priority.get(post.get("type"), 99) < priority.get(current.get("type"), 99):
            by_slug[slug] = post
    return by_slug


def candidates_from_pages(
    pages: list[dict[str, Any]],
    posts_by_slug: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    artists: dict[str, dict[str, Any]] = {}
    releases: dict[str, dict[str, Any]] = {}

    for page in pages:
        parts = path_parts(page.get("url", ""))
        if len(parts) < 2 or parts[0] != ARTIST_ROOT:
            continue
        artist_slug = parts[1]
        if artist_slug in SKIP_SLUGS:
            continue

        artist_post = posts_by_slug.get(artist_slug, {})
        artist = artists.setdefault(
            artist_slug,
            {
                "artist": {
                    "id": artist_slug,
                    "name": artist_post.get("title") or title_from_slug(artist_slug),
                    "visibility": "draft",
                    "source_url": artist_url(artist_slug),
                    "source_path": None,
                    "review_status": "needs_review",
                    "notes": ["Imported from captured artist page."],
                }
            },
        )

        if len(parts) == 2:
            artist["artist"]["source_url"] = page.get("url")
            artist["artist"]["source_path"] = page.get("path")
            continue
        if len(parts) < 3:
            continue
        release_slug = parts[2]
        release_post = posts_by_slug.get(release_slug, {})
        releases.setdefault(
            f"{artist_slug}/{release_slug}",
            {
                "release": {
                    "id": release_slug,
                    "slug": release_slug,
                    "title": release_post.get("title") or title_from_slug(release_slug),
                    "artist_id": artist_slug,
                    "model": "song",
                    "release_type": "single",
                    "status": "draft",
                    "release_date": date_part(release_post.get("published_at")),
                    "source_url": page.get("url"),
                    "source_path": page.get("path"),
                    "review_status": "needs_review",
                    "notes": [
                        "Imported as a single-song release candidate from artist page URL.",
                        "Confirm release metadata, cover image, streaming links, ISRC, and date.",
                    ],
                }
            },
        )

    return sorted(artists.values(), key=lambda item: item["artist"]["id"]), sorted(
        releases.values(), key=lambda item: (item["release"]["artist_id"], item["release"]["slug"])
    )


def candidate_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for asset in assets:
        path = asset.get("path") or ""
        if "woocommerce" in path:
            continue
        content_type = asset.get("content_type") or ""
        if not content_type.startswith(("image/", "audio/", "video/")):
            continue
        candidates.append(
            {
                "url": asset.get("url"),
                "path": asset.get("path"),
                "content_type": content_type,
                "bytes": asset.get("bytes"),
                "sha256": asset.get("sha256"),
                "review_status": "needs_review",
            }
        )
    return sorted(candidates, key=lambda item: item["path"] or "")


def path_parts(url: str) -> list[str]:
    return [part for part in urlparse(url).path.split("/") if part]


def title_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-"))


def artist_url(slug: str) -> str:
    return f"https://www.maricoparecords.com/artists/{slug}/"


def date_part(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(" ", 1)[0]


def format_import(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            "Import-site completed",
            f"Artist candidates: {summary['artist_candidates']}",
            f"Release candidates: {summary['release_candidates']}",
            f"Asset candidates: {summary['asset_candidates']}",
            f"Report: {report['report_path']}",
        ]
    )
