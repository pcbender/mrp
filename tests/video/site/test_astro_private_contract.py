from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path

import pytest
import yaml

from mrp.core.build import build_repository


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "video" / "fixtures" / "releases"
BUILD_CASES = [
    (
        "enriched-single.yaml",
        "song",
        [Path("releases/single-video-contract/index.html")],
    ),
    (
        "enriched-album.yaml",
        "tracks",
        [
            Path("releases/video-contract/index.html"),
            Path("releases/video-contract/private-track/index.html"),
        ],
    ),
]


def _write_yaml(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")


def _site_repo(tmp_path: Path, record: dict) -> Path:
    repo = tmp_path / "repo"
    content = repo / "content"
    (content / "artists").mkdir(parents=True)
    (content / "releases").mkdir(parents=True)
    shutil.copy2(ROOT / "tests" / "fixtures" / "content" / "valid" / "site.yaml", content / "site.yaml")
    shutil.copy2(
        ROOT / "tests" / "fixtures" / "content" / "valid" / "artist.yaml",
        content / "artists" / "pcbender.yaml",
    )
    release_slug = record["release"]["slug"]
    _write_yaml(content / "releases" / f"{release_slug}.yaml", record)

    shutil.copytree(
        ROOT / "site",
        repo / "site",
        ignore=shutil.ignore_patterns("node_modules", "public", "dist", ".astro"),
    )
    os.symlink(ROOT / "site" / "node_modules", repo / "site" / "node_modules", target_is_directory=True)
    os.symlink(ROOT / "site" / "public", repo / "site" / "public", target_is_directory=True)
    return repo


def _assert_build_passed(result: dict) -> Path:
    assert result["status"] == "passed", (
        result.get("message"),
        result.get("stdout"),
        result.get("stderr"),
        result.get("errors"),
    )
    return Path(result["build_path"])


def _page_text(build_path: Path, relevant_pages: list[Path]) -> dict[Path, str]:
    return {
        relative: (build_path / relative).read_text(encoding="ascii")
        for relative in relevant_pages
    }


def _emitted_browser_text(build_path: Path) -> str:
    browser_suffixes = {".html", ".xml", ".json", ".js"}
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(build_path.rglob("*"))
        if path.is_file() and path.suffix.lower() in browser_suffixes
    )


