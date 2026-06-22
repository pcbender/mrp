from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from mrp.core.enrich_apple_music import enrich_apple_music

ROOT = Path(__file__).resolve().parents[1]


class FakeAppleMusicClient:
    def __init__(
        self,
        albums_by_artist_id: dict[str, list[dict[str, Any]]] | None = None,
        tracks_by_collection_id: dict[Any, list[dict[str, Any]]] | None = None,
    ) -> None:
        self._albums_by_artist_id = albums_by_artist_id or {}
        self._tracks_by_collection_id = tracks_by_collection_id or {}
        self.album_calls: list[str] = []
        self.track_calls: list[Any] = []

    def get_albums(self, artist_id: str) -> list[dict[str, Any]]:
        self.album_calls.append(artist_id)
        return self._albums_by_artist_id.get(artist_id, [])

    def get_tracks(self, collection_id: Any) -> list[dict[str, Any]]:
        self.track_calls.append(collection_id)
        return self._tracks_by_collection_id.get(collection_id, [])


def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    return repo


def reset_apple_music_links(path: Path) -> dict[str, Any]:
    """Force a clean (no apple_music) starting state, independent of whatever
    a real enrichment run may have already written into this fixture file."""
    data = yaml.safe_load(path.read_text())
    release = data["release"]
    release.get("links", {}).pop("apple_music", None)
    for track in release.get("tracks") or []:
        if isinstance(track, dict) and "links" in track:
            track["links"].pop("apple_music", None)
            if not track["links"]:
                del track["links"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return release


def made_by_moving_album() -> dict[str, Any]:
    return {
        "collectionId": 1845588107,
        "collectionName": "Made by Moving",
        "collectionViewUrl": "https://music.apple.com/us/album/made-by-moving/1845588107?uo=4",
        "trackCount": 10,
    }


MADE_BY_MOVING_TRACKS = [
    {"trackName": "Made by Moving", "trackViewUrl": "https://music.apple.com/us/album/made-by-moving/1845588107?i=1&uo=4"},
    {"trackName": "Opposites Attract in Time", "trackViewUrl": "https://music.apple.com/us/album/made-by-moving/1845588107?i=7&uo=4"},
]


def test_enrich_apple_music_backfills_release_and_track_links(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    before = reset_apple_music_links(path)
    assert before["links"].get("apple_music") is None
    assert all("links" not in track for track in before["tracks"])

    client = FakeAppleMusicClient(
        albums_by_artist_id={"1793178641": [made_by_moving_album()]},
        tracks_by_collection_id={1845588107: MADE_BY_MOVING_TRACKS},
    )

    report = enrich_apple_music(repo, delay_seconds=0, client=client)

    assert report["summary"]["releases_patched"] >= 1
    assert report["summary"]["tracks_patched"] == 2

    after = yaml.safe_load(path.read_text())["release"]
    assert after["links"]["apple_music"] == "https://music.apple.com/us/album/made-by-moving/1845588107"
    tracks_by_slug = {t["slug"]: t for t in after["tracks"]}
    assert tracks_by_slug["made-by-moving"]["links"]["apple_music"] == "https://music.apple.com/us/album/made-by-moving/1845588107?i=1"
    # Case-insensitive match: our title is "Opposites Attract In Time".
    assert tracks_by_slug["opposites-attract-in-time"]["links"]["apple_music"] == "https://music.apple.com/us/album/made-by-moving/1845588107?i=7"
    # No Apple match was supplied for this track; it must stay untouched.
    assert "links" not in tracks_by_slug["riddles-abound"]


def test_enrich_apple_music_never_overwrites_existing_value(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    data = yaml.safe_load(path.read_text())
    data["release"]["links"]["apple_music"] = "https://music.apple.com/us/album/already-set/1"
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    client = FakeAppleMusicClient(
        albums_by_artist_id={"1793178641": [made_by_moving_album()]},
        tracks_by_collection_id={1845588107: MADE_BY_MOVING_TRACKS},
    )

    enrich_apple_music(repo, delay_seconds=0, client=client)

    after = yaml.safe_load(path.read_text())["release"]
    assert after["links"]["apple_music"] == "https://music.apple.com/us/album/already-set/1"


def test_enrich_apple_music_skips_artists_without_apple_link(tmp_path):
    repo = content_repo(tmp_path)
    reset_apple_music_links(repo / "content/releases/made-by-moving.yaml")
    artist_path = repo / "content/artists/pcbender.json"

    artist_data = json.loads(artist_path.read_text())
    artist_data["artist"]["links"]["apple_music"] = None
    artist_path.write_text(json.dumps(artist_data, indent=2))

    client = FakeAppleMusicClient(albums_by_artist_id={"1793178641": [made_by_moving_album()]})

    report = enrich_apple_music(repo, delay_seconds=0, client=client)

    assert "1793178641" not in client.album_calls
    assert report["summary"]["skipped_no_apple_artist_link"] >= 1
    after = yaml.safe_load((repo / "content/releases/made-by-moving.yaml").read_text())["release"]
    assert after["links"].get("apple_music") is None


def test_enrich_apple_music_reports_unmatched_release(tmp_path):
    repo = content_repo(tmp_path)
    client = FakeAppleMusicClient(
        albums_by_artist_id={"1793178641": [{**made_by_moving_album(), "collectionName": "Some Other Album"}]}
    )

    report = enrich_apple_music(repo, delay_seconds=0, client=client)

    assert "content/releases/made-by-moving.yaml" in report["unmatched_release_paths"]


def test_enrich_apple_music_dry_run_does_not_write(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    reset_apple_music_links(path)
    before_text = path.read_text()

    client = FakeAppleMusicClient(
        albums_by_artist_id={"1793178641": [made_by_moving_album()]},
        tracks_by_collection_id={1845588107: MADE_BY_MOVING_TRACKS},
    )

    report = enrich_apple_music(repo, delay_seconds=0, dry_run=True, client=client)

    assert report["summary"]["releases_patched"] >= 1
    assert path.read_text() == before_text
    assert "report_path" not in report
