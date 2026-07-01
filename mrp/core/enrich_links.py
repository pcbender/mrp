from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.odesli_client import OdesliClient, OdesliRateLimitedError

DEFAULT_DELAY_SECONDS = 1.0
CONSECUTIVE_RATE_LIMIT_ABORT_THRESHOLD = 3

# Odesli platform key -> our release.links key. Bandcamp isn't matched by
# Odesli (it only aggregates major-DSP distribution), so it's intentionally
# absent here and stays a manual/Landr-Amuse field.
PLATFORM_MAP = {
    "appleMusic": "apple_music",
    "youtube": "youtube",
    "youtubeMusic": "youtube_music",
    "tidal": "tidal",
    "deezer": "deezer",
    "amazonMusic": "amazon_music",
    "soundcloud": "soundcloud",
    "pandora": "pandora",
}


def enrich_links(
    repo: str | Path,
    delay_seconds: float | None = None,
    dry_run: bool = False,
    client: OdesliClient | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    odesli = client or OdesliClient.from_env(repo=root)
    if delay_seconds is None:
        delay_seconds = getattr(odesli, "default_delay_seconds", DEFAULT_DELAY_SECONDS)

    releases_dir = root / "content" / "releases"
    paths = sorted(p for p in releases_dir.glob("*") if p.suffix in {".yaml", ".yml", ".json"}) if releases_dir.is_dir() else []

    patched: list[dict[str, Any]] = []
    skipped_no_spotify = 0
    skipped_no_new_links = 0
    rate_limited: list[str] = []
    errors: list[str] = []
    consecutive_rate_limited = 0
    aborted_for_rate_limit = False
    total_tracks_checked = 0
    total_tracks_patched = 0

    for index, path in enumerate(paths):
        data = load_structured_record(path)
        release = data.get("release")
        if not isinstance(release, dict):
            continue

        spotify_url = (release.get("links") or {}).get("spotify")
        if not spotify_url:
            skipped_no_spotify += 1
            continue

        # Odesli works best with track URLs. For singles, prefer the track-level
        # Spotify URL stored under song.links.spotify over the album URL.
        if release.get("model") == "song":
            song_spotify = (release.get("song", {}).get("links") or {}).get("spotify")
            if song_spotify:
                spotify_url = song_spotify

        if index > 0:
            time.sleep(delay_seconds)

        # Release-level enrichment
        release_added: dict[str, str] = {}
        try:
            payload = odesli.get_links(spotify_url)
        except OdesliRateLimitedError:
            rate_limited.append(str(path.relative_to(root)))
            consecutive_rate_limited += 1
            if consecutive_rate_limited >= CONSECUTIVE_RATE_LIMIT_ABORT_THRESHOLD:
                aborted_for_rate_limit = True
                break
            continue
        except Exception as exc:  # noqa: BLE001 - one release's failure shouldn't abort the batch
            errors.append(f"{path.relative_to(root)}: {exc}")
            consecutive_rate_limited = 0
            continue
        consecutive_rate_limited = 0

        links_by_platform = payload.get("linksByPlatform") or {}
        target_links = release.setdefault("links", {})
        for odesli_key, our_key in PLATFORM_MAP.items():
            if target_links.get(our_key):
                continue
            entry = links_by_platform.get(odesli_key)
            url = entry.get("url") if isinstance(entry, dict) else None
            if url:
                target_links[our_key] = url
                release_added[our_key] = url

        # Per-track enrichment
        tracks_patched: list[dict[str, Any]] = []
        for track in release.get("tracks") or []:
            track_spotify = (track.get("links") or {}).get("spotify")
            if not track_spotify:
                continue
            total_tracks_checked += 1
            time.sleep(delay_seconds)
            try:
                track_payload = odesli.get_links(track_spotify)
            except OdesliRateLimitedError:
                rate_limited.append(f"{path.relative_to(root)}#track{track.get('number')}")
                consecutive_rate_limited += 1
                if consecutive_rate_limited >= CONSECUTIVE_RATE_LIMIT_ABORT_THRESHOLD:
                    aborted_for_rate_limit = True
                    break
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.relative_to(root)}#track{track.get('number')}: {exc}")
                consecutive_rate_limited = 0
                continue
            consecutive_rate_limited = 0

            track_links_by_platform = track_payload.get("linksByPlatform") or {}
            track_links = track.setdefault("links", {})
            track_added: dict[str, str] = {}
            for odesli_key, our_key in PLATFORM_MAP.items():
                if track_links.get(our_key):
                    continue
                entry = track_links_by_platform.get(odesli_key)
                url = entry.get("url") if isinstance(entry, dict) else None
                if url:
                    track_links[our_key] = url
                    track_added[our_key] = url
            if track_added:
                tracks_patched.append({"number": track.get("number"), "title": track.get("title"), "added": track_added})

        if aborted_for_rate_limit:
            break

        if not release_added and not tracks_patched:
            skipped_no_new_links += 1
            continue

        total_tracks_patched += len(tracks_patched)
        patched.append({"path": str(path.relative_to(root)), "added": release_added, "tracks_patched": tracks_patched})
        if not dry_run:
            path.write_text(serialize_structured_record(path, data))

    generated_at = now_iso()
    report = {
        "command": "enrich-links",
        "status": "rate_limited" if aborted_for_rate_limit else "passed",
        "repo": str(root),
        "dry_run": dry_run,
        "generated_at": generated_at,
        "delay_seconds": delay_seconds,
        "used_api_key": getattr(odesli, "has_key", False),
        "aborted_for_rate_limit": aborted_for_rate_limit,
        "summary": {
            "releases_scanned": len(paths),
            "releases_checked": sum([len(patched), skipped_no_new_links, len(rate_limited), len(errors)]),
            "releases_patched": len(patched),
            "skipped_no_spotify_link": skipped_no_spotify,
            "skipped_no_new_links": skipped_no_new_links,
            "tracks_checked": total_tracks_checked,
            "tracks_patched": total_tracks_patched,
            "rate_limited": len(rate_limited),
            "errors": len(errors),
        },
        "patched": patched,
        "rate_limited_paths": rate_limited,
        "errors": errors,
    }
    if not dry_run:
        report_path = root / "reports" / "enrichment" / f"{generated_at.replace('-', '').replace(':', '')}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        report["report_path"] = str(report_path.relative_to(root))
    return report


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_enrich_links(report: dict[str, Any]) -> str:
    summary = report["summary"]
    title = "Enrich-links " + ("aborted (rate-limited)" if report["aborted_for_rate_limit"] else "completed")
    lines = [
        title + (" (dry run)" if report["dry_run"] else ""),
        f"Odesli API key: {'used' if report.get('used_api_key') else 'not set (anonymous, 10 req/min cap)'}"
        f" -- delay: {report.get('delay_seconds')}s",
        f"Releases scanned: {summary['releases_scanned']} (checked: {summary['releases_checked']})",
        f"Releases patched: {summary['releases_patched']}",
        f"Tracks checked: {summary['tracks_checked']} / patched: {summary['tracks_patched']}",
        f"Skipped (no spotify link): {summary['skipped_no_spotify_link']}",
        f"Skipped (no new links found): {summary['skipped_no_new_links']}",
        f"Rate-limited (uncertain, not real misses): {summary['rate_limited']}",
        f"Errors: {summary['errors']}",
    ]
    if report.get("report_path"):
        lines.append(f"Report: {report['report_path']}")
    return "\n".join(lines)
