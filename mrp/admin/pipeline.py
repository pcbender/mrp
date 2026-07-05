"""Per-release pipeline step functions — each runs one enrichment step on a single release."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from mrp.core.migrate_site import load_structured_record, serialize_structured_record


def _load_release(root: Path, slug: str) -> tuple[Path, dict, dict]:
    path = root / "content" / "releases" / f"{slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Release not found: {slug}")
    data = load_structured_record(path)
    return path, data, data["release"]


def _load_artist(root: Path, artist_id: str) -> dict:
    # Artist records are YAML; tolerate legacy JSON records too
    # (load_structured_record handles both).
    for ext in (".yaml", ".json"):
        path = root / "content" / "artists" / f"{artist_id}{ext}"
        if path.exists():
            data = load_structured_record(path)
            return data.get("artist") or {}
    return {}


def enrich_odesli(root: Path, slug: str) -> dict[str, Any]:
    from mrp.core.odesli_client import OdesliClient
    from mrp.core.enrich_links import PLATFORM_MAP

    path, data, release = _load_release(root, slug)

    spotify_url = (release.get("links") or {}).get("spotify")
    if not spotify_url and release.get("model") == "song":
        spotify_url = (release.get("song") or {}).get("links", {}).get("spotify")
    if not spotify_url:
        raise ValueError("No Spotify URL on this release — add it under Streaming Links first")

    odesli = OdesliClient.from_env(repo=root)
    payload = odesli.get_links(spotify_url)

    links = release.setdefault("links", {})
    added: dict[str, str] = {}
    for odesli_key, our_key in PLATFORM_MAP.items():
        url = (payload.get("linksByPlatform") or {}).get(odesli_key, {}).get("url")
        if url and not links.get(our_key):
            links[our_key] = url
            added[our_key] = url

    path.write_text(serialize_structured_record(path, data))
    return {"added": added, "total": len(added), "slug": slug}


def enrich_apple_music(root: Path, slug: str) -> dict[str, Any]:
    from mrp.core.apple_music_client import AppleMusicClient, extract_artist_id, strip_tracking_params
    from mrp.core.enrich_apple_music import _title_key

    path, data, release = _load_release(root, slug)
    artist_id = release.get("artist_id") or ""
    artist = _load_artist(root, artist_id)

    artist_url = (artist.get("links") or {}).get("apple_music")
    if not artist_url:
        raise ValueError(
            f"Artist '{artist_id}' has no apple_music link — add it to the artist record first"
        )

    am_artist_id = extract_artist_id(artist_url)
    if not am_artist_id:
        raise ValueError(f"Cannot parse Apple Music artist ID from: {artist_url}")

    apple = AppleMusicClient()
    albums = apple.get_albums(am_artist_id)
    albums_by_key = {_title_key(a.get("collectionName") or ""): a for a in albums}
    album = albums_by_key.get(_title_key(release.get("title") or ""))
    if not album:
        raise ValueError(f"'{release.get('title')}' not matched on Apple Music for this artist")

    added: dict[str, str] = {}
    target_links = release.setdefault("links", {})
    if not target_links.get("apple_music") and album.get("collectionViewUrl"):
        target_links["apple_music"] = strip_tracking_params(album["collectionViewUrl"])
        added["apple_music"] = target_links["apple_music"]

    tracks = release.get("tracks")
    if isinstance(tracks, list) and len(tracks) > 1 and (album.get("trackCount") or 0) > 1:
        try:
            apple_tracks = apple.get_tracks(album["collectionId"])
            tracks_by_key = {_title_key(t.get("trackName") or ""): t for t in apple_tracks}
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                at = tracks_by_key.get(_title_key(track.get("title") or ""))
                if not at or not at.get("trackViewUrl"):
                    continue
                tl = track.setdefault("links", {})
                if not tl.get("apple_music"):
                    url = strip_tracking_params(at["trackViewUrl"])
                    tl["apple_music"] = url
                    added[f"track:{track.get('slug')}.apple_music"] = url
        except Exception as exc:
            added["_track_error"] = str(exc)

    path.write_text(serialize_structured_record(path, data))
    return {"added": {k: v for k, v in added.items() if not k.startswith("_")}, "total": len(added)}


def enrich_youtube(root: Path, slug: str) -> dict[str, Any]:
    from mrp.core.youtube_client import YouTubeClient, extract_channel_id
    from mrp.core.enrich_youtube import _title_key

    path, data, release = _load_release(root, slug)
    artist_id = release.get("artist_id") or ""
    artist = _load_artist(root, artist_id)

    channel_url = (artist.get("links") or {}).get("youtube")
    if not channel_url:
        raise ValueError(
            f"Artist '{artist_id}' has no youtube link — add it to the artist record first"
        )

    channel_id = extract_channel_id(channel_url)
    if not channel_id:
        raise ValueError(f"Cannot parse YouTube channel ID from: {channel_url}")

    yt = YouTubeClient.from_env(repo=root)
    if yt is None:
        raise ValueError("No YOUTUBE_API_KEY in environment")

    # Lazy-load channel uploads only if we need title-matching as a fallback
    _videos_by_key: dict | None = None
    def _by_title(title: str) -> dict | None:
        nonlocal _videos_by_key
        if _videos_by_key is None:
            uploads = yt.get_uploads_playlist_id(channel_id)
            videos = yt.get_playlist_videos(uploads) if uploads else []
            _videos_by_key = {_title_key(v.get("title") or ""): v for v in videos}
        return _videos_by_key.get(_title_key(title))

    def _find_video(isrc: str | None, title: str) -> dict | None:
        if isrc:
            hit = yt.search_by_isrc(isrc)
            if hit:
                return hit
        return _by_title(title)

    added: dict[str, str] = {}
    target_links = release.setdefault("links", {})

    if release.get("model") == "song":
        song = release.get("song") or {}
        video = _find_video(song.get("isrc"), release.get("title") or "")
    else:
        video = _find_video(None, release.get("title") or "")

    if video:
        if not target_links.get("youtube"):
            target_links["youtube"] = f"https://www.youtube.com/watch?v={video['videoId']}"
            added["youtube"] = target_links["youtube"]
        if not target_links.get("youtube_music"):
            target_links["youtube_music"] = f"https://music.youtube.com/watch?v={video['videoId']}"
            added["youtube_music"] = target_links["youtube_music"]

    tracks = release.get("tracks")
    if isinstance(tracks, list):
        for track in tracks:
            if not isinstance(track, dict):
                continue
            tv = _find_video(track.get("isrc"), track.get("title") or "")
            if not tv:
                continue
            tl = track.setdefault("links", {})
            if not tl.get("youtube"):
                tl["youtube"] = f"https://www.youtube.com/watch?v={tv['videoId']}"
                added[f"track:{track.get('slug')}.youtube"] = tl["youtube"]

    path.write_text(serialize_structured_record(path, data))
    return {"added": added, "total": len(added)}


def run_critic(
    root: Path,
    slug: str,
    model: str = "dev",
    persona: str = "default",
    target: str = "blurb",
    target_tier: int | None = None,
    track_slug: str | None = None,
) -> dict[str, Any]:
    """Pass 1: per-track standalone review. track_slug limits to one track.

    A single-track run is an explicit settings choice, so it is saved on the
    track (track.critic) and reused by later runs — including critic-all,
    where each track's saved settings override the call-level defaults.
    """
    from mrp.admin.critic_io import critic_bin
    from mrp.admin.workspace import effective_master_path, track_units

    path, data, release = _load_release(root, slug)
    critic_cwd = root / "app" / "critic"
    bin_path = critic_bin(root)

    units = track_units(release)
    if track_slug is not None:
        units = [u for u in units if u["slug"] == track_slug]
        if not units:
            raise ValueError(f"Track not found: {track_slug}")
        settings: dict[str, Any] = {"model": model, "persona": persona, "target": target}
        if target_tier is not None:
            settings["target_tier"] = target_tier
        units[0]["track"]["critic"] = settings
        path.write_text(serialize_structured_record(path, data))

    def _args(mp: str, tslug: str, cs: dict) -> list[str]:
        cmd = [
            bin_path, "review", str(mp),
            "--release-slug", slug,
            "--track-slug", tslug,
            "--model", cs["model"],
            "--persona", cs["persona"],
            "--target", cs["target"],
        ]
        if cs.get("target_tier") is not None:
            cmd += ["--target-tier", str(cs["target_tier"])]
        return cmd

    results = []
    for unit in units:
        saved = unit["track"].get("critic") or {}
        cs = {
            "model": saved.get("model") or model,
            "persona": saved.get("persona") or persona,
            "target": saved.get("target") or target,
            "target_tier": saved.get("target_tier", target_tier),
        }
        mp = effective_master_path(release, unit["index"], unit["track"])
        if not mp:
            results.append({"track_slug": unit["slug"], "ok": False,
                            "error": "no master_path — set it in the track editor"})
            continue
        r = subprocess.run(
            _args(mp, unit["slug"], cs),
            capture_output=True, text=True, cwd=str(critic_cwd),
        )
        entry: dict[str, Any] = {"track_slug": unit["slug"], "ok": r.returncode == 0}
        if r.returncode != 0:
            entry["error"] = (r.stderr or r.stdout)[-500:]
        results.append(entry)

    ok_count = sum(1 for r in results if r["ok"])
    return {
        "tracks": results, "total": len(results), "ok_count": ok_count,
        "model": model, "persona": persona, "target": target,
    }


def run_critic_album(
    root: Path,
    slug: str,
    target: str = "album_blurb",
    model: str = "default",
    persona: str = "default",
) -> dict[str, Any]:
    """Pass 2+3: album synthesis + recontextualized track reviews."""
    from mrp.admin.critic_io import critic_bin

    _path, _data, release = _load_release(root, slug)
    if release.get("model") != "album":
        raise ValueError("Album review only applies to EP/album releases")

    result = subprocess.run(
        [critic_bin(root), "album", slug,
         "--target", target, "--model", model, "--persona", persona],
        capture_output=True, text=True, cwd=str(root / "app" / "critic"),
    )
    ok = result.returncode == 0
    return {
        "ok": ok,
        "target": target,
        "model": model,
        "persona": persona,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-800:] if not ok else "",
    }


def run_writeback(root: Path, slug: str) -> dict[str, Any]:
    """Write approved/publishable critic reviews to site/src/content/reviews/.

    critic writeback itself does not gate on review status, so the gate
    lives here: only records marked approved or publishable are written.
    """
    from mrp.admin.critic_io import (
        album_record_id, critic_bin, load_record, track_record_id,
    )
    from mrp.admin.workspace import track_units

    _path, _data, release = _load_release(root, slug)
    artist_id = release.get("artist_id") or ""

    candidates = [track_record_id(artist_id, u["slug"]) for u in track_units(release)]
    if release.get("model") == "album":
        candidates.append(album_record_id(artist_id, slug))

    written, skipped, failed = [], [], []
    for record_id in candidates:
        record = load_record(root, record_id)
        status = ((record or {}).get("review") or {}).get("status")
        if record is None or status not in ("approved", "publishable"):
            skipped.append({"id": record_id, "status": status or "missing"})
            continue
        r = subprocess.run(
            [critic_bin(root), "writeback", "--track", record_id, "--force"],
            capture_output=True, text=True, cwd=str(root / "app" / "critic"),
        )
        if r.returncode == 0:
            written.append(record_id)
        else:
            failed.append({"id": record_id, "error": (r.stderr or r.stdout)[-300:]})

    result: dict[str, Any] = {"written": written, "skipped": skipped,
                              "failed": failed, "total": len(written)}
    if not written and (skipped or failed):
        bits = [f"{s['id']} is {s['status']}" for s in skipped]
        bits += [f"{f['id']} failed" for f in failed]
        result["message"] = ("nothing written — " + "; ".join(bits)
                             + ". Only approved or publishable reviews are written.")
    return result


def run_sampler(
    root: Path,
    slug: str,
    track_slug: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate 30s preview snippets. track_slug limits to one track."""
    from mrp.admin.workspace import track_units

    path, data, release = _load_release(root, slug)
    artist_id = release.get("artist_id") or ""

    units = track_units(release)
    if track_slug is not None:
        units = [u for u in units if u["slug"] == track_slug]
        if not units:
            raise ValueError(f"Track not found: {track_slug}")

    results = []
    for unit in units:
        track_id = f"{artist_id}--{unit['slug']}"
        critic_out = root / "app" / "critic" / "out" / f"{track_id}.json"
        if not critic_out.is_file():
            results.append({"track_id": track_id, "ok": False,
                            "error": "no critic record — run Critic first"})
            continue
        cmd = [sys.executable, str(root / "app" / "sampler" / "cli.py"), "--track", track_id]
        if force:
            cmd.append("--force")
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))
        entry: dict[str, Any] = {"track_id": track_id, "ok": r.returncode == 0}
        if r.returncode != 0:
            entry["error"] = (r.stderr or r.stdout)[-300:]
        results.append(entry)

    ok_count = sum(1 for r in results if r["ok"])
    if results and ok_count == 0:
        raise RuntimeError(results[0].get("error") or "sampler failed for every track")
    return {"tracks": results, "ok_count": ok_count, "total": ok_count}


