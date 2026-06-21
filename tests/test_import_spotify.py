from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import yaml

from mrp.core.import_spotify import import_spotify

ROOT = Path(__file__).resolve().parents[1]


class FakeSpotifyClient:
    def __init__(
        self,
        artists: dict[str, dict[str, Any]],
        albums_by_artist: dict[str, list[dict[str, Any]]],
        album_details: dict[str, dict[str, Any]],
    ) -> None:
        self._artists = artists
        self._albums_by_artist = albums_by_artist
        self._album_details = album_details
        self.downloaded: list[str] = []

    def get_artist(self, artist_id: str) -> dict[str, Any]:
        return self._artists[artist_id]

    def get_artist_albums(self, artist_id: str) -> list[dict[str, Any]]:
        return self._albums_by_artist.get(artist_id, [])

    def get_album(self, album_id: str) -> dict[str, Any]:
        return self._album_details[album_id]

    def get_tracks(self, track_ids: list[str]) -> list[dict[str, Any]]:
        found = []
        for album in self._album_details.values():
            for track in album["tracks"]["items"]:
                if track["id"] in track_ids:
                    found.append(track)
        return found

    def download(self, url: str) -> bytes:
        self.downloaded.append(url)
        return b"fake-cover-bytes"


def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    return repo


def write_roster(repo: Path, artists: list[dict[str, Any]]) -> Path:
    path = repo / "content" / "import-review" / "spotify-roster.yaml"
    path.write_text(yaml.safe_dump({"artists": artists}, sort_keys=False))
    return path


def track(track_id: str, name: str, isrc: str | None = None) -> dict[str, Any]:
    return {
        "id": track_id,
        "name": name,
        "duration_ms": 210000,
        "explicit": False,
        "preview_url": None,
        "external_ids": {"isrc": isrc},
    }


def album(
    album_id: str,
    name: str,
    artist_id: str,
    tracks: list[dict[str, Any]],
    release_date: str = "2025-02-15",
    precision: str = "day",
    upc: str | None = None,
) -> dict[str, Any]:
    return {
        "id": album_id,
        "name": name,
        "release_date": release_date,
        "release_date_precision": precision,
        "label": "Maricopa Records",
        "external_ids": {"upc": upc},
        "external_urls": {"spotify": f"https://open.spotify.com/album/{album_id}"},
        "images": [{"url": f"https://img.example/{album_id}.jpg"}],
        "artists": [{"id": artist_id}],
        "tracks": {"items": tracks},
    }


def test_known_artist_matches_existing_release_and_proposes_isrc_patch(tmp_path):
    repo = content_repo(tmp_path)
    roster_path = write_roster(repo, [{"artist_id": "pcbender", "spotify_url": None}])

    pcbender_id = "0aivrU155laeOcIoT4AhPo"
    circuiting = album(
        "alb1",
        "Circuiting",
        pcbender_id,
        [
            track("t1", "Conductor", isrc="USXXX0000001"),
            track("t2", "Resistor", isrc="USXXX0000002"),
            track("t3", "Capacitor"),
            track("t4", "Inductor"),
            track("t5", "Diode"),
            track("t6", "Transistor"),
            track("t7", "Relay"),
            track("t8", "Fuse"),
            track("t9", "Oscillator"),
            track("t10", "Circuit"),
        ],
    )
    client = FakeSpotifyClient(
        artists={
            pcbender_id: {
                "name": "PCBender",
                "images": [{"url": "https://img.example/pcbender.jpg"}],
                "external_urls": {"spotify": f"https://open.spotify.com/artist/{pcbender_id}"},
            }
        },
        albums_by_artist={pcbender_id: [{"id": "alb1", "name": "Circuiting", "release_date": "2025-02-15", "artists": [{"id": pcbender_id}]}]},
        album_details={"alb1": circuiting},
    )

    report = import_spotify(repo, roster=roster_path, client=client)

    assert report["status"] == "passed"
    assert report["summary"]["matched_existing"] == 1
    assert report["summary"]["release_candidates"] == 0

    artists = yaml.safe_load((repo / "content/import-review/spotify-artists.yaml").read_text())
    assert artists["candidates"][0]["artist"]["review_status"] == "known_artist"

    releases = yaml.safe_load((repo / "content/import-review/spotify-releases.yaml").read_text())
    matched = releases["candidates"][0]["release"]
    assert matched["review_status"] == "matched_existing"
    assert matched["existing_path"] == "content/releases/circuiting.json"
    patch_isrcs = {p["title"]: p["isrc"] for p in matched["proposed_patch"]["tracks_isrc"]}
    assert patch_isrcs == {"Conductor": "USXXX0000001", "Resistor": "USXXX0000002"}


