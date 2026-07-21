from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from mrp.admin import db
from mrp.admin.routes import video as video_routes
from mrp.admin.video_rendering import (
    VideoRenderingError,
    approve_render,
    discard_draft,
    load_rendering,
)
from mrp.core.migrate_site import load_structured_record
from tests.video.admin.test_video_casting import _get_request, _request


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_render_repo(tmp_path: Path) -> tuple[dict, dict, Path]:
    master = tmp_path / "private" / "master.wav"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"current master")
    release = {
        "id": "render-release",
        "slug": "render-release",
        "title": "Render Release",
        "artist_id": "artist",
        "model": "album",
        "release_type": "album",
        "status": "draft",
        "release_date": "2026-07-20",
        "cover_image": "assets/cover.jpg",
        "seo": {"title": "Render", "description": "Render"},
        "tracks": [
            {
                "number": 1,
                "title": "Rendered Track",
                "slug": "rendered-track",
                "explicit": False,
                "instrumental": False,
                "master_path": str(master),
                "lyrics_text": "Rendered line",
                "music_video": {
                    "project": "assets/source/video/artist--rendered-track/project.yaml",
                    "status": "rendered",
                },
            },
            {
                "number": 2,
                "title": "Untouched Track",
                "slug": "untouched-track",
                "explicit": False,
                "instrumental": True,
            },
        ],
    }
    release_path = tmp_path / "content" / "releases" / "render-release.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        yaml.safe_dump({"release": release}, sort_keys=False),
        encoding="utf-8",
    )
    track = release["tracks"][0]
    source = tmp_path / "assets" / "source" / "video" / "artist--rendered-track"
    source.mkdir(parents=True)
    project = source / "project.yaml"
    project.write_bytes(b"version: 1\nproject: current\n")
    aligned = source / "lyrics.aligned.yaml"
    aligned.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "source": "lyrics.yaml",
                "sections": [
                    {
                        "id": "verse_1",
                        "type": "verse",
                        "label": "Verse",
                        "start": 0,
                        "end": 4,
                        "lines": [{"text": "Rendered line", "start": 0, "end": 4}],
                    },
                    {
                        "id": "chorus_1",
                        "type": "chorus",
                        "label": "Chorus",
                        "start": 4,
                        "end": 8,
                        "lines": [{"text": "Chorus", "start": 4, "end": 8}],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    processed = (
        tmp_path / "assets" / "processed" / "video" / "artist--rendered-track"
    )
    logs = processed / "logs"
    drafts = processed / "renders" / "drafts"
    full = processed / "renders" / "full"
    logs.mkdir(parents=True)
    drafts.mkdir(parents=True)
    full.mkdir(parents=True)
    draft_output = drafts / "draft-1.mp4"
    full_output = full / "full-1.mp4"
    draft_output.write_bytes(b"verified draft bytes")
    full_output.write_bytes(b"verified full bytes")
    (drafts / "draft-1.render.json").write_text(
        json.dumps(
            {
                "timeline": {"draft": True, "source_start": 1, "source_end": 3},
                "output": {"sha256": _hash(draft_output.read_bytes())},
                "verification": {"valid": True},
            }
        ),
        encoding="utf-8",
    )
    (full / "full-1.render.json").write_text(
        json.dumps(
            {
                "timeline": {"draft": False, "source_start": 0, "source_end": 8},
                "output": {"sha256": _hash(full_output.read_bytes())},
                "verification": {"valid": True},
            }
        ),
        encoding="utf-8",
    )
    preflight = {
        "version": 1,
        "status": "passed",
        "track_key": "artist--rendered-track",
        "project_hash": _hash(project.read_bytes()),
        "input_fingerprint": "current-fingerprint",
        "input_hashes": {
            "audio.master": _hash(master.read_bytes()),
            "lyrics.aligned": _hash(aligned.read_bytes()),
        },
        "master_duration": 8,
    }
    (logs / "preflight.json").write_text(json.dumps(preflight), encoding="utf-8")
    artifacts = {
        "version": 1,
        "artifacts": [
            {
                "kind": "draft",
                "path": "assets/processed/video/artist--rendered-track/renders/drafts/draft-1.mp4",
                "input_fingerprint": "current-fingerprint",
                "recorded_at": "2026-07-20T12:00:00Z",
                "details": {
                    "render_id": "draft-1",
                    "draft": True,
                    "verified": True,
                    "frame_count": 20,
                    "width": 960,
                    "height": 540,
                    "fps": 10,
                    "duration": 2,
                },
            },
            {
                "kind": "render",
                "path": "assets/processed/video/artist--rendered-track/renders/full/full-1.mp4",
                "input_fingerprint": "current-fingerprint",
                "recorded_at": "2026-07-20T13:00:00Z",
                "details": {
                    "render_id": "full-1",
                    "draft": False,
                    "verified": True,
                    "frame_count": 300,
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                    "duration": 10,
                    "video_codec": "h264",
                    "audio_codec": "aac",
                },
            },
        ],
    }
    (logs / "artifacts.json").write_text(json.dumps(artifacts), encoding="utf-8")
    return release, track, release_path


def _plan_job(tmp_path: Path) -> dict:
    db.init(tmp_path / "admin.db")
    db.create_video_job(
        job_id="plan-1",
        command="video/render-release/rendered-track/render_plan",
        repo_root=str(tmp_path),
        release_slug="render-release",
        track_slug="rendered-track",
        track_key="artist--rendered-track",
        kind="render_plan",
        created_at=datetime.now(UTC).isoformat(),
        log_path="assets/processed/video/artist--rendered-track/logs/jobs/plan.log",
        events_path="assets/processed/video/artist--rendered-track/logs/jobs/plan.events",
    )
    db.update_video_job(
        "plan-1",
        status="done",
        output=json.dumps(
            {
                "preflight": {"input_fingerprint": "current-fingerprint"},
                "render_plan": {
                    "frame_count": 300,
                    "duration": 10,
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                    "cards_included": True,
                    "diagnostics": {"raw_stream_gib": 1.74},
                },
            }
        ),
    )
    return db.get_video_job("plan-1")


def test_rendering_history_and_plan_are_fingerprint_scoped(tmp_path: Path) -> None:
    release, track, _release_path = _write_render_repo(tmp_path)
    plan = _plan_job(tmp_path)

    state = load_rendering(tmp_path, release, track, plan_job=plan)

    assert state["preflight_current"] is True
    assert state["plan"]["current"] is True
    assert state["sections"][1]["id"] == "chorus_1"
    assert state["drafts"][0]["current"] is True
    assert state["drafts"][0]["source_start"] == 1
    assert state["renders"][0]["verified"] is True
    assert state["renders"][0]["output_sha256"] == _hash(b"verified full bytes")

    project = tmp_path / "assets/source/video/artist--rendered-track/project.yaml"
    project.write_text("changed: true\n", encoding="utf-8")
    stale = load_rendering(tmp_path, release, track, plan_job=plan)
    assert stale["plan"]["current"] is False
    assert stale["drafts"][0]["stale"] is True
    assert stale["renders"][0]["stale"] is True


def test_approval_rejects_stale_or_tampered_render(tmp_path: Path) -> None:
    release, track, _release_path = _write_render_repo(tmp_path)
    artifact = (
        "assets/processed/video/artist--rendered-track/renders/full/full-1.mp4"
    )

    approved = approve_render(tmp_path, release, track, artifact)

    assert approved["status"] == "approved"
    assert approved["output_sha256"] == _hash(b"verified full bytes")
    assert approved["project_hash"] == _hash(b"version: 1\nproject: current\n")
    assert approved["input_hashes"]["audio.master"] == _hash(b"current master")

    full = (
        tmp_path
        / "assets/processed/video/artist--rendered-track/renders/full/full-1.mp4"
    )
    full.write_bytes(b"tampered")
    with pytest.raises(VideoRenderingError, match="hash does not match"):
        approve_render(tmp_path, release, track, artifact)
    full.write_bytes(b"verified full bytes")

    project = (
        tmp_path / "assets/source/video/artist--rendered-track/project.yaml"
    )
    project.write_text("changed: true\n", encoding="utf-8")
    state = load_rendering(tmp_path, release, track)
    assert state["preflight_current"] is False
    assert state["renders"][0]["stale"] is True
    with pytest.raises(VideoRenderingError, match="project changed"):
        approve_render(tmp_path, release, track, artifact)


def test_discard_removes_only_selected_generated_draft(tmp_path: Path) -> None:
    release, track, _release_path = _write_render_repo(tmp_path)
    full = (
        tmp_path
        / "assets/processed/video/artist--rendered-track/renders/full/full-1.mp4"
    )

    result = discard_draft(tmp_path, release, track, "draft-1")

    assert result == {"draft_id": "draft-1", "discarded": True}
    assert not (
        tmp_path
        / "assets/processed/video/artist--rendered-track/renders/drafts/draft-1.mp4"
    ).exists()
    assert full.is_file()
    index = json.loads(
        (
            tmp_path
            / "assets/processed/video/artist--rendered-track/logs/artifacts.json"
        ).read_text()
    )
    assert [item["kind"] for item in index["artifacts"]] == ["render"]


def test_rendering_page_and_approval_update_only_selected_track(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release, _track, release_path = _write_render_repo(tmp_path)
    _plan_job(tmp_path)
    untouched = release["tracks"][1].copy()
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    page = asyncio.run(
        video_routes.video_rendering(
            _get_request(
                "/releases/render-release/tracks/rendered-track/video/rendering"
            ),
            "render-release",
            "rendered-track",
        )
    )
    body = page.body.decode()
    assert page.status_code == 200
    assert "Draft iteration history" in body
    assert "Full-render preflight" in body
    assert "Approve verified full render" in body
    assert "current-fingerprint" in body

    launched: dict[str, object] = {}

    def fake_launch(*args, **kwargs):
        launched["args"] = args
        launched["kwargs"] = kwargs
        return "render-job"

    monkeypatch.setattr(video_routes.video_jobs, "launch", fake_launch)
    launch_response = asyncio.run(
        video_routes.video_job_launch(
            _request(
                "/releases/render-release/tracks/rendered-track/video/jobs/render",
                [],
            ),
            "render-release",
            "rendered-track",
            "render",
        )
    )
    assert launch_response.status_code == 200
    assert launched["kwargs"]["expected_fingerprint"] == "current-fingerprint"

    response = asyncio.run(
        video_routes.video_render_approve(
            _request(
                "/releases/render-release/tracks/rendered-track/video/rendering/approve",
                [
                    (
                        "artifact_path",
                        "assets/processed/video/artist--rendered-track/renders/full/full-1.mp4",
                    )
                ],
            ),
            "render-release",
            "rendered-track",
        )
    )
    saved = load_structured_record(release_path)["release"]
    assert response.status_code == 200
    assert saved["tracks"][0]["music_video"]["status"] == "approved"
    assert saved["tracks"][1] == untouched

    video = asyncio.run(
        video_routes.video_render_file(
            "render-release",
            "rendered-track",
            "full",
            "full-1.mp4",
        )
    )
    rejected = asyncio.run(
        video_routes.video_render_file(
            "render-release",
            "rendered-track",
            "full",
            "../project.yaml",
        )
    )
    assert video.status_code == 200
    assert video.media_type == "video/mp4"
    assert rejected.status_code == 404
