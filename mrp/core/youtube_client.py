from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from mrp.core.spotify_client import load_dotenv

API_BASE = "https://www.googleapis.com/youtube/v3"
MAX_ATTEMPTS = 3
PAGE_SIZE = 50

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
