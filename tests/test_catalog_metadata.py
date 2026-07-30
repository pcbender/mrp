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

    # The 4 WXR-migrated artists must remain present; later imports (e.g.
    # Spotify catalog backfill) only add to the roster, never replace it.
    assert {"4castle", "lingua-aeternum", "pcbender", "stab"}.issubset(set(artists))
    assert all(artist["visibility"] == "public" for artist in artists.values())

    # Every artist image resolves to a file the site actually ships. Which
    # directory it lives in is not the invariant: images migrate off the
    # WP-clone path to the native artists dir as identity work reaches each
    # artist, and pinning one artist to one path just rots on the next move.
    missing = {
        slug: artist.get("image")
        for slug, artist in artists.items()
        if not artist.get("image")
        or not (ROOT / "site/public" / str(artist["image"]).lstrip("/")).is_file()
    }
    assert not missing


def test_imported_release_metadata_is_visible_and_local_asset_backed():
    releases = {
        path.stem: load_record(path, "release")
        for path in sorted((ROOT / "content/releases").glob("*"))
        if path.suffix in {".json", ".yaml", ".yml"}
    }

    # Scope to the WXR-migrated batch specifically (identified by its asset
    # convention); later imports (e.g. Spotify catalog backfill) use a
    # different cover_image path and are covered by their own tests.
    imported = {
        slug: release
        for slug, release in releases.items()
        if release["cover_image"].startswith("site/public/assets/migrated/")
    }
    assert len(imported) == 32
    # The batch was imported as "staged" but records advance along the publish
    # ladder over time; the invariant is that none regress to a broken or
    # hidden state.
    assert all(
        release["status"] in {"staged", "verified", "approved", "live"} for release in imported.values()
    )
    assert releases["abundant-emptiness"]["model"] == "song"
    assert releases["distance-not-safety"]["model"] == "album"
    assert releases["distance-not-safety"]["release_type"] == "album"
    assert len(releases["distance-not-safety"]["tracks"]) == 10
    assert releases["winds-of-change"]["tracks"][0]["links"]["spotify"].startswith("https://open.spotify.com/track/")
