from __future__ import annotations

from pathlib import Path
from typing import Any

from mrp.core.youtube_client import YouTubeClient, extract_channel_id


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._json = json_data or {}

    def json(self) -> dict[str, Any]:
        return self._json


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> FakeResponse:
        self.calls.append(params or {})
        return self._responses.pop(0)


def test_extract_channel_id_from_channel_url() -> None:
    assert extract_channel_id("https://www.youtube.com/channel/UCvNXkiIHQJM-uY4MT3gmKDw") == "UCvNXkiIHQJM-uY4MT3gmKDw"


def test_extract_channel_id_returns_none_for_non_channel_url() -> None:
    assert extract_channel_id("https://www.youtube.com/@pcbender") is None


def test_from_env_reads_google_service_api_key_from_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("GOOGLE_SERVICE_API_KEY=test-key-123\n")
    client = YouTubeClient.from_env(env={}, repo=tmp_path)
    assert client is not None


def test_from_env_returns_none_without_key(tmp_path: Path) -> None:
    assert YouTubeClient.from_env(env={}, repo=tmp_path) is None


def test_get_uploads_playlist_id() -> None:
    session = FakeSession(
        [FakeResponse(json_data={"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]})]
    )
    client = YouTubeClient(api_key="key", session=session)
    assert client.get_uploads_playlist_id("UC123") == "UU123"
    assert "key" in session.calls[0]


def test_get_uploads_playlist_id_returns_none_for_unknown_channel() -> None:
    session = FakeSession([FakeResponse(json_data={"items": []})])
    client = YouTubeClient(api_key="key", session=session)
    assert client.get_uploads_playlist_id("UC123") is None


def test_get_playlist_videos_paginates() -> None:
    page1 = FakeResponse(
        json_data={
            "items": [{"snippet": {"title": "Song One", "resourceId": {"videoId": "abc"}}}],
            "nextPageToken": "page2",
        }
    )
    page2 = FakeResponse(json_data={"items": [{"snippet": {"title": "Song Two", "resourceId": {"videoId": "def"}}}]})
    session = FakeSession([page1, page2])
    client = YouTubeClient(api_key="key", session=session)

    videos = client.get_playlist_videos("UU123")

    assert videos == [{"title": "Song One", "videoId": "abc"}, {"title": "Song Two", "videoId": "def"}]
    assert len(session.calls) == 2
    assert session.calls[1]["pageToken"] == "page2"


def test_get_returns_empty_dict_on_client_error() -> None:
    session = FakeSession([FakeResponse(status_code=404)])
    client = YouTubeClient(api_key="key", session=session)
    assert client.get_uploads_playlist_id("UC123") is None
