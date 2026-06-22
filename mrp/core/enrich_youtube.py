from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.release import slugify
from mrp.core.youtube_client import YouTubeClient, extract_channel_id

DEFAULT_DELAY_SECONDS = 0.2
VIDEO_SUFFIX_PATTERN = re.compile(
    r"\s*[\(\[]\s*(official\s+)?(music\s+)?(video|audio|lyric(s)?\s+video|visualizer)\s*[\)\]]\s*$",
    re.IGNORECASE,
)


def _title_key(title: str) -> str:
    return slugify(VIDEO_SUFFIX_PATTERN.sub("", title or ""))


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


def enrich_youtube(
    repo: str | Path,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    dry_run: bool = False,
    client: YouTubeClient | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    youtube = client or YouTubeClient.from_env(repo=root)
    if youtube is None:
        return {
            "command": "enrich-youtube",
            "status": "failed",
            "repo": str(root),
            "dry_run": dry_run,
            "generated_at": now_iso(),
            "message": "GOOGLE_SERVICE_API_KEY not set (environment or .env).",
        }

    artists = _load_records(root / "content" / "artists", "artist")
    releases = _load_records(root / "content" / "releases", "release")

    releases_by_artist: dict[str, list[tuple[Path, dict[str, Any], dict[str, Any]]]] = {}
    for entry in releases:
        releases_by_artist.setdefault(entry[2].get("artist_id", ""), []).append(entry)

    patched: list[dict[str, Any]] = []
    tracks_patched = 0
    skipped_no_youtube_channel = 0
    artists_checked = 0
    fully_unmatched_releases: list[str] = []
    errors: list[str] = []
    made_a_call = False

    for artist_path, _artist_data, artist in artists:
        channel_url = (artist.get("links") or {}).get("youtube")
        if not channel_url:
            skipped_no_youtube_channel += 1
            continue

        artist_releases = releases_by_artist.get(artist.get("id", ""), [])
        if not artist_releases:
            continue

        channel_id = extract_channel_id(channel_url)
        if not channel_id:
            errors.append(f"{artist_path.relative_to(root)}: could not parse channel id from {channel_url}")
            continue

        if made_a_call:
            time.sleep(delay_seconds)
        made_a_call = True
        artists_checked += 1

        try:
            uploads_playlist_id = youtube.get_uploads_playlist_id(channel_id)
            videos = youtube.get_playlist_videos(uploads_playlist_id) if uploads_playlist_id else []
        except Exception as exc:  # noqa: BLE001 - one artist's failure shouldn't abort the batch
            errors.append(f"{artist_path.relative_to(root)}: {exc}")
            continue

        videos_by_key = {_title_key(v.get("title") or ""): v for v in videos}

        for release_path, release_data, release in artist_releases:
            added: dict[str, str] = {}

            target_links = release.setdefault("links", {})
            video = videos_by_key.get(_title_key(release.get("title") or ""))
            if video:
                if not target_links.get("youtube"):
                    target_links["youtube"] = f"https://www.youtube.com/watch?v={video['videoId']}"
                    added["release.youtube"] = target_links["youtube"]
                if not target_links.get("youtube_music"):
                    target_links["youtube_music"] = f"https://music.youtube.com/watch?v={video['videoId']}"
                    added["release.youtube_music"] = target_links["youtube_music"]

            tracks = release.get("tracks")
            if isinstance(tracks, list):
                for track in tracks:
                    if not isinstance(track, dict):
                        continue
                    track_video = videos_by_key.get(_title_key(track.get("title") or ""))
                    if not track_video:
                        continue
                    track_links = track.setdefault("links", {})
                    track_touched = False
                    if not track_links.get("youtube"):
                        track_links["youtube"] = f"https://www.youtube.com/watch?v={track_video['videoId']}"
                        added[f"track:{track.get('slug')}.youtube"] = track_links["youtube"]
                        track_touched = True
                    if not track_links.get("youtube_music"):
                        track_links["youtube_music"] = f"https://music.youtube.com/watch?v={track_video['videoId']}"
                        added[f"track:{track.get('slug')}.youtube_music"] = track_links["youtube_music"]
                        track_touched = True
                    if track_touched:
                        tracks_patched += 1

            if not added:
                fully_unmatched_releases.append(str(release_path.relative_to(root)))
                continue

            patched.append({"path": str(release_path.relative_to(root)), "added": added})
            if not dry_run:
                release_path.write_text(serialize_structured_record(release_path, release_data))

    generated_at = now_iso()
    report = {
        "command": "enrich-youtube",
        "status": "passed",
        "repo": str(root),
        "dry_run": dry_run,
        "generated_at": generated_at,
        "delay_seconds": delay_seconds,
        "summary": {
            "artists_scanned": len(artists),
            "artists_checked": artists_checked,
            "skipped_no_youtube_channel": skipped_no_youtube_channel,
            "releases_patched": len(patched),
            "tracks_patched": tracks_patched,
            "fully_unmatched_releases": len(fully_unmatched_releases),
            "errors": len(errors),
        },
        "patched": patched,
        "fully_unmatched_release_paths": fully_unmatched_releases,
        "errors": errors,
    }
    if not dry_run:
        report_path = root / "reports" / "enrichment" / f"{generated_at.replace('-', '').replace(':', '')}-youtube.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        report["report_path"] = str(report_path.relative_to(root))
    return report


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_enrich_youtube(report: dict[str, Any]) -> str:
    if report["status"] == "failed":
        return f"Enrich-youtube failed: {report.get('message')}"
    summary = report["summary"]
    lines = [
        "Enrich-youtube completed" + (" (dry run)" if report["dry_run"] else ""),
        f"Artists scanned: {summary['artists_scanned']} (with a YouTube channel: {summary['artists_checked']})",
        f"Releases patched: {summary['releases_patched']}",
        f"Tracks patched: {summary['tracks_patched']}",
        f"Skipped (artist has no YouTube channel link): {summary['skipped_no_youtube_channel']}",
        f"Fully unmatched releases (no video title match at all): {summary['fully_unmatched_releases']}",
        f"Errors: {summary['errors']}",
    ]
    if report.get("report_path"):
        lines.append(f"Report: {report['report_path']}")
    return "\n".join(lines)