def _snip_encode(
    source_path: str,
    start_s: float,
    duration_s: float,
    output_path: Path,
    target_lufs: float = -14.0,
) -> None:
    """Two-pass loudnorm on the excerpt, then encode stereo 128k MP3.

    Mirrors app/sampler/cli.py — kept local because app/ is not an importable
    package from the admin process.
    """
    import json as _json
    import re as _re

    fade_out_start = max(0.0, duration_s - 1.5)
    af_base = (
        f"afade=t=in:st=0:d=0.3,"
        f"afade=t=out:st={fade_out_start}:d=1.5,"
        f"loudnorm=I={target_lufs}:TP=-1:LRA=11"
    )

    pass1 = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start_s), "-t", str(duration_s),
         "-i", source_path,
         "-af", af_base + ":print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    af_pass2 = af_base  # fall back to single-pass if measurement parsing fails
    match = _re.search(r'\{\s*"input_i"\s*:.+?\}', pass1.stderr, _re.DOTALL)
    if match:
        try:
            lnorm = _json.loads(match.group(0))
            af_pass2 = (
                af_base
                + f":measured_I={lnorm['input_i']}"
                + f":measured_LRA={lnorm['input_lra']}"
                + f":measured_TP={lnorm['input_tp']}"
                + f":measured_thresh={lnorm['input_thresh']}"
                + f":offset={lnorm['target_offset']}"
                + ":linear=true"
            )
        except (ValueError, KeyError):
            pass

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pass2 = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start_s), "-t", str(duration_s),
         "-i", source_path,
         "-af", af_pass2,
         "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k",
         str(output_path)],
        capture_output=True, text=True,
    )
    if pass2.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed: {pass2.stderr[-300:]}")


