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
        request_params = {**params, "key": self._api_key}
        for attempt in range(MAX_ATTEMPTS):
            response = self._session.get(f"{API_BASE}/{path}", params=request_params, timeout=15)
            if response.status_code in (403, 429) and attempt < MAX_ATTEMPTS - 1:
                time.sleep(2.0)
                continue
            if response.status_code >= 400:
                return {}
            return response.json()
        return {}

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