def test_new_artist_single_and_ep_with_partial_date(tmp_path):
    repo = content_repo(tmp_path)
    artist_spotify_id = "49lxwccrBkArWVhPknMJtz"
    roster_path = write_roster(
        repo,
        [
            {
                "artist_id": "nova-test-artist",
                "spotify_url": f"https://open.spotify.com/artist/{artist_spotify_id}",
            }
        ],
    )

    single = album("alb-single", "Lonely Highway", artist_spotify_id, [track("s1", "Lonely Highway")], release_date="2026-03-01")
    ep = album(
        "alb-ep",
        "Short Stories",
        artist_spotify_id,
        [track("e1", "First"), track("e2", "Second"), track("e3", "Third")],
        release_date="2025",
        precision="year",
    )
    client = FakeSpotifyClient(
        artists={
            artist_spotify_id: {
                "name": "Nova Test Artist",
                "images": [{"url": "https://img.example/nova-test-artist.jpg"}],
                "external_urls": {"spotify": f"https://open.spotify.com/artist/{artist_spotify_id}"},
            }
        },
        albums_by_artist={
            artist_spotify_id: [
                {"id": "alb-single", "name": "Lonely Highway", "release_date": "2026-03-01", "artists": [{"id": artist_spotify_id}]},
                {"id": "alb-ep", "name": "Short Stories", "release_date": "2025", "artists": [{"id": artist_spotify_id}]},
            ]
        },
        album_details={"alb-single": single, "alb-ep": ep},
    )

    report = import_spotify(repo, roster=roster_path, client=client)

    assert report["summary"]["release_candidates"] == 2
    assert report["summary"]["matched_existing"] == 0

    artists = yaml.safe_load((repo / "content/import-review/spotify-artists.yaml").read_text())
    assert artists["candidates"][0]["artist"]["review_status"] == "needs_review"
    assert artists["candidates"][0]["artist"]["id"] == "nova-test-artist"

    releases = {
        r["release"]["title"]: r["release"]
        for r in yaml.safe_load((repo / "content/import-review/spotify-releases.yaml").read_text())["candidates"]
    }
    assert releases["Lonely Highway"]["model"] == "song"
    assert releases["Lonely Highway"]["release_type"] == "single"
    assert releases["Lonely Highway"]["release_date"] == "2026-03-01"

    short_stories = releases["Short Stories"]
    assert short_stories["model"] == "album"
    assert short_stories["release_type"] == "ep"
    assert short_stories["release_date"] is None
    assert any("precision was 'year'" in note for note in short_stories["notes"])

    assets = yaml.safe_load((repo / "content/import-review/spotify-assets.yaml").read_text())
    assert len(assets["candidates"]) == 2
    assert client.downloaded == []


def test_download_covers_writes_files_with_checksum(tmp_path):
    repo = content_repo(tmp_path)
    artist_spotify_id = "1bpeEWD8VsTewFr5FKOKv0"
    roster_path = write_roster(
        repo,
        [{"artist_id": "michael-anthony-rose", "spotify_url": f"https://open.spotify.com/artist/{artist_spotify_id}"}],
    )
    single = album("alb-x", "New Track", artist_spotify_id, [track("x1", "New Track")])
    client = FakeSpotifyClient(
        artists={
            artist_spotify_id: {
                "name": "Michael Anthony Rose",
                "images": [],
                "external_urls": {"spotify": f"https://open.spotify.com/artist/{artist_spotify_id}"},
            }
        },
        albums_by_artist={
            artist_spotify_id: [{"id": "alb-x", "name": "New Track", "release_date": "2025-02-15", "artists": [{"id": artist_spotify_id}]}]
        },
        album_details={"alb-x": single},
    )

    import_spotify(repo, roster=roster_path, download_covers=True, client=client)

    assert client.downloaded == ["https://img.example/alb-x.jpg"]
    cover_path = repo / "content/import-review/spotify-assets/michael-anthony-rose/new-track/cover.jpg"
    assert cover_path.read_bytes() == b"fake-cover-bytes"
    assets = yaml.safe_load((repo / "content/import-review/spotify-assets.yaml").read_text())
    assert assets["candidates"][0]["sha256"] == hashlib.sha256(b"fake-cover-bytes").hexdigest()