def run_snip(
    root: Path,
    slug: str,
    track_slug: str,
    start_s: float,
    end_s: float,
    target_lufs: float = -14.0,
) -> dict[str, Any]:
    """Cut a user-chosen [start, end] snippet from the master and set preview_audio."""
    from mrp.admin.workspace import effective_master_path, track_units

    path, data, release = _load_release(root, slug)
    artist_id = release.get("artist_id") or ""

    unit = next((u for u in track_units(release) if u["slug"] == track_slug), None)
    if unit is None:
        raise ValueError(f"Track not found: {track_slug}")
    master = effective_master_path(release, unit["index"], unit["track"])
    if not master:
        raise ValueError("No master path on this track — set it on the Tracks tab first")
    if not Path(master).is_file():
        raise ValueError(f"Master not found: {master}")

    duration = end_s - start_s
    if start_s < 0 or duration < 3:
        raise ValueError("Range must be at least 3 seconds")
    if duration > 60:
        raise ValueError("Range must be 60 seconds or less — previews should stay short")

    track_id = f"{artist_id}--{track_slug}"
    output_path = root / "site" / "public" / "samples" / f"{track_id}.mp3"
    _snip_encode(master, start_s, duration, output_path, target_lufs)

    preview_url = f"/samples/{track_id}.mp3"
    unit["track"]["preview_audio"] = preview_url
    path.write_text(serialize_structured_record(path, data))

    return {
        "status": "ok",
        "track_id": track_id,
        "start_s": round(start_s, 2),
        "duration_s": round(duration, 2),
        "preview_audio": preview_url,
        "sample_path": str(output_path.relative_to(root)),
    }


