from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.release import slugify
from mrp.core.spotify_client import SpotifyClient

DEFAULT_DELAY_SECONDS = 1.5

_ALBUM_ID_RE = re.compile(r"open\.spotify\.com/album/([A-Za-z0-9]+)")
_SUFFIX_RE = re.compile(r"\s*-\s*(single|ep)$", re.IGNORECASE)


def _title_key(title: str) -> str:
    return slugify(_SUFFIX_RE.sub("", title or ""))


def enrich_isrc(
    repo: str | Path,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    dry_run: bool = False,
    client: SpotifyClient | None = None,
) -> dict[str, Any]:
    root = Path(repo).resolve()
    spotify = client or SpotifyClient.from_env(repo=root)

    releases_dir = root / "content" / "releases"
    release_paths = sorted(p for p in releases_dir.glob("*.yaml") if p.is_file())

    patched: list[dict[str, Any]] = []
    skipped_no_link: list[str] = []
    unmatched_tracks: list[str] = []
    errors: list[str] = []
    made_a_call = False

    for path in release_paths:
        data = load_structured_record(path)
        rel = data.get("release", {})

        spotify_url = (rel.get("links") or {}).get("spotify", "")
        m = _ALBUM_ID_RE.search(spotify_url or "")
        if not m:
            skipped_no_link.append(path.name)
            continue

        album_id = m.group(1)

        # Collect tracks that actually need an ISRC
        is_single = rel.get("model") == "song"
        if is_single:
            song = rel.get("song") or {}
            if song.get("isrc"):
                continue  # already has one
            needs_isrc = [song]
        else:
            needs_isrc = [t for t in (rel.get("tracks") or []) if not t.get("isrc")]
            if not needs_isrc:
                continue

        # Fetch Spotify album track listing (SimplifiedTrackObjects — no ISRC yet)
        if made_a_call:
            time.sleep(delay_seconds)
        made_a_call = True

        try:
            album = spotify.get_album(album_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: get_album failed: {exc}")
            continue

        spotify_tracks = (album.get("tracks") or {}).get("items") or []
        spotify_by_key = {_title_key(t.get("name") or ""): t for t in spotify_tracks}

        added: dict[str, str] = {}

        for track in needs_isrc:
            key = _title_key(track.get("title") or "")
            sp_track = spotify_by_key.get(key)
            if not sp_track:
                unmatched_tracks.append(f"{path.name}: {track.get('title')!r}")
                continue

            spotify_track_id = sp_track.get("id")
            if not spotify_track_id:
                unmatched_tracks.append(f"{path.name}: {track.get('title')!r} (no Spotify track id)")
                continue

            time.sleep(delay_seconds)
            try:
                full_tracks = spotify.get_tracks([spotify_track_id])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.name}: get_tracks({spotify_track_id}) failed: {exc}")
                continue

            isrc = (full_tracks[0].get("external_ids") or {}).get("isrc") if full_tracks else None
            if not isrc:
                unmatched_tracks.append(f"{path.name}: {track.get('title')!r} (Spotify returned no ISRC)")
                continue

            track["isrc"] = isrc
            field = "song.isrc" if is_single else f"track:{track.get('slug')}.isrc"
            added[field] = isrc

        if not added:
            continue

        patched.append({"path": str(path.relative_to(root)), "added": added})
        if not dry_run:
            path.write_text(serialize_structured_record(path, data))

    generated_at = _now_iso()
    report = {
        "command": "enrich-isrc",
        "status": "passed",
        "repo": str(root),
        "dry_run": dry_run,
        "generated_at": generated_at,
        "delay_seconds": delay_seconds,
        "summary": {
            "releases_scanned": len(release_paths),
            "releases_patched": len(patched),
            "tracks_patched": sum(len(p["added"]) for p in patched),
            "skipped_no_spotify_link": len(skipped_no_link),
            "unmatched_tracks": len(unmatched_tracks),
            "errors": len(errors),
        },
        "patched": patched,
        "unmatched": unmatched_tracks,
        "errors": errors,
    }
    if not dry_run:
        report_path = (
            root / "reports" / "enrichment"
            / f"{generated_at.replace('-','').replace(':','').replace('+','')}-isrc.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        report["report_path"] = str(report_path.relative_to(root))
    return report


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_enrich_isrc(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "Enrich-isrc completed" + (" (dry run)" if report["dry_run"] else ""),
        f"Releases scanned: {s['releases_scanned']}",
        f"Releases patched: {s['releases_patched']}",
        f"Tracks patched:   {s['tracks_patched']}",
        f"Skipped (no Spotify link): {s['skipped_no_spotify_link']}",
        f"Unmatched tracks: {s['unmatched_tracks']}",
        f"Errors: {s['errors']}",
    ]
    if report.get("patched"):
        lines.append("")
        for entry in report["patched"]:
            for field, isrc in entry["added"].items():
                lines.append(f"  {entry['path']}  {field} = {isrc}")
    if report.get("unmatched"):
        lines.append("")
        lines.append("Unmatched:")
        for u in report["unmatched"]:
            lines.append(f"  {u}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  {e}")
    if report.get("report_path"):
        lines.append(f"\nReport: {report['report_path']}")
    return "\n".join(lines)
