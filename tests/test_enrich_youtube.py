from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from mrp.core.enrich_youtube import enrich_youtube

ROOT = Path(__file__).resolve().parents[1]


class FakeYouTubeClient:
    def __init__(
        self,
        uploads_playlist_by_channel: dict[str, str] | None = None,
        videos_by_playlist: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self._uploads_playlist_by_channel = uploads_playlist_by_channel or {}
        self._videos_by_playlist = videos_by_playlist or {}
        self.channel_calls: list[str] = []
        self.playlist_calls: list[str] = []

    def get_uploads_playlist_id(self, channel_id: str) -> str | None:
        self.channel_calls.append(channel_id)
        return self._uploads_playlist_by_channel.get(channel_id)

    def get_playlist_videos(self, playlist_id: str) -> list[dict[str, Any]]:
        self.playlist_calls.append(playlist_id)
        return self._videos_by_playlist.get(playlist_id, [])


def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    return repo


def reset_youtube_links(path: Path) -> dict[str, Any]:
    """Force a clean (no youtube/youtube_music) starting state, independent of
    whatever a real enrichment run may have already written into this fixture."""
    data = yaml.safe_load(path.read_text())
    release = data["release"]
    for key in ("youtube", "youtube_music"):
        release.get("links", {}).pop(key, None)
    for track in release.get("tracks") or []:
        if isinstance(track, dict) and "links" in track:
            for key in ("youtube", "youtube_music"):
                track["links"].pop(key, None)
            if not track["links"]:
                del track["links"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return release


PCBENDER_CHANNEL = "UCvNXkiIHQJM-uY4MT3gmKDw"
PCBENDER_UPLOADS = "UUvNXkiIHQJM-uY4MT3gmKDw"

MADE_BY_MOVING_VIDEOS = [
    {"title": "Confused By Your Wires", "videoId": "abc123"},
    {"title": "Inner Outer (Official Audio)", "videoId": "def456"},
]


def test_enrich_youtube_backfills_release_and_track_links(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    before = reset_youtube_links(path)
    assert before["links"].get("youtube") is None
    assert all("links" not in track or "youtube" not in track.get("links", {}) for track in before["tracks"])

    client = FakeYouTubeClient(
        uploads_playlist_by_channel={PCBENDER_CHANNEL: PCBENDER_UPLOADS},
        videos_by_playlist={PCBENDER_UPLOADS: MADE_BY_MOVING_VIDEOS},
    )

    report = enrich_youtube(repo, delay_seconds=0, client=client)

    assert report["summary"]["tracks_patched"] == 2
    after = yaml.safe_load(path.read_text())["release"]
    tracks_by_slug = {t["slug"]: t for t in after["tracks"]}
    assert tracks_by_slug["confused-by-your-wires"]["links"]["youtube"] == "https://www.youtube.com/watch?v=abc123"
    assert tracks_by_slug["confused-by-your-wires"]["links"]["youtube_music"] == "https://music.youtube.com/watch?v=abc123"
    # Suffix "(Official Audio)" stripped for matching against our plain title "Inner Outer".
    assert tracks_by_slug["inner-outer"]["links"]["youtube"] == "https://www.youtube.com/watch?v=def456"
    # No video supplied for this track; must stay untouched.
    assert "links" not in tracks_by_slug["riddles-abound"] or "youtube" not in tracks_by_slug["riddles-abound"]["links"]


def test_enrich_youtube_never_overwrites_existing_value(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    data = yaml.safe_load(path.read_text())
    data["release"]["links"]["youtube"] = "https://www.youtube.com/watch?v=already-set"
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    client = FakeYouTubeClient(
        uploads_playlist_by_channel={PCBENDER_CHANNEL: PCBENDER_UPLOADS},
        videos_by_playlist={PCBENDER_UPLOADS: [{"title": "Made By Moving", "videoId": "different"}]},
    )

    enrich_youtube(repo, delay_seconds=0, client=client)

    after = yaml.safe_load(path.read_text())["release"]
    assert after["links"]["youtube"] == "https://www.youtube.com/watch?v=already-set"


def test_enrich_youtube_skips_artists_without_channel_link(tmp_path):
    repo = content_repo(tmp_path)
    reset_youtube_links(repo / "content/releases/made-by-moving.yaml")
    artist_path = repo / "content/artists/pcbender.json"
    import json

    artist_data = json.loads(artist_path.read_text())
    artist_data["artist"]["links"]["youtube"] = None
    artist_path.write_text(json.dumps(artist_data, indent=2))

    client = FakeYouTubeClient(
        uploads_playlist_by_channel={PCBENDER_CHANNEL: PCBENDER_UPLOADS},
        videos_by_playlist={PCBENDER_UPLOADS: MADE_BY_MOVING_VIDEOS},
    )

    report = enrich_youtube(repo, delay_seconds=0, client=client)

    assert PCBENDER_CHANNEL not in client.channel_calls
    assert report["summary"]["skipped_no_youtube_channel"] >= 1


def test_enrich_youtube_reports_fully_unmatched_release(tmp_path):
    repo = content_repo(tmp_path)
    reset_youtube_links(repo / "content/releases/made-by-moving.yaml")

    client = FakeYouTubeClient(
        uploads_playlist_by_channel={PCBENDER_CHANNEL: PCBENDER_UPLOADS},
        videos_by_playlist={PCBENDER_UPLOADS: [{"title": "Some Unrelated Video", "videoId": "zzz"}]},
    )

    report = enrich_youtube(repo, delay_seconds=0, client=client)

    assert "content/releases/made-by-moving.yaml" in report["fully_unmatched_release_paths"]


def test_enrich_youtube_dry_run_does_not_write(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    reset_youtube_links(path)
    before_text = path.read_text()

    client = FakeYouTubeClient(
        uploads_playlist_by_channel={PCBENDER_CHANNEL: PCBENDER_UPLOADS},
        videos_by_playlist={PCBENDER_UPLOADS: MADE_BY_MOVING_VIDEOS},
    )

    report = enrich_youtube(repo, delay_seconds=0, dry_run=True, client=client)

    assert report["summary"]["tracks_patched"] == 2
    assert path.read_text() == before_text
    assert "report_path" not in report


def test_enrich_youtube_fails_cleanly_without_api_key(tmp_path):
    repo = content_repo(tmp_path)
    report = enrich_youtube(repo, delay_seconds=0, client=None)
    # No client and no GOOGLE_SERVICE_API_KEY in this isolated tmp_path repo.
    assert report["status"] == "failed"
