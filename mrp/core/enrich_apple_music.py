from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.core.apple_music_client import AppleMusicClient, extract_artist_id, strip_tracking_params
from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.release import slugify

DEFAULT_DELAY_SECONDS = 1.0
COLLECTION_SUFFIX_PATTERN = re.compile(r"\s*-\s*(single|ep)$", re.IGNORECASE)


def _title_key(title: str) -> str:
    return slugify(COLLECTION_SUFFIX_PATTERN.sub("", title or ""))


def _load_records(directory: Path, key: str) -> list[tuple[Path, dict[str, Any], dict[str, Any]]]:
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(p for p in directory.glob("*") if p.suffix in {".yaml", ".yml", ".json"}):
        data = load_structured_record(path)
        record = data.get(key)
        if isinstance(record, dict):
            records.append((path, data, record))
    return records


def enrich_apple_music(
    repo: str | Path,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    dry_run: bool = False,
    client: AppleMusicClient | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    apple = client or AppleMusicClient()

    artists = _load_records(root / "content" / "artists", "artist")
    releases = _load_records(root / "content" / "releases", "release")

    releases_by_artist: dict[str, list[tuple[Path, dict[str, Any], dict[str, Any]]]] = {}
    for entry in releases:
        releases_by_artist.setdefault(entry[2].get("artist_id", ""), []).append(entry)

    patched: list[dict[str, Any]] = []
    tracks_patched = 0
    skipped_no_apple_artist_link = 0
    artists_checked = 0
    unmatched_releases: list[str] = []
    errors: list[str] = []
    made_a_call = False

    for artist_path, _artist_data, artist in artists:
        artist_url = (artist.get("links") or {}).get("apple_music")
        if not artist_url:
            skipped_no_apple_artist_link += 1
            continue

        artist_releases = releases_by_artist.get(artist.get("id", ""), [])
        if not artist_releases:
            continue

        artist_id = extract_artist_id(artist_url)
        if not artist_id:
            errors.append(f"{artist_path.relative_to(root)}: could not parse Apple artist id from {artist_url}")
            continue

        if made_a_call:
            time.sleep(delay_seconds)
        made_a_call = True
        artists_checked += 1

        try:
            albums = apple.get_albums(artist_id)
        except Exception as exc:  # noqa: BLE001 - one artist's failure shouldn't abort the batch
            errors.append(f"{artist_path.relative_to(root)}: {exc}")
            continue

        albums_by_key = {_title_key(album.get("collectionName") or ""): album for album in albums}

        for release_path, release_data, release in artist_releases:
            album = albums_by_key.get(_title_key(release.get("title") or ""))
            if not album:
                unmatched_releases.append(str(release_path.relative_to(root)))
                continue

            added: dict[str, str] = {}
            target_links = release.setdefault("links", {})
            if not target_links.get("apple_music") and album.get("collectionViewUrl"):
                target_links["apple_music"] = strip_tracking_params(album["collectionViewUrl"])
                added["release.apple_music"] = target_links["apple_music"]

            tracks = release.get("tracks")
            if isinstance(tracks, list) and len(tracks) > 1 and (album.get("trackCount") or 0) > 1:
                time.sleep(delay_seconds)
                try:
                    apple_tracks = apple.get_tracks(album["collectionId"])
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{release_path.relative_to(root)}: {exc}")
                    apple_tracks = []
                tracks_by_key = {_title_key(t.get("trackName") or ""): t for t in apple_tracks}
                for track in tracks:
                    if not isinstance(track, dict):
                        continue
                    apple_track = tracks_by_key.get(_title_key(track.get("title") or ""))
                    if not apple_track or not apple_track.get("trackViewUrl"):
                        continue
                    track_links = track.setdefault("links", {})
                    if not track_links.get("apple_music"):
                        track_links["apple_music"] = strip_tracking_params(apple_track["trackViewUrl"])
                        added[f"track:{track.get('slug')}.apple_music"] = track_links["apple_music"]
                        tracks_patched += 1

            if not added:
                continue

            patched.append({"path": str(release_path.relative_to(root)), "added": added})
            if not dry_run:
                release_path.write_text(serialize_structured_record(release_path, release_data))

    generated_at = now_iso()
    report = {
        "command": "enrich-apple-music",
        "status": "passed",
        "repo": str(root),
        "dry_run": dry_run,
        "generated_at": generated_at,
        "delay_seconds": delay_seconds,
        "summary": {
            "artists_scanned": len(artists),
            "artists_checked": artists_checked,
            "skipped_no_apple_artist_link": skipped_no_apple_artist_link,
            "releases_patched": len(patched),
            "tracks_patched": tracks_patched,
            "unmatched_releases": len(unmatched_releases),
            "errors": len(errors),
        },
        "patched": patched,
        "unmatched_release_paths": unmatched_releases,
        "errors": errors,
    }
    if not dry_run:
        report_path = root / "reports" / "enrichment" / f"{generated_at.replace('-', '').replace(':', '')}-apple-music.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        report["report_path"] = str(report_path.relative_to(root))
    return report


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_enrich_apple_music(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "Enrich-apple-music completed" + (" (dry run)" if report["dry_run"] else ""),
        f"Artists scanned: {summary['artists_scanned']} (with Apple Music link: {summary['artists_checked']})",
        f"Releases patched: {summary['releases_patched']}",
        f"Tracks patched: {summary['tracks_patched']}",
        f"Skipped (artist has no Apple Music link): {summary['skipped_no_apple_artist_link']}",
        f"Unmatched releases (no Apple album title match): {summary['unmatched_releases']}",
        f"Errors: {summary['errors']}",
    ]
    if report.get("report_path"):
        lines.append(f"Report: {report['report_path']}")
    return "\n".join(lines)
