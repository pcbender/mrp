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
    path = root / "content" / "artists" / f"{artist_id}.yaml"
    if not path.exists():
        return {}
    data = load_structured_record(path)
    return data.get("artist") or {}


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
) -> dict[str, Any]:
    path, data, release = _load_release(root, slug)

    automation = release.get("automation") or {}
    master_path = automation.get("master_path")
    if not master_path:
        raise ValueError(
            "No automation.master_path — set the master file path in the Automation section first"
        )

    critic_cwd = root / "app" / "critic"

    def _args(mp: str, track_slug: str) -> list[str]:
        cmd = [
            "critic", "review", str(mp),
            "--release-slug", slug,
            "--track-slug", track_slug,
            "--model", model,
            "--persona", persona,
            "--target", target,
        ]
        if target_tier is not None:
            cmd += ["--target-tier", str(target_tier)]
        return cmd

    if release.get("model") == "song":
        song = release.get("song") or {}
        track_slug = song.get("slug") or slug
        result = subprocess.run(
            _args(str(master_path), track_slug),
            capture_output=True, text=True, cwd=str(critic_cwd),
        )
        ok = result.returncode == 0
        return {
            "ok": ok,
            "track_slug": track_slug,
            "model": model,
            "persona": persona,
            "target": target,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-500:] if not ok else "",
        }

    # Album: run per-track
    tracks = release.get("tracks") or []
    raw_paths = master_path if isinstance(master_path, list) else [master_path]
    results = []
    for i, track in enumerate(tracks):
        track_slug = track.get("slug") or f"track-{i + 1}"
        mp = raw_paths[i] if i < len(raw_paths) else raw_paths[0]
        r = subprocess.run(
            _args(str(mp), track_slug),
            capture_output=True, text=True, cwd=str(critic_cwd),
        )
        results.append({"track_slug": track_slug, "ok": r.returncode == 0})
    return {"tracks": results, "total": len(tracks), "model": model, "persona": persona, "target": target}


def run_sampler(root: Path, slug: str) -> dict[str, Any]:
    path, data, release = _load_release(root, slug)
    artist_id = release.get("artist_id") or ""

    if release.get("model") == "song":
        song = release.get("song") or {}
        track_slug = song.get("slug") or slug
        track_id = f"{artist_id}--{track_slug}"
        critic_out = root / "app" / "critic" / "out" / f"{track_id}.json"
        if not critic_out.is_file():
            raise ValueError(
                f"No critic output at {critic_out.relative_to(root)} — run Critic first"
            )
        result = subprocess.run(
            [sys.executable, str(root / "app" / "sampler" / "cli.py"), "--track", track_id],
            capture_output=True, text=True, cwd=str(root),
        )
        return {
            "ok": result.returncode == 0,
            "track_id": track_id,
            "stdout": result.stdout[-2000:],
        }

    tracks = release.get("tracks") or []
    results = []
    for track in tracks:
        track_slug = track.get("slug") or ""
        track_id = f"{artist_id}--{track_slug}"
        r = subprocess.run(
            [sys.executable, str(root / "app" / "sampler" / "cli.py"), "--track", track_id],
            capture_output=True, text=True, cwd=str(root),
        )
        results.append({"track_id": track_id, "ok": r.returncode == 0})
    return {"tracks": results}


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


def run_promoter(root: Path, slug: str) -> dict[str, Any]:
    path, data, release = _load_release(root, slug)
    artist_id = release.get("artist_id") or ""
    if not artist_id:
        raise ValueError("No artist_id on this release")

    result = subprocess.run(
        ["promoter", "blurb", "--artist", artist_id],
        capture_output=True, text=True, cwd=str(root / "app" / "promoter"),
    )
    ok = result.returncode == 0
    return {
        "ok": ok,
        "artist_id": artist_id,
        "stdout": result.stdout[-3000:],
        "stderr": result.stderr[-500:] if not ok else "",
    }
