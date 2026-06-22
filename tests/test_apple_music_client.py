from __future__ import annotations

from typing import Any

from mrp.core.apple_music_client import AppleMusicClient, extract_artist_id, strip_tracking_params


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


def test_extract_artist_id_from_artist_url() -> None:
    assert extract_artist_id("https://music.apple.com/us/artist/pcbender/1793178641") == "1793178641"


def test_extract_artist_id_returns_none_when_no_trailing_id() -> None:
    assert extract_artist_id("https://music.apple.com/us/artist/pcbender") is None


def test_strip_tracking_params_drops_uo_but_keeps_track_index() -> None:
    url = "https://music.apple.com/us/album/made-by-moving/1845588107?i=1845588108&uo=4"
    assert strip_tracking_params(url) == "https://music.apple.com/us/album/made-by-moving/1845588107?i=1845588108"


def test_get_albums_filters_to_collection_results() -> None:
    session = FakeSession(
        FakeResponse(
            json_data={
                "results": [
                    {"wrapperType": "artist", "artistId": 1},
                    {"wrapperType": "collection", "collectionId": 2, "collectionName": "An Album"},
                ]
            }
        )
    )
    client = AppleMusicClient(session=session)
    albums = client.get_albums("1")
    assert len(albums) == 1
    assert albums[0]["collectionName"] == "An Album"


def test_get_tracks_filters_to_track_results() -> None:
    session = FakeSession(
        FakeResponse(
            json_data={
                "results": [
                    {"wrapperType": "collection", "collectionId": 2},
                    {"wrapperType": "track", "trackName": "Song One"},
                ]
            }
        )
    )
    client = AppleMusicClient(session=session)
    tracks = client.get_tracks("2")
    assert len(tracks) == 1
    assert tracks[0]["trackName"] == "Song One"


def test_lookup_returns_empty_list_on_client_error() -> None:
    session = FakeSession(FakeResponse(status_code=404))
    client = AppleMusicClient(session=session)
    assert client.get_albums("1") == []