def enrich_landr(root: Path, slug: str) -> dict[str, Any]:
    import re
    import html
    from urllib.parse import urlparse, urljoin
    import requests

    path, data, release = _load_release(root, slug)

    upc = release.get("upc") or ""
    if not upc:
        raise ValueError("No UPC on this release — add it in the Info section first")

    landr_url = f"https://artists.landr.com/{upc}"
    resp = requests.get(landr_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    # Classify from the raw (un-cleaned) URL so query params are visible.
    # iTunes Store uses music.apple.com?app=itunes — same domain as Apple Music,
    # only distinguishable before the query string is stripped. youtube_music
    # must precede youtube to avoid the wrong key on music.youtube.com.
    _STORE_PATTERNS = [
        (re.compile(r"open\.spotify\.com/album/"), "spotify"),
        (re.compile(r"music\.apple\.com"), "apple_music"),
        (re.compile(r"music\.youtube\.com"), "youtube_music"),
        (re.compile(r"(?:www\.)?youtube\.com/watch"), "youtube"),
        (re.compile(r"(?:listen\.)?tidal\.com"), "tidal"),
        (re.compile(r"music\.amazon\.com|amazon\.com/music"), "amazon_music"),
        (re.compile(r"(?:www\.)?deezer\.com"), "deezer"),
        (re.compile(r"soundcloud\.com"), "soundcloud"),
        (re.compile(r"\.bandcamp\.com"), "bandcamp"),
        (re.compile(r"(?:www\.)?pandora\.com"), "pandora"),
    ]

    def _classify(raw: str) -> str | None:
        if "music.apple.com" in raw and "app=itunes" in raw:
            return "itunes_store"
        for pat, key in _STORE_PATTERNS:
            if pat.search(raw):
                return key
        return None

    # Platforms LANDR may expose that have no schema key — surfaced as warnings
    KNOWN_EXTRAS: list[tuple[re.Pattern, str]] = []

    # Extract all href values from <a> tags
    href_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
    hrefs = href_pattern.findall(resp.text)

    # Strip tracking params but preserve app= (identifies iTunes Store vs Apple Music)
    _TRACKING = frozenset([
        "utm_source", "utm_medium", "utm_content", "utm_campaign",
        "at", "ct", "itscg", "itsct", "tag", "linkCode", "ascsubtag", "go", "src", "lId", "ie",
        "cId", "sr", "ls",
    ])

    def clean_url(raw: str) -> str:
        from urllib.parse import parse_qs, urlencode
        decoded = html.unescape(raw)
        p = urlparse(decoded)
        kept = {k: v for k, v in parse_qs(p.query).items() if k not in _TRACKING}
        return p._replace(query=urlencode(kept, doseq=True), fragment="").geturl()

    seen: dict[str, str] = {}
    extra_links: dict[str, str] = {}
    for raw in hrefs:
        if not raw.startswith("http"):
            continue
        decoded = html.unescape(raw)
        key = _classify(decoded)
        if key:
            if key not in seen:
                seen[key] = clean_url(decoded)
        else:
            for pat, xkey in KNOWN_EXTRAS:
                if xkey not in extra_links and pat.search(decoded):
                    extra_links[xkey] = clean_url(decoded)
                    break

    target_links = release.setdefault("links", {})
    added: dict[str, str] = {}
    for key, url in seen.items():
        if not target_links.get(key):
            target_links[key] = url
            added[key] = url

    path.write_text(serialize_structured_record(path, data))
    return {"added": added, "total": len(added), "extra_links": extra_links, "landr_url": landr_url}


def run_promoter(root: Path, slug: str, mode: str = "blurb", model: str = "default") -> dict[str, Any]:
    """Run promoter blurb or bio for the release's artist (writes artist YAML)."""
    from mrp.admin.critic_io import promoter_bin

    path, data, release = _load_release(root, slug)
    artist_id = release.get("artist_id") or ""
    if not artist_id:
        raise ValueError("No artist_id on this release")
    if mode not in ("blurb", "bio"):
        raise ValueError(f"Unknown promoter mode: {mode}")

    cmd = [promoter_bin(root), mode, "--artist", artist_id, "--model", model]
    if mode == "bio":
        cmd.append("--force")
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(root / "app" / "promoter"),
    )
    ok = result.returncode == 0
    return {
        "ok": ok,
        "mode": mode,
        "artist_id": artist_id,
        "model": model,
        "stdout": result.stdout[-3000:],
        "stderr": result.stderr[-500:] if not ok else "",
    }


