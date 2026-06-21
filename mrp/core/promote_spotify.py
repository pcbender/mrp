from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from mrp.core.migrate_site import existing_record_path, load_structured_record, serialize_structured_record
from mrp.core.spotify_client import SpotifyClient

DEFAULT_ARTISTS_PATH = Path("content/import-review/spotify-artists.yaml")
DEFAULT_RELEASES_PATH = Path("content/import-review/spotify-releases.yaml")
SPOTIFY_ASSET_CACHE = Path("content/import-review/spotify-assets")
PATCHABLE_TOP_LEVEL = ("upc", "release_date", "label")


def promote_spotify(
    repo: str | Path,
    artists_path: str | Path = DEFAULT_ARTISTS_PATH,
    releases_path: str | Path = DEFAULT_RELEASES_PATH,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    artist_candidates = _read_candidates(root / artists_path)
    release_candidates = _read_candidates(root / releases_path)
    artist_names = {entry["artist"]["id"]: entry["artist"]["name"] for entry in artist_candidates}

    created_artists: list[str] = []
    created_releases: list[str] = []
    patched_releases: list[str] = []
    skipped: list[str] = []

    for entry in artist_candidates:
        artist = entry["artist"]
        if artist.get("review_status") != "needs_review":
            continue
        path = root / "content" / "artists" / f"{artist['id']}.yaml"
        if path.exists():
            skipped.append(str(path.relative_to(root)))
            continue
        image = None
        if artist.get("image_source") and client is not None:
            image = _place_artist_image(root, artist["id"], artist["image_source"], client)
        record = {
            "artist": {
                "id": artist["id"],
                "name": artist["name"],
                "sort_name": artist["name"],
                "type": None,
                "label": "Maricopa Records",
                "default_publisher": "Maricopa Publishing",
                "bio_short": None,
                "bio_long": None,
                "image": image,
                "links": {
                    "spotify": (artist.get("links") or {}).get("spotify"),
                    "apple_music": None,
                    "youtube_music": None,
                    "youtube": None,
                    "bandcamp": None,
                    "instagram": None,
                },
                "visibility": "public",
            }
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=False))
        created_artists.append(str(path.relative_to(root)))

    for entry in release_candidates:
        release = entry["release"]
        if release.get("review_status") == "matched_existing":
            patched = _apply_release_patch(root, release)
            if patched:
                patched_releases.append(patched)
            continue

        path = root / "content" / "releases" / f"{release['slug']}.yaml"
        if path.exists():
            skipped.append(str(path.relative_to(root)))
            continue

        cover_image = _place_release_cover(root, release["artist_id"], release["slug"])
        if cover_image is None:
            skipped.append(f"{release['slug']} (no cached cover art)")
            continue

        artist_name = artist_names.get(release["artist_id"], release["artist_id"])
        record: dict[str, Any] = {
            "id": release["id"],
            "slug": release["slug"],
            "title": release["title"],
            "artist_id": release["artist_id"],
            "model": release["model"],
            "release_type": release["release_type"],
            "status": "staged",
            "release_date": release.get("release_date"),
            "label": release.get("label"),
            "publisher": None,
            "upc": release.get("upc"),
            "catalog_number": None,
            "cover_image": cover_image,
            "hero_image": None,
            "summary": "",
            "description": "",
            "credits": {
                "primary_artist": artist_name,
                "songwriter": None,
                "producer": None,
                "mastering": None,
            },
            "links": release.get("links") or {"spotify": None},
            "seo": {
                "title": f"{release['title']} by {artist_name}",
                "description": f"{release['title']} by {artist_name} on Maricopa Records.",
            },
            "automation": {"allow_auto_publish": False},
        }
        if release["model"] == "song":
            record["song"] = release["song"]
        else:
            record["tracks"] = release["tracks"]

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"release": record}, sort_keys=False, allow_unicode=False))
        created_releases.append(str(path.relative_to(root)))

    return {
        "command": "promote-spotify",
        "status": "passed",
        "repo": str(root),
        "summary": {
            "artists_created": len(created_artists),
            "releases_created": len(created_releases),
            "releases_patched": len(patched_releases),
            "skipped": len(skipped),
        },
        "created_artists": created_artists,
        "created_releases": created_releases,
        "patched_releases": patched_releases,
        "skipped": skipped,
    }


def _read_candidates(path: Path) -> list[dict[str, Any]]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("candidates", [])


def _place_release_cover(root: Path, artist_id: str, slug: str) -> str | None:
    source = root / SPOTIFY_ASSET_CACHE / artist_id / slug / "cover.jpg"
    if not source.is_file():
        return None
    dest_rel = Path("site/public/assets/releases") / slug / "cover.jpg"
    dest = root / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    return f"site/public/{dest_rel.relative_to('site/public')}"


def _place_artist_image(root: Path, artist_id: str, url: str, client: SpotifyClient) -> str | None:
    try:
        content = client.download(url)
    except Exception:
        return None
    dest_rel = Path("site/public/assets/artists") / artist_id / "cover.jpg"
    dest = root / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return f"/{dest_rel.relative_to('site/public')}"


def _apply_release_patch(root: Path, release: dict[str, Any]) -> str | None:
    existing_path = root / release["existing_path"]
    if not existing_path.is_file():
        return None
    data = load_structured_record(existing_path)
    target = data.get("release")
    if not isinstance(target, dict):
        return None

    patch = release.get("proposed_patch") or {}
    changed = False
    for field in PATCHABLE_TOP_LEVEL:
        if field in patch and not target.get(field):
            target[field] = patch[field]
            changed = True

    song = target.get("song")
    if "song_isrc" in patch and isinstance(song, dict) and not song.get("isrc"):
        song["isrc"] = patch["song_isrc"]
        changed = True

    tracks = target.get("tracks") or []
    for item in patch.get("tracks_isrc", []):
        index = item["index"]
        if 0 <= index < len(tracks) and not tracks[index].get("isrc"):
            tracks[index]["isrc"] = item["isrc"]
            changed = True

    if not changed:
        return None
    existing_path.write_text(serialize_structured_record(existing_path, data))
    return str(existing_path.relative_to(root))


def format_promote_spotify(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            "Promote-spotify completed",
            f"Artists created: {summary['artists_created']}",
            f"Releases created: {summary['releases_created']}",
            f"Releases patched: {summary['releases_patched']}",
            f"Skipped: {summary['skipped']}",
        ]
    )
