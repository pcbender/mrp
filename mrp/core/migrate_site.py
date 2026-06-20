from __future__ import annotations

import json
import re
import shutil
import unicodedata
from hashlib import sha256
from html import unescape
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

import yaml

from mrp.core.import_site import title_from_slug
from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE, migration_inventory
from mrp.core.wp_normalize import normalize_wordpress_content

MIGRATED_ASSET_USAGE = "migrated_content"
OVERSIZED_ASSET_BYTES = 5_000_000
SUPPORTED_ASSET_TYPES = {
    "image": ("image/",),
    "audio": ("audio/",),
    "video": ("video/",),
    "document": ("application/pdf",),
}
ASSET_REFERENCE_RE = re.compile(
    r"""(?:src|href|srcset)=["']([^"']+)["']|url\(([^)]+)\)|(https?://[^\s"'<>]+/wp-content/[^\s"'<>]+|/wp-content/[^\s"'<>]+)"""
)


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
    normalization_result = normalize_canonical_content(root)
    if normalization_result["report_path"]:
        created.append(normalization_result["report_path"])
    asset_result = copy_referenced_assets(root, inventory)
    if asset_result.get("manifest_updated"):
        created.append("content/assets/manifest.yaml")
    catalog_result = promote_catalog_metadata(root)

    return {
        "status": "completed",
        "stage": "content_generation",
        "summary": inventory["summary"],
        "planned_writes": planned_writes(inventory),
        "normalization": normalization_result,
        "catalog": catalog_result,
        "assets": asset_result,
        "created": sorted(created),
        "skipped": sorted(skipped, key=lambda item: item["path"]),
        "review_needed": sorted(review_needed, key=lambda item: item["path"]),
        "notes": [
            "Generated staging content records and copied referenced migrated assets.",
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
    content = normalize_wordpress_content(
        post.get("content") or "",
        f"content/pages/{slug}.yaml",
    )
    return {
        "page": {
            "id": slug,
            "slug": slug,
            "title": title,
            "status": "draft",
            "normalized_path": normalized_path,
            "source_url": (route["url"] if route else f"https://www.maricoparecords.com/{slug}/"),
            "content_html": content.content_html,
            "content_markdown": content.content_markdown,
            "sections": content.sections,
            "images": content.images,
            "socials": content.socials,
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
    content = normalize_wordpress_content(
        source_post.get("content") or "",
        f"content/posts/{post['slug']}.yaml",
    )
    return {
        "post": {
            "id": post["slug"],
            "slug": post["slug"],
            "title": unescape(post.get("title") or title_from_slug(post["slug"])),
            "status": "draft",
            "normalized_path": f"/{post['slug']}/",
            "source_url": f"https://www.maricoparecords.com/{post['slug']}/",
            "published_at": post.get("published_at"),
            "content_html": content.content_html,
            "content_markdown": content.content_markdown,
            "sections": content.sections,
            "images": content.images,
            "socials": content.socials,
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


def normalize_canonical_content(root: Path) -> dict[str, Any]:
    updated: list[str] = []
    unresolved: list[dict[str, str]] = []
    for directory, root_key in ((root / "content" / "pages", "page"), (root / "content" / "posts", "post")):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text()) or {}
            record = data.get(root_key)
            if not isinstance(record, dict) or "content_html" not in record:
                continue
            rel_path = str(path.relative_to(root))
            content = normalize_wordpress_content(record.get("content_html") or "", rel_path)
            before = yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
            record["content_html"] = content.content_html
            record["content_markdown"] = content.content_markdown
            record["sections"] = content.sections
            record["images"] = content.images
            record["socials"] = content.socials
            unresolved.extend(content.unresolved_artifacts)
            after = yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
            if after != before:
                path.write_text(after)
                updated.append(rel_path)
    report_path = write_unresolved_artifact_report(root, unresolved)
    return {
        "updated": updated,
        "updated_count": len(updated),
        "unresolved_count": len(unresolved),
        "report_path": report_path,
    }


def write_unresolved_artifact_report(root: Path, artifacts: list[dict[str, str]]) -> str:
    report_path = root / "migration" / "reports" / "unresolved-artifacts.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": now_utc(),
        "scope": "canonical_content",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return str(report_path.relative_to(root))


def promote_catalog_metadata(root: Path) -> dict[str, Any]:
    artist_pages, release_pages = catalog_pages(root)
    updated: list[str] = []
    for artist_id, page in sorted(artist_pages.items()):
        path = existing_record_path(root / "content" / "artists", artist_id)
        if path is None:
            continue
        data = load_structured_record(path)
        artist = data.get("artist")
        if not isinstance(artist, dict):
            continue
        before = serialize_structured_record(path, data)
        artist["name"] = page.get("title") or artist.get("name") or title_from_slug(artist_id)
        artist["sort_name"] = artist["name"]
        artist["visibility"] = "public"
        artist["bio_long"] = page.get("content_markdown") or artist.get("bio_long") or ""
        artist["bio_short"] = (
            first_nonempty_paragraph(page.get("content_markdown") or "", page.get("title"))
            or artist.get("bio_short")
            or ""
        )
        image = first_local_asset_url(root, page)
        if image:
            artist["image"] = public_asset_url(image)
        links = artist.setdefault("links", {})
        links.pop("website", None)
        for key, value in (page.get("socials") or {}).items():
            if key in {"spotify", "apple_music", "youtube_music", "youtube", "bandcamp", "instagram"}:
                links[key] = value
        after = serialize_structured_record(path, data)
        if after != before:
            path.write_text(after)
            updated.append(str(path.relative_to(root)))

    for (artist_id, release_id), page in sorted(release_pages.items()):
        path = existing_record_path(root / "content" / "releases", release_id)
        if path is None:
            continue
        data = load_structured_record(path)
        release = data.get("release")
        if not isinstance(release, dict):
            continue
        before = serialize_structured_record(path, data)
        tracks = release_tracks(page)
        release["artist_id"] = artist_id
        release["status"] = "staged"
        release["summary"] = (
            first_nonempty_paragraph(page.get("content_markdown") or "", page.get("title"))
            or release.get("summary")
            or ""
        )
        release["description"] = page.get("content_markdown") or release.get("description") or ""
        image = first_local_asset_url(root, page)
        if image:
            release["cover_image"] = image
        links = release.setdefault("links", {})
        for source_key, target_key in (
            ("spotify", "spotify"),
            ("apple_music", "apple_music"),
            ("youtube_music", "youtube_music"),
            ("bandcamp", "bandcamp"),
            ("soundcloud", "soundcloud"),
        ):
            value = (page.get("socials") or {}).get(source_key)
            if value:
                links[target_key] = value
        links.pop("landing_page", None)
        primary_artist = title_from_slug(artist_id)
        if artist_id in artist_pages:
            primary_artist = artist_pages[artist_id].get("title") or primary_artist
        release.setdefault("credits", {})["primary_artist"] = primary_artist
        if tracks:
            release["model"] = "album"
            release["release_type"] = "ep" if len(tracks) <= 6 else "album"
            release["tracks"] = tracks
            release.pop("song", None)
        else:
            release["model"] = "song"
            release["release_type"] = "single"
            release["song"] = {
                "number": None,
                "title": release.get("title") or page.get("title") or title_from_slug(release_id),
                "slug": release_id,
                "isrc": None,
                "duration": None,
                "explicit": False,
                "preview_audio": None,
                "lyrics_excerpt": None,
            }
            release.pop("tracks", None)
        title = release.get("title") or page.get("title") or title_from_slug(release_id)
        release["seo"] = {
            "title": f"{title} by {primary_artist}",
            "description": f"{title} by {primary_artist} on Maricopa Records.",
        }
        after = serialize_structured_record(path, data)
        if after != before:
            path.write_text(after)
            updated.append(str(path.relative_to(root)))
    return {"updated": sorted(updated), "updated_count": len(updated)}


def catalog_pages(root: Path) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    artist_pages: dict[str, dict[str, Any]] = {}
    release_pages: dict[tuple[str, str], dict[str, Any]] = {}
    pages_dir = root / "content" / "pages"
    if not pages_dir.is_dir():
        return artist_pages, release_pages
    for path in sorted(pages_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        page = data.get("page") or {}
        parts = [part for part in (page.get("normalized_path") or "").split("/") if part]
        if len(parts) == 2 and parts[0] == "artists":
            artist_pages[parts[1]] = page
        elif len(parts) == 3 and parts[0] == "artists":
            release_pages[(parts[1], parts[2])] = page
    for artist_id, page in list(artist_pages.items()):
        if page.get("content_html") or page.get("images"):
            continue
        clone_page = clone_artist_page(root, artist_id)
        if clone_page:
            artist_pages[artist_id] = clone_page
    return artist_pages, release_pages


def clone_artist_page(root: Path, artist_id: str) -> dict[str, Any] | None:
    path = root / "content" / "clone" / "pages" / f"artists-{artist_id}.yaml"
    if not path.is_file():
        return None
    clone = (yaml.safe_load(path.read_text()) or {}).get("clone") or {}
    content = normalize_wordpress_content(clone.get("content_html") or "", str(path.relative_to(root)))
    return {
        "title": clone.get("title") or title_from_slug(artist_id),
        "source_url": ((clone.get("source") or {}).get("link")),
        "content_html": content.content_html,
        "content_markdown": content.content_markdown,
        "images": content.images,
        "socials": content.socials,
    }


def existing_record_path(directory: Path, record_id: str) -> Path | None:
    for suffix in (".yaml", ".yml", ".json"):
        path = directory / f"{record_id}{suffix}"
        if path.exists():
            return path
    return None


def load_structured_record(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        return json.loads(path.read_text())
    return yaml.safe_load(path.read_text()) or {}


def serialize_structured_record(path: Path, data: dict[str, Any]) -> str:
    if path.suffix == ".json":
        return json.dumps(data, indent=2, sort_keys=False) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def first_nonempty_paragraph(markdown: str, title: str | None = None) -> str:
    normalized_title = (title or "").strip().lower()
    for block in markdown.split("\n\n"):
        value = re.sub(r"^#+\s*", "", block).strip()
        if (
            value
            and value.lower() != normalized_title
            and not value.startswith("![")
            and not value.startswith("[](")
        ):
            return value
    return ""


def first_local_asset_url(root: Path, page: dict[str, Any]) -> str | None:
    for image in page.get("images") or []:
        src = image.get("src") if isinstance(image, dict) else None
        normalized = normalize_asset_url(src or "")
        if normalized:
            migrated = migrated_asset_path(normalized)
            if (root / migrated).is_file():
                return migrated
            parsed = urlparse(normalized)
            if parsed.netloc.endswith("maricoparecords.com") and parsed.path.startswith("/wp-content/"):
                mirrored = f"site/public/assets/wp{parsed.path}"
                if (root / mirrored).is_file():
                    return mirrored
    return None


def public_asset_url(path: str) -> str:
    return "/" + path.removeprefix("site/public/").lstrip("/")


def streaming_service_key(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if "open.spotify.com" in host:
        return "spotify"
    if "music.apple.com" in host:
        return "apple_music"
    if "music.youtube.com" in host or host.endswith("youtube.com") or host.endswith("youtu.be"):
        return "youtube_music"
    return None


def release_track_links(page: dict[str, Any]) -> dict[int, dict[str, str]]:
    markdown = page.get("content_markdown") or ""
    if "## Tracks" not in markdown:
        return {}
    track_section = markdown.split("## Tracks", 1)[1]
    lines = [line.strip() for line in track_section.splitlines() if line.strip()]
    links_by_number: dict[int, dict[str, str]] = {}
    for index, line in enumerate(lines):
        if not line.isdigit():
            continue
        number = int(line)
        cursor = index + 1
        while cursor < len(lines) and (lines[cursor].isdigit() or lines[cursor].lower() in {"#", "title", "listen"}):
            cursor += 1
        cursor += 1
        links: dict[str, str] = {}
        while cursor < len(lines) and not lines[cursor].isdigit():
            for url in re.findall(r"\]\((https?://[^)]+)\)", lines[cursor]):
                service = streaming_service_key(url)
                if service and service not in links:
                    links[service] = url
            cursor += 1
        if links:
            links_by_number[number] = links
    return links_by_number


def release_tracks(page: dict[str, Any]) -> list[dict[str, Any]]:
    text = re.sub(r"<[^>]+>", "\n", page.get("content_html") or "")
    lines = [unescape(line).strip() for line in text.splitlines() if unescape(line).strip()]
    track_links = release_track_links(page)
    tracks: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line.isdigit():
            continue
        number = int(line)
        if number < 1:
            continue
        title = next((candidate for candidate in lines[index + 1 :] if candidate and not candidate.isdigit()), "")
        if title and title.lower() not in {"title", "listen"}:
            tracks.append(
                {
                    "number": number,
                    "title": title,
                    "slug": safe_slug(title),
                    "isrc": None,
                    "duration": None,
                    "explicit": False,
                    "preview_audio": None,
                    "lyrics_excerpt": None,
                    "links": track_links.get(number, {}),
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[int] = set()
    for track in tracks:
        if track["number"] in seen:
            continue
        seen.add(track["number"])
        deduped.append(track)
    return deduped


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
                "spotify": None,
                "apple_music": None,
                "youtube_music": None,
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


def copy_referenced_assets(root: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    capture_manifest = Path(inventory["source_files"]["capture_manifest"])
    capture_root = capture_manifest.parent
    assets_by_url = capture_assets_by_url(inventory["assets"])
    references = extract_content_asset_references(root)
    copied: list[dict[str, Any]] = []
    skipped_existing: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    oversized: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    duplicate_destinations: list[dict[str, Any]] = []
    manifest_records: list[dict[str, Any]] = []
    destination_paths: dict[str, str] = {}
    total_bytes = 0

    for source_url, page_references in sorted(references.items()):
        normalized_url = normalize_asset_url(source_url)
        if not normalized_url:
            continue
        asset = assets_by_url.get(normalized_url)
        if asset is None:
            missing.append(
                {
                    "source_url": source_url,
                    "page_references": sorted(page_references),
                    "reason": "Referenced asset was not found in the capture manifest.",
                }
            )
            continue
        asset_type = manifest_asset_type(asset.get("content_type") or "")
        if asset_type is None or "woocommerce" in (asset.get("path") or ""):
            unsupported.append(
                {
                    "source_url": asset.get("url") or source_url,
                    "page_references": sorted(page_references),
                    "content_type": asset.get("content_type"),
                    "reason": "Asset type or source path is excluded from migrated staging copy.",
                }
            )
            continue
        source_path = capture_root / (asset.get("path") or "")
        if not source_path.is_file():
            missing.append(
                {
                    "source_url": asset.get("url") or source_url,
                    "page_references": sorted(page_references),
                    "reason": f"Captured asset file is missing: {asset.get('path')}",
                }
            )
            continue

        dest_rel = migrated_asset_path(normalized_url)
        previous_url = destination_paths.get(dest_rel)
        if previous_url and previous_url != normalized_url:
            duplicate_destinations.append(
                {
                    "path": dest_rel,
                    "source_url": normalized_url,
                    "duplicate_of": previous_url,
                }
            )
            continue
        destination_paths[dest_rel] = normalized_url
        dest_path = root / dest_rel
        asset_bytes = int(asset.get("bytes") or source_path.stat().st_size)
        if asset_bytes > OVERSIZED_ASSET_BYTES:
            oversized.append(
                {
                    "path": dest_rel,
                    "source_url": asset.get("url") or source_url,
                    "page_references": sorted(page_references),
                    "bytes": asset_bytes,
                    "threshold": OVERSIZED_ASSET_BYTES,
                }
            )
        if dest_path.exists():
            skipped_existing.append({"path": dest_rel, "source_url": asset.get("url") or source_url})
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)
            copied.append(
                {
                    "path": dest_rel,
                    "source_url": asset.get("url") or source_url,
                    "page_references": sorted(page_references),
                    "bytes": asset_bytes,
                }
            )
            total_bytes += asset_bytes
        manifest_records.append(
            {
                "id": f"migrated-{sha256(normalized_url.encode()).hexdigest()[:12]}",
                "path": dest_rel,
                "type": asset_type,
                "usage": [MIGRATED_ASSET_USAGE],
                "required": True,
                "alt": None,
            }
        )

    manifest_updated = merge_asset_manifest(root, manifest_records)
    return {
        "referenced": len(references),
        "copied": len(copied),
        "skipped_existing": len(skipped_existing),
        "missing": missing,
        "oversized": oversized,
        "unsupported": unsupported,
        "duplicates": duplicate_destinations,
        "total_bytes": total_bytes,
        "manifest_records": len(manifest_records),
        "manifest_updated": manifest_updated,
        "copied_files": copied,
    }


def capture_assets_by_url(assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for asset in assets:
        normalized = normalize_asset_url(asset.get("url") or "")
        if normalized:
            by_url[normalized] = asset
    return by_url


def extract_content_asset_references(root: Path) -> dict[str, set[str]]:
    references: dict[str, set[str]] = {}
    for directory, key in ((root / "content" / "pages", "page"), (root / "content" / "posts", "post")):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text()) or {}
            html = ((data.get(key) or {}).get("content_html") or "")
            for raw_reference in asset_references_from_html(html):
                normalized = normalize_asset_url(raw_reference)
                if normalized:
                    references.setdefault(normalized, set()).add(str(path.relative_to(root)))
    return references


def asset_references_from_html(html: str) -> set[str]:
    references: set[str] = set()
    for match in ASSET_REFERENCE_RE.findall(html):
        raw = next((part for part in match if part), "")
        for reference in split_asset_reference(raw):
            if "/wp-content/" in reference:
                references.add(reference)
    return references


def split_asset_reference(raw: str) -> list[str]:
    value = unescape(raw).strip().strip("\"'")
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
    if not parsed.scheme or not parsed.netloc or not parsed.path:
        return None
    return urlunparse((parsed.scheme, parsed.netloc.lower(), unquote(parsed.path), "", "", ""))


def manifest_asset_type(content_type: str) -> str | None:
    for asset_type, prefixes in SUPPORTED_ASSET_TYPES.items():
        if content_type.startswith(prefixes):
            return asset_type
    return None


def migrated_asset_path(source_url: str) -> str:
    parsed = urlparse(source_url)
    basename = safe_filename(Path(unquote(parsed.path)).name or "asset")
    digest = sha256(source_url.encode()).hexdigest()[:12]
    return f"site/public/assets/migrated/{digest}-{basename}"


def safe_filename(value: str) -> str:
    stem = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-")
    return stem or "asset"


def merge_asset_manifest(root: Path, generated_records: list[dict[str, Any]]) -> bool:
    if not generated_records:
        return False
    manifest_path = root / "content" / "assets" / "manifest.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text()) or {}
    else:
        manifest = {"assets": []}
    assets = manifest.setdefault("assets", [])
    existing_ids = {asset.get("id") for asset in assets if isinstance(asset, dict)}
    updated = False
    for record in sorted(generated_records, key=lambda item: item["id"]):
        if record["id"] in existing_ids:
            continue
        assets.append(record)
        existing_ids.add(record["id"])
        updated = True
    if updated:
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False))
    return updated


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
