from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

API_BASE = "https://itunes.apple.com/lookup"
MAX_ATTEMPTS = 3
DEFAULT_DELAY_SECONDS = 1.0
TRACKING_QUERY_PARAMS = ("uo",)


def extract_artist_id(artist_url: str) -> str | None:
    segments = [segment for segment in urlsplit(artist_url).path.split("/") if segment]
    if segments and segments[-1].isdigit():
        return segments[-1]
    return None


def strip_tracking_params(url: str) -> str:
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key not in TRACKING_QUERY_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


class AppleMusicClient:
    """Free, keyless lookup against Apple's public iTunes Search/Lookup API."""

    def __init__(self, session: requests.Session | None = None, country: str = "us") -> None:
        self._session = session or requests.Session()
        self._country = country

    def _lookup(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        request_params = {"country": self._country, **params}
        for attempt in range(MAX_ATTEMPTS):
            response = self._session.get(API_BASE, params=request_params, timeout=15)
            if response.status_code in (403, 429) and attempt < MAX_ATTEMPTS - 1:
                time.sleep(float(response.headers.get("Retry-After", 5)))
                continue
            if response.status_code >= 400:
                return []
            return response.json().get("results", [])
        return []

    def get_albums(self, artist_id: str) -> list[dict[str, Any]]:
        results = self._lookup({"id": artist_id, "entity": "album", "limit": 200})
        return [r for r in results if r.get("wrapperType") == "collection"]

    def get_tracks(self, collection_id: int | str) -> list[dict[str, Any]]:
        results = self._lookup({"id": collection_id, "entity": "song"})
        return [r for r in results if r.get("wrapperType") == "track"]
