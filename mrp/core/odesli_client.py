from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from mrp.core.spotify_client import load_dotenv

API_BASE = "https://api.song.link/v1-alpha.1/links"
MAX_ATTEMPTS = 5

# Without a key: 10 requests/min. With one (free, request via developers@song.link):
# 60 requests/min. https://help.song.link/articles/3037922-api-documentation-v1-alpha-1
DEFAULT_DELAY_SECONDS_NO_KEY = 6.5
DEFAULT_DELAY_SECONDS_WITH_KEY = 1.1


class OdesliRateLimitedError(RuntimeError):
    pass


class OdesliClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        country: str = "US",
        api_key: str | None = None,
    ) -> None:
        self._session = session or requests.Session()
        self._country = country
        self._api_key = api_key
        self.has_key = bool(api_key)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, repo: str | Path | None = None) -> "OdesliClient":
        merged = dict(env if env is not None else os.environ)
        dotenv_path = Path(repo) / ".env" if repo is not None else Path(".env")
        for key, value in load_dotenv(dotenv_path).items():
            merged.setdefault(key, value)
        return cls(api_key=merged.get("ODESLI_API_KEY") or None)

    @property
    def default_delay_seconds(self) -> float:
        return DEFAULT_DELAY_SECONDS_WITH_KEY if self.has_key else DEFAULT_DELAY_SECONDS_NO_KEY

    def get_links(self, url: str) -> dict[str, Any]:
        params = {"url": url, "userCountry": self._country}
        if self._api_key:
            params["key"] = self._api_key
        for _ in range(MAX_ATTEMPTS):
            response = self._session.get(
                API_BASE,
                params=params,
                timeout=15,
            )
            if response.status_code == 429:
                time.sleep(float(response.headers.get("Retry-After", 5)))
                continue
            if response.status_code >= 400:
                # Most commonly a 404 when Odesli has no match for this release;
                # treat as "nothing found" rather than a hard failure.
                return {}
            return response.json()
        # Exhausted retries while still being rate-limited -- distinct from a
        # genuine "no match" so callers don't mistake throttling for coverage.
        raise OdesliRateLimitedError(f"Odesli rate-limited after {MAX_ATTEMPTS} attempts for {url}")
