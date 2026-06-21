from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from mrp.core.import_site import write_json, write_yaml
from mrp.core.release import slugify
from mrp.core.spotify_client import SpotifyClient

DEFAULT_ROSTER = Path("content/import-review/spotify-roster.yaml")
PATCHABLE_RELEASE_FIELDS = ("upc", "release_date", "label")


def import_spotify(
    repo: str | Path,
    roster: str | Path = DEFAULT_ROSTER,
    download_covers: bool = False,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    roster_path = Path(roster)
    if not roster_path.is_absolute():
        roster_path = root / roster_path
    roster_entries = (yaml.safe_load(roster_path.read_text(encoding="utf-8")) or {}).get("artists", [])

    spotify = client or SpotifyClient.from_env(repo=root)
    existing_releases = load_existing_releases(root)

    artist_candidates: list[dict[str, Any]] = []
    release_candidates: list[dict[str, Any]] = []
    asset_candidates: list[dict[str, Any]] = []
    matched_existing = 0

    for entry in roster_entries:
        artist_id_hint = entry.get("artist_id")
        spotify_url = entry.get("spotify_url")
        if not spotify_url and artist_id_hint:
            spotify_url = existing_artist_spotify_url(root, artist_id_hint)
        if not spotify_url:
            raise ValueError(f"No spotify_url available for roster entry: {entry!r}")

        spotify_artist_id = artist_id_from_url(spotify_url)
        artist_payload = spotify.get_artist(spotify_artist_id)
        artist_id = artist_id_hint or slugify(artist_payload.get("name") or spotify_artist_id)
        is_known = artist_record_path(root, artist_id) is not None

        artist_candidates.append(build_artist_candidate(artist_id, artist_payload, is_known))

        for album in dedupe_albums(spotify.get_artist_albums(spotify_artist_id), spotify_artist_id):
            full_album = spotify.get_album(album["id"])
            release_slug = slugify(full_album.get("name") or album["id"])
            mapped = build_release_candidate(artist_id, release_slug, full_album, spotify)

            match = match_existing_release(existing_releases, mapped["release"])
            if match is not None:
                patch = diff_patch(match["data"], mapped["release"])
                if patch:
                    matched_existing += 1
                    release_candidates.append(
                        {
                            "release": {
                                "artist_id": artist_id,
                                "existing_path": match["path"],
                                "review_status": "matched_existing",
                                "proposed_patch": patch,
                                "notes": [
                                    "Backfilling fields missing from the existing record; not auto-applied.",
                                ],
                            }
                        }
                    )
                continue

            release_candidates.append({"release": mapped["release"]})
            if mapped["cover_url"]:
                if download_covers:
                    asset_candidates.append(
                        download_cover(root, artist_id, release_slug, mapped["cover_url"], spotify)
                    )
                else:
                    asset_candidates.append(
                        {
                            "url": mapped["cover_url"],
                            "artist_id": artist_id,
                            "release_slug": release_slug,
                            "review_status": "needs_review",
                        }
                    )

    review_dir = root / "content" / "import-review"
    review_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(review_dir / "spotify-artists.yaml", {"candidates": artist_candidates})
    write_yaml(review_dir / "spotify-releases.yaml", {"candidates": release_candidates})
    write_yaml(review_dir / "spotify-assets.yaml", {"candidates": asset_candidates})

    generated_at = now_iso()
    report = {
        "command": "import-spotify",
        "status": "passed",
        "repo": str(root),
        "generated_at": generated_at,
        "summary": {
            "artist_candidates": len(artist_candidates),
            "release_candidates": len(release_candidates) - matched_existing,
            "matched_existing": matched_existing,
            "asset_candidates": len(asset_candidates),
        },
        "outputs": [
            "content/import-review/spotify-artists.yaml",
            "content/import-review/spotify-releases.yaml",
            "content/import-review/spotify-assets.yaml",
        ],
        "notes": [
            "Spotify-derived candidates require human/agent review before promotion.",
            "Credits, catalog_number, publisher, and non-Spotify links are not available "
            "from Spotify and must be filled in manually.",
        ],
    }
    report["report_path"] = report_path(root, generated_at)
    write_json(root / report["report_path"], report)
    return report


def build_artist_candidate(artist_id: str, artist: dict[str, Any], is_known: bool) -> dict[str, Any]:
    images = artist.get("images") or []
    candidate: dict[str, Any] = {
        "id": artist_id,
        "name": artist.get("name"),
        "image_source": images[0]["url"] if images else None,
        "visibility": "draft",
        "links": {"spotify": (artist.get("external_urls") or {}).get("spotify")},
        "review_status": "known_artist" if is_known else "needs_review",
        "notes": (
            ["Matches an existing content/artists record; only links.spotify is authoritative from Spotify."]
            if is_known
            else [
                "New artist, not present in content/artists/.",
                "bio_short, bio_long, type, default_publisher, and non-Spotify links "
                "need manual/collaborative drafting before promotion.",
            ]
        ),
    }
    return {"artist": candidate}


def build_release_candidate(
    artist_id: str,
    slug: str,
    album: dict[str, Any],
    spotify: SpotifyClient,
) -> dict[str, Any]:
    simplified_tracks = album.get("tracks", {}).get("items", [])
    full_tracks = {t["id"]: t for t in spotify.get_tracks([t["id"] for t in simplified_tracks])} if simplified_tracks else {}
    tracks = [
        build_track(index + 1, full_tracks.get(track["id"], track))
        for index, track in enumerate(simplified_tracks)
    ]

    release_date = album.get("release_date")
    date_precision = album.get("release_date_precision")
    if date_precision != "day":
        release_date = None

    model = "song" if len(tracks) == 1 else "album"
    release_type = "single" if model == "song" else ("ep" if len(tracks) <= 6 else "album")

    notes = [
        "Imported from Spotify catalog; credits, catalog_number, publisher, and "
        "non-Spotify links need manual fill.",
    ]
    if release_date is None and date_precision is not None:
        notes.append(f"Spotify release_date precision was '{date_precision}'; confirm the exact date manually.")

    release: dict[str, Any] = {
        "id": slug,
        "slug": slug,
        "title": album.get("name"),
        "artist_id": artist_id,
        "model": model,
        "release_type": release_type,
        "status": "draft",
        "release_date": release_date,
        "label": album.get("label"),
        "publisher": None,
        "upc": (album.get("external_ids") or {}).get("upc"),
        "catalog_number": None,
        "cover_image": None,
        "links": {"spotify": (album.get("external_urls") or {}).get("spotify")},
        "review_status": "needs_review",
        "notes": notes,
    }
    if model == "song":
        release["song"] = tracks[0]
    else:
        release["tracks"] = tracks

    images = album.get("images") or []
    return {"release": release, "cover_url": images[0]["url"] if images else None}


def build_track(number: int, track: dict[str, Any]) -> dict[str, Any]:
    name = track.get("name") or f"Track {number}"
    return {
        "number": number,
        "title": name,
        "slug": slugify(name),
        "isrc": (track.get("external_ids") or {}).get("isrc"),
        "duration": format_duration(track.get("duration_ms")),
        "explicit": bool(track.get("explicit", False)),
        "preview_audio": track.get("preview_url"),
        "links": {"spotify": (track.get("external_urls") or {}).get("spotify")},
    }


def dedupe_albums(albums: list[dict[str, Any]], primary_artist_id: str) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str | None], dict[str, Any]] = {}
    for album in albums:
        artists = album.get("artists") or []
        if not artists or artists[0].get("id") != primary_artist_id:
            continue
        key = ((album.get("name") or "").strip().lower(), album.get("release_date"))
        seen.setdefault(key, album)
    return sorted(seen.values(), key=lambda album: album.get("release_date") or "")


