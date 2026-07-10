"""Unit tests for the admin Catalog page helpers.

Covers flattening every track across releases into one list, the search /
artist filter, and the row → track-editor linkage.
"""

import yaml

from mrp.admin.routes.catalog import (
    _filter_tracks,
    _load_all_tracks,
    _release_songs,
)


def _write_artist(root, artist_id, name):
    (root / "content" / "artists").mkdir(parents=True, exist_ok=True)
    record = {"artist": {"id": artist_id, "name": name, "visibility": "public"}}
    (root / "content" / "artists" / f"{artist_id}.yaml").write_text(yaml.safe_dump(record))


def _write_release(root, slug, rel):
    (root / "content" / "releases").mkdir(parents=True, exist_ok=True)
    (root / "content" / "releases" / f"{slug}.yaml").write_text(
        yaml.safe_dump({"release": rel})
    )


def _repo(tmp_path):
    _write_artist(tmp_path, "pcbender", "pcbender")
    _write_artist(tmp_path, "4castle", "4Castle")
    # A single: song lives under `song`
    _write_release(tmp_path, "lonely-road", {
        "title": "Lonely Road", "artist_id": "pcbender", "model": "song",
        "status": "live", "release_date": "2026-01-01",
        "song": {"title": "Lonely Road", "slug": "lonely-road",
                 "explicit": False, "instrumental": False, "duration": "3:20"},
    })
    # An album: songs live under `tracks[]`
    _write_release(tmp_path, "night-drive", {
        "title": "Night Drive", "artist_id": "4castle", "model": "album",
        "status": "draft", "release_date": "2026-05-01",
        "tracks": [
            {"title": "Ignition", "slug": "ignition", "number": 1,
             "explicit": True, "instrumental": False, "duration": "2:58"},
            {"title": "Coast", "slug": "coast", "number": 2,
             "explicit": False, "instrumental": True, "duration": "4:10"},
        ],
    })
    return tmp_path


# --- _release_songs ----------------------------------------------------------

def test_release_songs_handles_single_and_album():
    assert len(_release_songs({"song": {"slug": "x"}})) == 1
    assert len(_release_songs({"tracks": [{"slug": "a"}, {"slug": "b"}]})) == 2
    assert _release_songs({}) == []


# --- _load_all_tracks --------------------------------------------------------

def test_load_all_tracks_flattens_every_track(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    slugs = {r["track_slug"] for r in rows}
    assert slugs == {"lonely-road", "ignition", "coast"}
    assert len(rows) == 3


def test_load_all_tracks_carries_release_and_artist_context(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    coast = next(r for r in rows if r["track_slug"] == "coast")
    assert coast["release_slug"] == "night-drive"
    assert coast["release_title"] == "Night Drive"
    assert coast["artist_id"] == "4castle"
    assert coast["artist_name"] == "4Castle"  # resolved from artist record
    assert coast["instrumental"] is True
    assert coast["number"] == 2


def test_load_all_tracks_orders_newest_release_first(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    # night-drive (2026-05) tracks precede lonely-road (2026-01)
    assert rows[0]["release_slug"] == "night-drive"
    assert rows[-1]["track_slug"] == "lonely-road"


# --- _filter_tracks ----------------------------------------------------------

def test_filter_by_search_matches_title_artist_release(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    assert {r["track_slug"] for r in _filter_tracks(rows, "coast", "")} == {"coast"}
    # artist name search
    assert {r["track_slug"] for r in _filter_tracks(rows, "4castle", "")} == {"ignition", "coast"}
    # release-title search
    assert {r["track_slug"] for r in _filter_tracks(rows, "night drive", "")} == {"ignition", "coast"}


def test_filter_by_artist(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    got = _filter_tracks(rows, "", "pcbender")
    assert {r["track_slug"] for r in got} == {"lonely-road"}


def test_filter_empty_returns_all(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    assert len(_filter_tracks(rows, "", "")) == 3