@pytest.mark.parametrize(
    ("fixture_name", "track_container", "relevant_pages"),
    BUILD_CASES,
    ids=["single", "album"],
)
def test_unpublished_video_fields_do_not_change_or_leak_into_astro(
    tmp_path: Path,
    monkeypatch,
    fixture_name: str,
    track_container: str,
    relevant_pages: list[Path],
):
    enriched = yaml.safe_load((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    legacy = copy.deepcopy(enriched)
    enriched_release = enriched["release"]
    legacy_release = legacy["release"]
    enriched_track = (
        enriched_release["song"]
        if track_container == "song"
        else enriched_release["tracks"][0]
    )
    legacy_track = (
        legacy_release["song"]
        if track_container == "song"
        else legacy_release["tracks"][0]
    )
    private_values = [
        enriched_track["master_path"],
        *(stem["path"] for stem in enriched_track["stems"]),
        enriched_track["music_video"]["project"],
    ]
    legacy_track.pop("stems")
    legacy_track.pop("music_video")
    repo = _site_repo(tmp_path, legacy)

    monkeypatch.setenv("MRP_SITE_OUT_ROOT", str(tmp_path / "site-output"))
    monkeypatch.setenv("MRP_PREVIEW_DRAFTS", "1")
    monkeypatch.setenv("MRP_PRUNE_DISABLE", "1")

    legacy_build = _assert_build_passed(build_repository(repo))
    legacy_pages = _page_text(legacy_build, relevant_pages)

    release_path = repo / "content" / "releases" / f"{enriched_release['slug']}.yaml"
    _write_yaml(release_path, enriched)
    enriched_build = _assert_build_passed(build_repository(repo))
    enriched_pages = _page_text(enriched_build, relevant_pages)

    assert enriched_pages == legacy_pages
    relevant_html = "\n".join(enriched_pages.values())
    browser_text = _emitted_browser_text(enriched_build)
    assert "public lyric stays visible" in relevant_html
    assert "<video" not in relevant_html
    for private_value in private_values:
        assert private_value not in browser_text


@pytest.mark.parametrize(
    ("fixture_name", "track_container", "page"),
    [
        (
            "enriched-single.yaml",
            "song",
            Path("releases/single-video-contract/index.html"),
        ),
        (
            "enriched-album.yaml",
            "tracks",
            Path("releases/video-contract/private-track/index.html"),
        ),
    ],
    ids=["single", "album"],
)
def test_only_opted_in_published_video_reaches_astro_and_public_metadata(
    tmp_path: Path,
    monkeypatch,
    fixture_name: str,
    track_container: str,
    page: Path,
):
    record = yaml.safe_load((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    release = record["release"]
    track = release["song"] if track_container == "song" else release["tracks"][0]
    private_values = [
        track["master_path"],
        *(stem["path"] for stem in track["stems"]),
        track["music_video"]["project"],
    ]
    key = f"{release['artist_id']}--{track['slug']}"
    video_relative = Path("music-videos") / key / "published-hash" / "video.mp4"
    poster_relative = (
        Path("music-videos") / key / "published-hash" / "poster-cover.jpg"
    )
    track["music_video"].update(
        {
            "status": "published",
            "opt_in": True,
            "public_url": f"/media/{video_relative.as_posix()}",
            "poster": f"/media/{poster_relative.as_posix()}",
        }
    )
    repo = _site_repo(tmp_path, record)
    media_root = tmp_path / "public-media"
    (media_root / video_relative).parent.mkdir(parents=True)
    (media_root / video_relative).write_bytes(b"public mp4")
    (media_root / poster_relative).write_bytes(b"public poster")
    monkeypatch.setenv("MRP_PUBLIC_MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("MRP_SITE_OUT_ROOT", str(tmp_path / "site-output"))
    monkeypatch.setenv("MRP_PREVIEW_DRAFTS", "1")
    monkeypatch.setenv("MRP_PRUNE_DISABLE", "1")

    build = _assert_build_passed(build_repository(repo))
    html = (build / page).read_text(encoding="ascii")
    browser_text = _emitted_browser_text(build)

    assert "<video" in html
    assert track["music_video"]["public_url"] in html
    assert track["music_video"]["poster"] in html
    assert "VideoObject" in html
    assert (build / "media" / video_relative).read_bytes() == b"public mp4"
    assert (build / "media" / poster_relative).read_bytes() == b"public poster"
    for private_value in private_values:
        assert private_value not in browser_text


def test_published_video_without_opt_in_is_not_rendered_or_copied(
    tmp_path: Path,
    monkeypatch,
):
    record = yaml.safe_load(
        (FIXTURES / "enriched-album.yaml").read_text(encoding="utf-8")
    )
    track = record["release"]["tracks"][0]
    video_relative = Path("music-videos/pcbender--private-track/hash/video.mp4")
    poster_relative = Path("music-videos/pcbender--private-track/hash/poster.jpg")
    track["music_video"].update(
        {
            "status": "published",
            "opt_in": False,
            "public_url": f"/media/{video_relative.as_posix()}",
            "poster": f"/media/{poster_relative.as_posix()}",
        }
    )
    repo = _site_repo(tmp_path, record)
    media_root = tmp_path / "public-media"
    (media_root / video_relative).parent.mkdir(parents=True)
    (media_root / video_relative).write_bytes(b"public mp4")
    (media_root / poster_relative).write_bytes(b"public poster")
    monkeypatch.setenv("MRP_PUBLIC_MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("MRP_SITE_OUT_ROOT", str(tmp_path / "site-output"))
    monkeypatch.setenv("MRP_PREVIEW_DRAFTS", "1")
    monkeypatch.setenv("MRP_PRUNE_DISABLE", "1")

    build = _assert_build_passed(build_repository(repo))
    page = build / "releases/video-contract/private-track/index.html"
    html = page.read_text(encoding="ascii")
    browser_text = _emitted_browser_text(build)

    assert "<video" not in html
    assert track["music_video"]["public_url"] not in browser_text
    assert track["music_video"]["poster"] not in browser_text
    assert not (build / "media" / video_relative).exists()
    assert not (build / "media" / poster_relative).exists()


def test_opted_in_video_with_missing_durable_media_blocks_build(
    tmp_path: Path,
    monkeypatch,
):
    record = yaml.safe_load(
        (FIXTURES / "enriched-single.yaml").read_text(encoding="utf-8")
    )
    track = record["release"]["song"]
    track["music_video"].update(
        {
            "status": "published",
            "opt_in": True,
            "public_url": "/media/music-videos/pcbender--single-video-track/hash/video.mp4",
            "poster": "/media/music-videos/pcbender--single-video-track/hash/poster.jpg",
        }
    )
    repo = _site_repo(tmp_path, record)
    monkeypatch.setenv("MRP_PUBLIC_MEDIA_ROOT", str(tmp_path / "public-media"))
    monkeypatch.setenv("MRP_SITE_OUT_ROOT", str(tmp_path / "site-output"))
    monkeypatch.setenv("MRP_PREVIEW_DRAFTS", "1")
    monkeypatch.setenv("MRP_PRUNE_DISABLE", "1")

    result = build_repository(repo)

    assert result["status"] == "failed"
    assert result["stage"] == "static_build"
    assert "missing from durable media" in result["message"]