def load_existing_releases(root: Path) -> list[dict[str, Any]]:
    releases_dir = root / "content" / "releases"
    records: list[dict[str, Any]] = []
    if not releases_dir.is_dir():
        return records
    for path in sorted(releases_dir.glob("*")):
        if path.suffix not in {".yaml", ".yml", ".json"}:
            continue
        release = load_structured(path).get("release")
        if isinstance(release, dict):
            records.append({"path": str(path.relative_to(root)), "data": release})
    return records


def match_existing_release(existing: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any] | None:
    candidate_upc = candidate.get("upc")
    candidate_isrcs = release_isrcs(candidate)
    candidate_key = (candidate.get("artist_id"), normalize_title(candidate.get("title")))
    for record in existing:
        data = record["data"]
        if candidate_upc and data.get("upc") == candidate_upc:
            return record
        if candidate_isrcs and candidate_isrcs & release_isrcs(data):
            return record
        if (data.get("artist_id"), normalize_title(data.get("title"))) == candidate_key:
            return record
    return None


def diff_patch(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for field in PATCHABLE_RELEASE_FIELDS:
        if not existing.get(field) and candidate.get(field):
            patch[field] = candidate[field]

    existing_song = existing.get("song")
    candidate_song = candidate.get("song")
    if isinstance(existing_song, dict) and not existing_song.get("isrc") and isinstance(candidate_song, dict):
        if candidate_song.get("isrc"):
            patch["song_isrc"] = candidate_song["isrc"]

    candidate_tracks = candidate.get("tracks") or []
    track_patches = []
    for index, existing_track in enumerate(existing.get("tracks") or []):
        if existing_track.get("isrc"):
            continue
        match = next(
            (t for t in candidate_tracks if normalize_title(t.get("title")) == normalize_title(existing_track.get("title"))),
            None,
        )
        if match and match.get("isrc"):
            track_patches.append({"index": index, "title": existing_track.get("title"), "isrc": match["isrc"]})
    if track_patches:
        patch["tracks_isrc"] = track_patches

    return patch


def release_isrcs(release: dict[str, Any]) -> set[str]:
    isrcs: set[str] = set()
    song = release.get("song")
    if isinstance(song, dict) and song.get("isrc"):
        isrcs.add(song["isrc"])
    for track in release.get("tracks") or []:
        if track.get("isrc"):
            isrcs.add(track["isrc"])
    return isrcs


def download_cover(root: Path, artist_id: str, slug: str, url: str, spotify: SpotifyClient) -> dict[str, Any]:
    content = spotify.download(url)
    rel_path = Path("content/import-review/spotify-assets") / artist_id / slug / "cover.jpg"
    abs_path = root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return {
        "url": url,
        "path": str(rel_path),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "artist_id": artist_id,
        "release_slug": slug,
        "review_status": "needs_review",
    }


def artist_record_path(root: Path, artist_id: str) -> Path | None:
    for suffix in (".yaml", ".yml", ".json"):
        path = root / "content" / "artists" / f"{artist_id}{suffix}"
        if path.is_file():
            return path
    return None


def existing_artist_spotify_url(root: Path, artist_id: str) -> str | None:
    path = artist_record_path(root, artist_id)
    if path is None:
        return None
    artist = load_structured(path).get("artist") or {}
    return (artist.get("links") or {}).get("spotify")


def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def artist_id_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "artist":
        return parts[1]
    raise ValueError(f"Could not parse a Spotify artist id from URL: {url}")


def normalize_title(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def format_duration(duration_ms: int | None) -> str | None:
    if not duration_ms:
        return None
    total_seconds = round(duration_ms / 1000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def report_path(root: Path, generated_at: str) -> str:
    timestamp = generated_at.replace("-", "").replace(":", "")
    return str((root / "reports" / "import" / f"{timestamp}-spotify.json").relative_to(root))


def format_import_spotify(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            "Import-spotify completed",
            f"Artist candidates: {summary['artist_candidates']}",
            f"Release candidates: {summary['release_candidates']}",
            f"Matched existing (patch proposals): {summary['matched_existing']}",
            f"Asset candidates: {summary['asset_candidates']}",
            f"Report: {report['report_path']}",
        ]
    )
