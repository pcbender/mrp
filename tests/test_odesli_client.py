from __future__ import annotations

from pathlib import Path
from typing import Any

from mrp.core.odesli_client import (
    DEFAULT_DELAY_SECONDS_NO_KEY,
    DEFAULT_DELAY_SECONDS_WITH_KEY,
    OdesliClient,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._json


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> FakeResponse:
        self.calls.append(params or {})
        return self._response


def test_from_env_reads_odesli_api_key_from_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("ODESLI_API_KEY=test-key-123\n")

    client = OdesliClient.from_env(env={}, repo=tmp_path)

    assert client.has_key is True
    assert client.default_delay_seconds == DEFAULT_DELAY_SECONDS_WITH_KEY


def test_from_env_without_key_is_anonymous(tmp_path: Path) -> None:
    client = OdesliClient.from_env(env={}, repo=tmp_path)

    assert client.has_key is False
    assert client.default_delay_seconds == DEFAULT_DELAY_SECONDS_NO_KEY


def test_get_links_includes_key_param_when_set() -> None:
    session = FakeSession(FakeResponse(json_data={"linksByPlatform": {}}))
    client = OdesliClient(session=session, api_key="test-key-123")

    client.get_links("https://open.spotify.com/album/abc")

    assert session.calls[0]["key"] == "test-key-123"


def test_get_links_omits_key_param_when_unset() -> None:
    session = FakeSession(FakeResponse(json_data={"linksByPlatform": {}}))
    client = OdesliClient(session=session)

    client.get_links("https://open.spotify.com/album/abc")

    assert "key" not in session.calls[0]