# --- Build/Publish pipeline wrappers -----------------------------------------

_STATUS_LADDER = ["draft", "staged", "verified", "approved", "live"]


def _advance_release_status(root: Path, slug: str, new_status: str) -> str:
    """Move the release forward on the lifecycle ladder as pipeline steps succeed.

    Forward-only: never regresses, never touches live/archived (those belong to
    publish/rollback). "failed" may re-enter the ladder at any rung.
    """
    path, data, release = _load_release(root, slug)
    current = release.get("status") or "draft"
    if current in ("live", "archived"):
        return current
    if (current in _STATUS_LADDER
            and _STATUS_LADDER.index(current) >= _STATUS_LADDER.index(new_status)):
        return current
    release["status"] = new_status
    path.write_text(serialize_structured_record(path, data))
    return new_status


def pub_validate(root: Path, slug: str) -> dict[str, Any]:
    from mrp.core.validate import validate_repository
    return validate_repository(root, release=slug)


def pub_build(root: Path, slug: str) -> dict[str, Any]:
    from mrp.core.build import build_repository
    # Draft releases are excluded from site builds, so a build requested for
    # this release implies promotion — it must be staged before the build runs.
    status = _advance_release_status(root, slug, "staged")
    result = build_repository(root, release=slug)
    result["release_status"] = status
    return result


