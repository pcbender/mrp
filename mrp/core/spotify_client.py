from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
MAX_ATTEMPTS = 5


class SpotifyAuthError(RuntimeError):
    pass


class SpotifyAPIError(RuntimeError):
    pass


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        session: requests.Session | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session or requests.Session()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        repo: str | Path | None = None,
    ) -> "SpotifyClient":
        merged = dict(env if env is not None else os.environ)
        dotenv_path = Path(repo) / ".env" if repo is not None else Path(".env")
        for key, value in load_dotenv(dotenv_path).items():
            merged.setdefault(key, value)

        client_id = merged.get("SPOTIFY_CLIENT_ID")
        client_secret = merged.get("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise SpotifyAuthError(
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in the "
                f"environment or in {dotenv_path}."
            )
        return cls(client_id, client_secret)

    def get_artist(self, artist_id: str) -> dict[str, Any]:
        return self._get(f"/artists/{artist_id}")

    def get_artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        url: str | None = f"/artists/{artist_id}/albums"
        params: dict[str, Any] | None = {
            "include_groups": "album,single",
            "market": "US",
        }
        # No explicit `limit`: this app's token gets a 400 "Invalid limit" for
        # any limit value (even Spotify's own default of 20), a known quirk
        # for newly-created/dev-mode apps. Omitting it falls back to the
        # server default page size; `next` still drives pagination normally.
        while url:
            payload = self._get(url, params=params)
            items.extend(payload.get("items", []))
            url = payload.get("next")
            params = None  # 'next' already carries its own query string
        return items

    def get_album(self, album_id: str) -> dict[str, Any]:
        return self._get(f"/albums/{album_id}", params={"market": "US"})

    def get_tracks(self, track_ids: list[str]) -> list[dict[str, Any]]:
        # Album track items are SimplifiedTrackObjects with no external_ids;
        # ISRC requires the full track. The batch "Get Several Tracks"
        # endpoint (GET /tracks?ids=...) returns 403 for this app (a
        # dev-mode/new-app restriction); the singular GET /tracks/{id} works,
        # so fetch one at a time.
        return [self._get(f"/tracks/{track_id}", params={"market": "US"}) for track_id in track_ids]

    def download(self, url: str) -> bytes:
        response = self._session.get(url, timeout=30)
        response.raise_for_status()
        return response.content

    def _ensure_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        response = self._session.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
            timeout=15,
        )
        if response.status_code != 200:
            raise SpotifyAuthError(f"Spotify token request failed: {response.status_code} {response.text}")
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + float(payload.get("expires_in", 3600)) - 30
        return self._token

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        for _ in range(MAX_ATTEMPTS):
            token = self._ensure_token()
            response = self._session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if response.status_code == 429:
                time.sleep(float(response.headers.get("Retry-After", 1)))
                continue
            if response.status_code == 401:
                self._token = None
                continue
            if response.status_code >= 400:
                raise SpotifyAPIError(f"Spotify API error {response.status_code} for {url}: {response.text}")
            return response.json()
        raise SpotifyAPIError(f"Spotify API rate-limited too many times for {url}")
