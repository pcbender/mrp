from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
import yaml
from pydantic import ValidationError
from starlette.requests import Request

from mrp.admin import db
from mrp.admin.routes import video as video_routes
from mrp.admin.video_timing import TimingEditorError, load_timing, save_timing
from mrp.core.migrate_site import load_structured_record
from mrp.video.project import AlignedLyricLine, LyricLine

ROOT = Path(__file__).resolve().parents[3]
ENRICHED = ROOT / "tests" / "video" / "fixtures" / "releases" / "enriched-album.yaml"


def _request(path: str, fields: list[tuple[str, str]], *, method: str = "POST") -> Request:
    body = urlencode(fields).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": (
                [(b"content-type", b"application/x-www-form-urlencoded")]
                if method == "POST"
                else []
            ),
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        },
        receive,
    )


def _release() -> dict:
    return yaml.safe_load(ENRICHED.read_text(encoding="utf-8"))["release"]


def _aligned() -> dict:
    return {
        "version": 1,
        "source": "lyrics.yaml",
        "alignment": {
            "algorithm_version": 1,
            "model": "whisper-1",
            "transcription_cache_key": "transcription-key",
            "source_hash": "source-hash",
            "vocals_hash": "vocals-hash",
            "warnings": ["verse line 2 is uncertain"],
        },
        "sections": [
            {
                "id": "verse",
                "type": "verse",
                "label": "Verse 1",
                "start": 0.0,
                "end": 4.0,
                "lines": [
                    {
                        "text": "First lyric",
                        "start": 0.0,
                        "end": 1.5,
                        "confidence": 0.98,
                        "status": "matched",
                    },
                    {
                        "text": "Needs attention",
                        "start": 1.5,
                        "end": 4.0,
                        "confidence": 0.52,
                        "status": "uncertain",
                    },
                ],
            },
            {
                "id": "break",
                "type": "instrumental",
                "label": "Instrumental",
                "start": 4.0,
                "end": 6.0,
                "lines": [],
            },
        ],
    }


def _write_timing(tmp_path: Path, release: dict) -> Path:
    key = f"{release['artist_id']}--{release['tracks'][0]['slug']}"
    path = tmp_path / "assets" / "source" / "video" / key / "lyrics.aligned.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(_aligned(), sort_keys=False), encoding="utf-8")
    preflight = tmp_path / "assets" / "processed" / "video" / key / "logs" / "preflight.json"
    preflight.parent.mkdir(parents=True)
    preflight.write_text(json.dumps({"status": "passed", "master_duration": 6.0}), encoding="utf-8")
    return path


def _fields(*, overlap: bool = False) -> dict[str, list[str]]:
    return {
        "section_id": ["verse", "break"],
        "section_start": ["0", "4"],
        "section_end": ["4", "6"],
        "section_reviewed": ["true", "true"],
        "line_key": ["verse:0", "verse:1"],
        "line_start": ["0", "1" if not overlap else "0.5"],
        "line_end": ["1", "4"],
        "line_reviewed": ["false", "true"],
    }


def _form_fields(fields: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(name, value) for name, values in fields.items() for value in values]


def test_review_markers_are_backward_compatible_and_structure_tags_are_not_cues():
    line = AlignedLyricLine(
        text="A real lyric",
        start=0,
        end=1,
        confidence=1,
        status="matched",
    )
    assert line.reviewed is None
    with pytest.raises(ValidationError, match="section labels"):
        LyricLine(text="[Verse]")


def test_load_timing_reports_confidence_review_and_master_duration(tmp_path: Path):
    release = _release()
    _write_timing(tmp_path, release)

    timing = load_timing(tmp_path, release, release["tracks"][0])

    assert timing["exists"] is True
    assert timing["master_duration"] == 6.0
    assert timing["summary"] == {
        "matched": 1,
        "uncertain": 1,
        "unmatched": 0,
        "sections": 2,
        "reviewed_sections": 0,
        "lines": 2,
        "reviewed_lines": 0,
        "pending_review": 1,
        "review_complete": False,
    }


def test_save_timing_atomically_persists_boundaries_and_review(tmp_path: Path):
    release = _release()
    path = _write_timing(tmp_path, release)

    result = save_timing(tmp_path, release, release["tracks"][0], _fields())

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["sections"][0]["reviewed"] is True
    assert saved["sections"][0]["lines"][1]["reviewed"] is True
    assert saved["sections"][0]["lines"][1]["start"] == 1.0
    assert result["summary"]["review_complete"] is True
    assert not list(path.parent.glob(".lyrics.aligned.yaml.*.tmp"))


def test_invalid_overlap_leaves_versioned_timing_unchanged(tmp_path: Path):
    release = _release()
    path = _write_timing(tmp_path, release)
    before = path.read_text(encoding="utf-8")

    with pytest.raises(TimingEditorError, match="non-overlapping"):
        save_timing(tmp_path, release, release["tracks"][0], _fields(overlap=True))

    assert path.read_text(encoding="utf-8") == before


def test_timing_route_marks_only_selected_track_timed(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    release = _release()
    release["tracks"][0]["music_video"]["status"] = "draft"
    untouched = copy.deepcopy(release["tracks"][1])
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"release": release}, sort_keys=False), encoding="utf-8")
    _write_timing(tmp_path, release)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_timing_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                _form_fields(_fields()),
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]
    assert saved["tracks"][0]["music_video"]["status"] == "timed"
    assert saved["tracks"][1] == untouched


def test_timing_page_renders_scrubbing_boundaries_and_no_structure_cues(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    release = _release()
    master = tmp_path / "private" / "master.wav"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"audio")
    release["tracks"][0]["master_path"] = str(master)
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"release": release}, sort_keys=False), encoding="utf-8")
    _write_timing(tmp_path, release)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_timing(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                [],
                method="GET",
            ),
            "video-contract",
            "private-track",
        )
    )
    body = response.body.decode()

    assert response.status_code == 200
    assert "Audio playhead" in body
    assert "Use playhead" in body
    assert "Needs attention" in body
    assert "52.0%" in body
    assert "[Verse]" not in body


def test_video_audio_serves_the_selected_track_master(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    release = _release()
    master = tmp_path / "private" / "master.wav"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"audio")
    release["tracks"][0]["master_path"] = str(master)
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"release": release}, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(video_routes.video_audio("video-contract", "private-track"))

    assert Path(response.path) == master
    assert response.media_type == "audio/wav"