def pub_stage(root: Path, slug: str, target: str = "local-staging") -> dict[str, Any]:
    from mrp.core.deploy import stage_build
    result = stage_build(root, target=target)
    if result.get("status") == "passed":
        result["release_status"] = _advance_release_status(root, slug, "staged")
    return result


def pub_verify(root: Path, slug: str, target: str = "staging") -> dict[str, Any]:
    from mrp.core.verify import verify_target
    result = verify_target(root, target=target, release=slug)
    if result.get("status") == "passed":
        result["release_status"] = _advance_release_status(root, slug, "verified")
    return result


def pub_approve(root: Path, slug: str) -> dict[str, Any]:
    from mrp.core.approve import approve
    result = approve(root, release=slug)
    if result.get("status") == "approved":
        result["release_status"] = _advance_release_status(root, slug, "approved")
    return result


def pub_publish(root: Path, slug: str) -> dict[str, Any]:
    from mrp.core.deploy import load_targets
    from mrp.core.publish import publish
    targets, _ = load_targets(root)
    remote = "remote-production" if "remote-production" in targets else None
    return publish(root, release=slug, remote_target=remote)


def pub_rollback(root: Path, slug: str) -> dict[str, Any]:
    from mrp.core.rollback import rollback
    return rollback(root, yes=True)
