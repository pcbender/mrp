from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from mrp.core.enrich_links import enrich_links
from mrp.core.odesli_client import OdesliRateLimitedError

ROOT = Path(__file__).resolve().parents[1]


class FakeOdesliClient:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def get_links(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        return self._responses.get(url, {})


class AlwaysRateLimitedClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_links(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        raise OdesliRateLimitedError(f"rate-limited for {url}")


def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    return repo


def odesli_payload(platforms: dict[str, str]) -> dict[str, Any]:
    return {"linksByPlatform": {key: {"url": url} for key, url in platforms.items()}}


def test_enrich_links_backfills_only_null_platform_fields(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/a-candle-deep.yaml"
    before = yaml.safe_load(path.read_text())["release"]
    spotify_url = before["links"]["spotify"]
    assert before["links"].get("apple_music") is None
    assert before["links"].get("tidal") is None

    client = FakeOdesliClient(
        {
            spotify_url: odesli_payload(
                {
                    "appleMusic": "https://music.apple.com/us/album/example/1",
                    "tidal": "https://listen.tidal.com/album/123",
                    "spotify": spotify_url,
                }
            )
        }
    )

    report = enrich_links(repo, delay_seconds=0, client=client)

    assert report["status"] == "passed"
    assert report["summary"]["releases_patched"] == 1
    after = yaml.safe_load(path.read_text())["release"]
    assert after["links"]["apple_music"] == "https://music.apple.com/us/album/example/1"
    assert after["links"]["tidal"] == "https://listen.tidal.com/album/123"
    assert after["links"]["spotify"] == spotify_url


def test_enrich_links_never_overwrites_existing_value(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/bent.yaml"
    data = yaml.safe_load(path.read_text())
    data["release"]["links"]["apple_music"] = "https://music.apple.com/us/album/already-set/1"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    spotify_url = data["release"]["links"]["spotify"]

    client = FakeOdesliClient(
        {spotify_url: odesli_payload({"appleMusic": "https://music.apple.com/us/album/different/2"})}
    )

    report = enrich_links(repo, delay_seconds=0, client=client)

    assert report["summary"]["releases_patched"] == 0
    after = yaml.safe_load(path.read_text())["release"]
    assert after["links"]["apple_music"] == "https://music.apple.com/us/album/already-set/1"


def test_enrich_links_skips_releases_without_spotify_link(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/gone-and-forgotten.yaml"
    data = yaml.safe_load(path.read_text())
    data["release"]["links"]["spotify"] = None
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    client = FakeOdesliClient({})
    report = enrich_links(repo, delay_seconds=0, client=client)

    assert report["summary"]["skipped_no_spotify_link"] >= 1
    assert path.name not in {entry["path"].split("/")[-1] for entry in report["patched"]}


def test_enrich_links_dry_run_does_not_write(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/bent.yaml"
    before_text = path.read_text()
    spotify_url = yaml.safe_load(before_text)["release"]["links"]["spotify"]

    client = FakeOdesliClient({spotify_url: odesli_payload({"appleMusic": "https://music.apple.com/us/album/x/1"})})
    report = enrich_links(repo, delay_seconds=0, dry_run=True, client=client)

    assert report["summary"]["releases_patched"] == 1
    assert path.read_text() == before_text
    assert "report_path" not in report


def test_enrich_links_aborts_after_consecutive_rate_limits(tmp_path):
    repo = content_repo(tmp_path)
    client = AlwaysRateLimitedClient()

    report = enrich_links(repo, delay_seconds=0, client=client)

    assert report["status"] == "rate_limited"
    assert report["aborted_for_rate_limit"] is True
    assert report["summary"]["rate_limited"] == 3
    assert report["summary"]["releases_patched"] == 0
    # Stopped after 3 consecutive 429s rather than grinding through all 32
    # bundled fixture releases that have a spotify link.
    assert len(client.calls) == 3
