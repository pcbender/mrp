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
}


def enrich_links(
    repo: str | Path,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    dry_run: bool = False,
    client: OdesliClient | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    odesli = client or OdesliClient()

    releases_dir = root / "content" / "releases"
    paths = sorted(p for p in releases_dir.glob("*") if p.suffix in {".yaml", ".yml", ".json"}) if releases_dir.is_dir() else []

    patched: list[dict[str, Any]] = []
    skipped_no_spotify = 0
    skipped_no_new_links = 0
    rate_limited: list[str] = []
    errors: list[str] = []
    consecutive_rate_limited = 0
    aborted_for_rate_limit = False

    for index, path in enumerate(paths):
        data = load_structured_record(path)
        release = data.get("release")
        if not isinstance(release, dict):
            continue

        spotify_url = (release.get("links") or {}).get("spotify")
        if not spotify_url:
            skipped_no_spotify += 1
            continue

        if index > 0:
            time.sleep(delay_seconds)

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
        added: dict[str, str] = {}
        for odesli_key, our_key in PLATFORM_MAP.items():
            if target_links.get(our_key):
                continue
            entry = links_by_platform.get(odesli_key)
            url = entry.get("url") if isinstance(entry, dict) else None
            if url:
                target_links[our_key] = url
                added[our_key] = url

        if not added:
            skipped_no_new_links += 1
            continue

        patched.append({"path": str(path.relative_to(root)), "added": added})
        if not dry_run:
            path.write_text(serialize_structured_record(path, data))

    generated_at = now_iso()
    report = {
        "command": "enrich-links",
        "status": "rate_limited" if aborted_for_rate_limit else "passed",
        "repo": str(root),
        "dry_run": dry_run,
        "generated_at": generated_at,
        "aborted_for_rate_limit": aborted_for_rate_limit,
        "summary": {
            "releases_scanned": len(paths),
            "releases_checked": sum([len(patched), skipped_no_new_links, len(rate_limited), len(errors)]),
            "releases_patched": len(patched),
            "skipped_no_spotify_link": skipped_no_spotify,
            "skipped_no_new_links": skipped_no_new_links,
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
        f"Releases scanned: {summary['releases_scanned']} (checked: {summary['releases_checked']})",
        f"Releases patched: {summary['releases_patched']}",
        f"Skipped (no spotify link): {summary['skipped_no_spotify_link']}",
        f"Skipped (no new links found): {summary['skipped_no_new_links']}",
        f"Rate-limited (uncertain, not real misses): {summary['rate_limited']}",
        f"Errors: {summary['errors']}",
    ]
    if report.get("report_path"):
        lines.append(f"Report: {report['report_path']}")
    return "\n".join(lines)
