from __future__ import annotations

import time
from typing import Any

import requests

API_BASE = "https://api.song.link/v1-alpha.1/links"
MAX_ATTEMPTS = 5


class OdesliRateLimitedError(RuntimeError):
    pass


class OdesliClient:
    def __init__(self, session: requests.Session | None = None, country: str = "US") -> None:
        self._session = session or requests.Session()
        self._country = country

    def get_links(self, url: str) -> dict[str, Any]:
        for _ in range(MAX_ATTEMPTS):
            response = self._session.get(
                API_BASE,
                params={"url": url, "userCountry": self._country},
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
