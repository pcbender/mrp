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
