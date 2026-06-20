import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_record(path: Path, key: str) -> dict:
    if path.suffix == ".json":
        return json.loads(path.read_text())[key]
    return yaml.safe_load(path.read_text())[key]


def test_imported_artist_metadata_is_public_and_image_backed():
    artists = {
        path.stem: load_record(path, "artist")
        for path in sorted((ROOT / "content/artists").glob("*"))
        if path.suffix in {".json", ".yaml", ".yml"}
    }

    assert set(artists) == {"4castle", "lingua-aeternum", "pcbender", "stab"}
    assert all(artist["visibility"] == "public" for artist in artists.values())
    assert artists["4castle"]["image"].startswith("/assets/migrated/")
    assert artists["stab"]["image"].startswith("/assets/wp/")


def test_imported_release_metadata_is_visible_and_local_asset_backed():
    releases = {
        path.stem: load_record(path, "release")
        for path in sorted((ROOT / "content/releases").glob("*"))
        if path.suffix in {".json", ".yaml", ".yml"}
    }

    imported = {slug: release for slug, release in releases.items() if slug != "circuiting"}
    assert len(releases) == 32
    assert all(release["status"] == "staged" for release in imported.values())
    assert all(release["cover_image"].startswith("site/public/assets/migrated/") for release in imported.values())
    assert releases["abundant-emptiness"]["model"] == "song"
    assert releases["distance-not-safety"]["model"] == "album"
    assert releases["distance-not-safety"]["release_type"] == "album"
    assert len(releases["distance-not-safety"]["tracks"]) == 10
    assert releases["winds-of-change"]["tracks"][0]["links"]["spotify"].startswith("https://open.spotify.com/track/")
