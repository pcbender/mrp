"""Unit tests for the admin Catalog page helpers.

Covers flattening every track across releases into one list, the search /
artist filter, and the row → track-editor linkage.
"""

import yaml

from mrp.admin.routes.catalog import (
    _duration_seconds,
    _filter_tracks,
    _load_all_tracks,
    _release_songs,
    _sort_tracks,
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
        "status": "live", "release_date": "2026-01-01", "distributor": "landr",
        "song": {"title": "Lonely Road", "slug": "lonely-road", "isrc": "US-ABC-26-001",
                 "explicit": False, "instrumental": False, "duration": "3:20"},
    })
    # An album: songs live under `tracks[]`
    _write_release(tmp_path, "night-drive", {
        "title": "Night Drive", "artist_id": "4castle", "model": "album",
        "status": "draft", "release_date": "2026-05-01", "distributor": "amuse",
        "tracks": [
            {"title": "Ignition", "slug": "ignition", "number": 1, "isrc": "US-XYZ-26-010",
             "explicit": True, "instrumental": False, "duration": "2:58"},
            {"title": "Coast", "slug": "coast", "number": 2,
             "explicit": False, "instrumental": True, "duration": "10:05"},
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
    ignition = next(r for r in rows if r["track_slug"] == "ignition")
    assert ignition["isrc"] == "US-XYZ-26-010"
    assert coast["isrc"] == ""  # missing ISRC surfaces as empty string


def test_load_all_tracks_orders_newest_release_first(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    # night-drive (2026-05) tracks precede lonely-road (2026-01)
    assert rows[0]["release_slug"] == "night-drive"
    assert rows[-1]["track_slug"] == "lonely-road"


# --- _filter_tracks ----------------------------------------------------------

def test_filter_by_search_matches_title_artist_release(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    assert {r["track_slug"] for r in _filter_tracks(rows, "coast", "", "")} == {"coast"}
    # artist name search
    assert {r["track_slug"] for r in _filter_tracks(rows, "4castle", "", "")} == {"ignition", "coast"}
    # release-title search
    assert {r["track_slug"] for r in _filter_tracks(rows, "night drive", "", "")} == {"ignition", "coast"}


def test_filter_by_artist(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    got = _filter_tracks(rows, "", "pcbender", "")
    assert {r["track_slug"] for r in got} == {"lonely-road"}


def test_filter_by_distributor(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    assert {r["track_slug"] for r in _filter_tracks(rows, "", "", "amuse")} == {"ignition", "coast"}
    assert {r["track_slug"] for r in _filter_tracks(rows, "", "", "landr")} == {"lonely-road"}


def test_distributor_carried_on_rows(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    dist = {r["track_slug"]: r["distributor"] for r in rows}
    assert dist == {"lonely-road": "landr", "ignition": "amuse", "coast": "amuse"}


def test_filter_empty_returns_all(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    assert len(_filter_tracks(rows, "", "", "")) == 3


# --- _duration_seconds -------------------------------------------------------

def test_duration_seconds_parses_and_orders_numerically():
    assert _duration_seconds("2:58") == 178
    assert _duration_seconds("10:05") == 605
    assert _duration_seconds("1:00:00") == 3600
    # blank / unparseable sort first
    assert _duration_seconds("") == -1
    assert _duration_seconds("n/a") == -1


# --- _sort_tracks ------------------------------------------------------------

def test_sort_by_title_asc_and_desc(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    asc = [r["track_slug"] for r in _sort_tracks(rows, "title", "asc")]
    assert asc == ["coast", "ignition", "lonely-road"]
    desc = [r["track_slug"] for r in _sort_tracks(rows, "title", "desc")]
    assert desc == ["lonely-road", "ignition", "coast"]


def test_sort_by_duration_is_numeric_not_lexical(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    asc = [r["track_slug"] for r in _sort_tracks(rows, "duration", "asc")]
    # 2:58 < 3:20 < 10:05 — lexical order would wrongly put 10:05 first
    assert asc == ["ignition", "lonely-road", "coast"]


def test_sort_by_isrc_puts_empty_last_ascending(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    asc = [r["track_slug"] for r in _sort_tracks(rows, "isrc", "asc")]
    # coast has no ISRC → sorts last regardless of direction being asc
    assert asc[-1] == "coast"
    assert asc[:2] == ["lonely-road", "ignition"]  # US-ABC < US-XYZ


def test_sort_by_date(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    asc = [r["track_slug"] for r in _sort_tracks(rows, "date", "asc")]
    # lonely-road 2026-01-01 before night-drive tracks 2026-05-01
    assert asc[0] == "lonely-road"
    desc = [r["track_slug"] for r in _sort_tracks(rows, "date", "desc")]
    assert desc[-1] == "lonely-road"


def test_sort_by_distributor(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    asc = [r["distributor"] for r in _sort_tracks(rows, "distributor", "asc")]
    assert asc == ["amuse", "amuse", "landr"]


def test_sort_by_streams_is_numeric():
    rows = [
        {"track_slug": "a", "streams": 90},
        {"track_slug": "b", "streams": 1000},
        {"track_slug": "c", "streams": 0},
    ]
    asc = [r["track_slug"] for r in _sort_tracks(rows, "streams", "asc")]
    assert asc == ["c", "a", "b"]
    desc = [r["track_slug"] for r in _sort_tracks(rows, "streams", "desc")]
    assert desc == ["b", "a", "c"]


def test_sort_unknown_key_keeps_default_order(tmp_path):
    rows = _load_all_tracks(_repo(tmp_path))
    assert _sort_tracks(rows, "", "asc") == rows
    assert _sort_tracks(rows, "number", "asc") == rows  # '#' is not sortable
