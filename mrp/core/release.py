from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from mrp.core.validate import validate_repository


def create_release(
    repo: str | Path,
    artist: str,
    title: str,
    release_type: str | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    release_type = release_type or "single"
    slug = slugify(title)
    release_path = root / "content" / "releases" / f"{slug}.yaml"
    asset_dir = root / "assets" / "releases" / slug

    result = {
        "command": "release create",
        "repo": str(root),
        "artist": artist,
        "title": title,
        "release_type": release_type,
        "slug": slug,
        "release_path": str(release_path.relative_to(root)),
        "asset_dir": str(asset_dir.relative_to(root)),
    }

    if not artist or not title:
        result.update(failed("artist and title are required."))
        return result
    if not (root / "content" / "artists" / f"{artist}.json").exists() and not (
        root / "content" / "artists" / f"{artist}.yaml"
    ).exists():
        result.update(failed(f"Unknown artist: {artist}"))
        return result
    if release_path.exists():
        result.update(failed(f"Release already exists: {release_path.relative_to(root)}"))
        return result

    release_path.parent.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / ".gitkeep").touch()
    release_path.write_text(yaml.safe_dump(release_record(artist, title, slug, release_type), sort_keys=False))

    validation = validate_repository(root, release=slug)
    result["validation_report_path"] = validation["report_path"]
    if validation["status"] != "passed":
        result["validation_errors"] = validation["errors"]
        result.update(failed("Generated release did not pass validation."))
        return result

    result["status"] = "created"
    return result


def release_record(artist: str, title: str, slug: str, release_type: str) -> dict[str, Any]:
    model = "song" if release_type == "single" else "album"
    release: dict[str, Any] = {
        "id": slug,
        "slug": slug,
        "title": title,
        "artist_id": artist,
        "model": model,
        "release_type": release_type,
        "status": "draft",
        "release_date": None,
        "label": "Maricopa Records",
        "publisher": "Maricopa Publishing",
        "upc": None,
        "catalog_number": None,
        "cover_image": f"assets/releases/{slug}/cover.jpg",
        "hero_image": None,
        "summary": "",
        "description": "",
        "credits": {
            "primary_artist": artist,
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
            "title": f"{title} by {artist}",
            "description": f"{title} by {artist} on Maricopa Records.",
        },
        "automation": {"allow_auto_publish": False},
    }
    if model == "song":
        release["song"] = track(title, slug, None)
    else:
        count = 2 if release_type == "ep" else 1
        release["tracks"] = [track(f"Track {index}", f"track-{index}", index) for index in range(1, count + 1)]
    return {"release": release}


def track(title: str, slug: str, number: int | None) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "slug": slug,
        "isrc": None,
        "duration": None,
        "explicit": False,
        "preview_audio": None,
        "lyrics_text": None,
        "lyrics_source": None,
    }


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "release"


def failed(message: str) -> dict[str, str]:
    return {
        "status": "failed",
        "message": message,
    }


def format_release_create(result: dict[str, Any]) -> str:
    lines = [
        f"Release create {result['status']}",
        f"Release: {result['release_path']}",
        f"Assets: {result['asset_dir']}",
    ]
    if result.get("message"):
        lines.append(result["message"])
    return "\n".join(lines)
