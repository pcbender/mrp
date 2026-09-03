from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from mrp.core.spotify_client import load_dotenv

API_BASE = "https://www.googleapis.com/youtube/v3"
MAX_ATTEMPTS = 3
PAGE_SIZE = 50

# Auto-generated album playlists ("Album - X" / "X" owned by channel YouTube).
_ALBUM_PLAYLIST_RE = re.compile(r"OLAK5uy_[A-Za-z0-9_-]{10,}")
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 403 covers both "slow down" and "this key will never work". Only the former
# is worth retrying; the rest should surface immediately.
_RETRYABLE_REASONS = frozenset(
    {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded", "backendError"}
)


class YouTubeAPIError(RuntimeError):
    """A YouTube API call failed for a reason the caller cannot paper over.

    Kept distinct from "no match": a rejected key, an unenabled API or an
    exhausted quota all used to be swallowed into an empty result, so every
    enrichment job reported "nothing new" whatever the real cause. An expired
    or wrong-type credential looks exactly like a release that simply is not
    on YouTube, which is the opposite of actionable.
    """


def _error_detail(response: requests.Response) -> tuple[str, str]:
    """(reason, message) from a Google API error body, best effort."""
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return "", response.text[:200]
    errors = error.get("errors") or [{}]
    return str(errors[0].get("reason") or ""), str(error.get("message") or "")


def extract_channel_id(channel_url: str) -> str | None:
    segments = [segment for segment in urlsplit(channel_url).path.split("/") if segment]
    if segments and segments[-1].startswith("UC"):
        return segments[-1]
    return None


class YouTubeClient:
    """Thin wrapper around the YouTube Data API v3 for read-only channel lookups."""

    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self._api_key = api_key
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, repo: str | Path | None = None) -> "YouTubeClient | None":
        merged = dict(env if env is not None else os.environ)
        dotenv_path = Path(repo) / ".env" if repo is not None else Path(".env")
        for key, value in load_dotenv(dotenv_path).items():
            merged.setdefault(key, value)
        api_key = merged.get("GOOGLE_SERVICE_API_KEY")
        return cls(api_key=api_key) if api_key else None

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET one endpoint, distinguishing "no match" from "call failed".

        Only 404 means the thing genuinely is not there. Everything else that
        will not fix itself — a rejected or wrong-type key, the Data API not
        enabled on the project, a spent quota — raises, so the caller reports
        the real reason instead of an empty result.
        """
        request_params = {**params, "key": self._api_key}
        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            response = self._session.get(f"{API_BASE}/{path}", params=request_params, timeout=15)
            if response.status_code == 404:
                return {}
            if response.status_code < 400:
                return response.json()

            reason, message = _error_detail(response)
            last_error = f"HTTP {response.status_code} {reason or ''} {message}".strip()
            retryable = response.status_code == 429 or (
                response.status_code == 403 and reason in _RETRYABLE_REASONS
            )
            if not retryable:
                raise YouTubeAPIError(f"YouTube API call to {path} failed: {last_error}")
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(2.0)
        raise YouTubeAPIError(
            f"YouTube API call to {path} still failing after {MAX_ATTEMPTS} attempts: {last_error}"
        )

    def get_playlist(self, playlist_id: str) -> dict[str, Any] | None:
        """Title and item count for a playlist, or None if it does not exist."""
        data = self._get("playlists", {"part": "snippet,contentDetails", "id": playlist_id})
        for item in data.get("items") or []:
            return {
                "playlistId": playlist_id,
                "title": (item.get("snippet") or {}).get("title") or "",
                "itemCount": (item.get("contentDetails") or {}).get("itemCount"),
            }
        return None

    def playlist_video_ids(self, playlist_id: str) -> list[str]:
        """Every video id in a playlist, following pagination."""
        video_ids: list[str] = []
        page_token = ""
        while True:
            params = {
                "part": "contentDetails",
                "playlistId": playlist_id,
                "maxResults": PAGE_SIZE,
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get("playlistItems", params)
            for item in data.get("items") or []:
                video_id = (item.get("contentDetails") or {}).get("videoId")
                if video_id:
                    video_ids.append(video_id)
            page_token = data.get("nextPageToken") or ""
            if not page_token:
                return video_ids

    def album_playlist_ids(self, video_id: str) -> list[str]:
        """Candidate album-playlist ids advertised on a track's watch page.

        Auto-generated OLAK album playlists are absent from the Data API:
        `search?type=playlist` never returns one (verified against Abbey Road,
        Rumours and Thriller as well as our own catalogue), and they belong to
        channel "YouTube" rather than the artist's Topic channel, so listing
        the channel's playlists does not reach them either. They can be read
        back by id, just never discovered — so recover a candidate id from the
        watch page and let the caller verify it through the API.

        Scraping a page whose markup Google may change at any time: this
        returns candidates only, and callers must confirm them.
        """
        response = self._session.get(
            f"https://www.youtube.com/watch?v={video_id}",
            timeout=20,
            headers={"User-Agent": _BROWSER_UA},
        )
        if response.status_code >= 400:
            return []
        seen: list[str] = []
        for match in _ALBUM_PLAYLIST_RE.finditer(response.text):
            if match.group(0) not in seen:
                seen.append(match.group(0))
        return seen

    def search_by_isrc(self, isrc: str) -> dict[str, Any] | None:
        """Return the first music video matching the ISRC, or None if not found."""
        data = self._get("search", {
            "part": "id,snippet",
            "q": f'"{isrc}"',
            "maxResults": 1,
            "type": "video",
            "videoCategoryId": "10",
        })
        items = data.get("items") or []
        if not items:
            return None
        item = items[0]
        video_id = (item.get("id") or {}).get("videoId")
        title = (item.get("snippet") or {}).get("title")
        return {"videoId": video_id, "title": title} if video_id else None

    def get_uploads_playlist_id(self, channel_id: str) -> str | None:
        data = self._get("channels", {"part": "contentDetails", "id": channel_id})
        items = data.get("items") or []
        if not items:
            return None
        return (items[0].get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")

    def get_playlist_videos(self, playlist_id: str) -> list[dict[str, Any]]:
        videos: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"part": "snippet", "playlistId": playlist_id, "maxResults": PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            data = self._get("playlistItems", params)
            for item in data.get("items", []):
                snippet = item.get("snippet") or {}
                video_id = (snippet.get("resourceId") or {}).get("videoId")
                if video_id:
                    videos.append({"title": snippet.get("title"), "videoId": video_id})
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return videos
