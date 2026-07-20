from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest
import yaml
from starlette.requests import Request

from mrp.admin import db, video_jobs, video_workspace
from mrp.admin.routes import video as video_routes
from mrp.admin.routes import workspace as workspace_routes
from mrp.admin.workspace import STAGES
from mrp.core.migrate_site import load_structured_record
from mrp.video.worker import EventWriter, ProgressMapper

ROOT = Path(__file__).resolve().parents[3]
ENRICHED = ROOT / "tests" / "video" / "fixtures" / "releases" / "enriched-album.yaml"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _request(path: str, fields: list[tuple[str, str]]) -> Request:
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
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        },
        receive,
    )


def _get_request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        }
    )


def _create_job(
    tmp_path: Path,
    *,
    job_id: str = "job-1",
    kind: str = "analyze",
    track_key: str = "artist--track",
) -> None:
    db.create_video_job(
        job_id=job_id,
        command=f"video/release/track/{kind}",
        repo_root=str(tmp_path),
        release_slug="release",
        track_slug="track",
        track_key=track_key,
        kind=kind,
        created_at=_now(),
        log_path=f"assets/processed/video/{track_key}/logs/jobs/{job_id}.log",
        events_path=f"assets/processed/video/{track_key}/logs/jobs/{job_id}.events.jsonl",
    )


def test_video_stage_is_optional_and_immediately_follows_tracks(tmp_path: Path):
    stage_ids = [stage_id for stage_id, _label in STAGES]
    assert stage_ids.index("video") == stage_ids.index("tracks") + 1

    release = {
        "artist_id": "artist",
        "model": "song",
        "song": {"slug": "track", "title": "Track"},
    }
    assert video_workspace.video_stage_status(tmp_path, "release", release) == {
        "state": "todo",
        "detail": "optional",
    }


def test_video_track_matrix_reads_track_scoped_artifacts(tmp_path: Path):
    db.init(tmp_path / "admin.db")
    release_path = tmp_path / "content" / "releases" / "release.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text("release: {}\n", encoding="utf-8")
    master = tmp_path / "private" / "master.wav"
    cover = tmp_path / "private" / "cover.jpg"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master")
    cover.write_bytes(b"cover")
    release = {
        "artist_id": "artist",
        "cover_image": str(cover),
        "model": "song",
        "song": {
            "slug": "track",
            "title": "Track",
            "master_path": str(master),
            "lyrics_text": "One line",
            "music_video": {
                "project": "assets/source/video/artist--track/project.yaml",
                "status": "draft",
            },
        },
    }
    source = tmp_path / "assets" / "source" / "video" / "artist--track"
    logs = tmp_path / "assets" / "processed" / "video" / "artist--track" / "logs"
    source.mkdir(parents=True)
    logs.mkdir(parents=True)
    (source / "project.yaml").write_text("version: 1\n", encoding="utf-8")
    (source / "lyrics.aligned.yaml").write_text("version: 1\n", encoding="utf-8")
    (logs / "preflight.json").write_text(
        json.dumps({"status": "passed", "input_fingerprint": "fingerprint"}),
        encoding="utf-8",
    )
    (logs / "artifacts.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {"kind": "render", "input_fingerprint": "fingerprint"}
                ]
            }
        ),
        encoding="utf-8",
    )

    row = video_workspace.video_track_rows(tmp_path, "release", release)[0]

    assert row["master"] is True
    assert row["stems"] is True
    assert row["enabled_stem_count"] == 0
    assert row["timing"] is True
    assert row["render"] is True
    assert row["validation"] == "passed"


def test_asset_validation_accepts_master_only_track(tmp_path: Path, monkeypatch):
    master = tmp_path / "master.wav"
    cover = tmp_path / "cover.jpg"
    font = tmp_path / "font.ttf"
    master.write_bytes(b"audio")
    cover.write_bytes(b"image")
    font.write_bytes(b"font")
    release = {
        "artist_id": "artist",
        "cover_image": str(cover),
        "model": "song",
        "song": {
            "slug": "track",
            "title": "Track",
            "master_path": str(master),
            "lyrics_text": "Line",
        },
    }
    monkeypatch.setattr(video_workspace.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(video_workspace, "_default_font", lambda: font)
    monkeypatch.setattr(video_workspace, "_audio_duration", lambda _path: 10.0)
    monkeypatch.setattr(
        video_workspace,
        "_probe",
        lambda *_args, **_kwargs: {"streams": [{"width": 1200, "height": 1200}]},
    )

    report = video_workspace.validate_assets(
        tmp_path,
        release,
        {"index": 0, "track": release["song"]},
    )

    assert report["status"] == "passed"
    assert next(check for check in report["checks"] if check["name"] == "Stems")["detail"] == "0 enabled"


def test_asset_save_updates_only_selected_track(tmp_path: Path, monkeypatch):
    record = yaml.safe_load(ENRICHED.read_text(encoding="utf-8"))
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    untouched = record["release"]["tracks"][1].copy()
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_assets_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/assets",
                [
                    ("master_path", "/private/new-master.wav"),
                    ("stem_id", "vocal-a"),
                    ("stem_label", "Vocal A"),
                    ("stem_role", "vocals"),
                    ("stem_path", "/private/vocal-a.wav"),
                    ("stem_enabled", "true"),
                    ("stem_id", "vocal-b"),
                    ("stem_label", "Vocal B"),
                    ("stem_role", "vocals"),
                    ("stem_path", "/private/vocal-b.wav"),
                    ("stem_enabled", "false"),
                ],
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]
    assert saved["tracks"][0]["master_path"] == "/private/new-master.wav"
    assert [stem["id"] for stem in saved["tracks"][0]["stems"]] == ["vocal-a", "vocal-b"]
    assert saved["tracks"][0]["stems"][1]["enabled"] is False
    assert saved["tracks"][1] == untouched


def test_video_track_page_renders_assets_and_job_controls(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    record = yaml.safe_load(ENRICHED.read_text(encoding="utf-8"))
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        video_routes,
        "validate_assets",
        lambda *_args: {
            "status": "failed",
            "checks": [{"name": "Master", "ok": False, "detail": "missing"}],
            "errors": ["Master: missing"],
        },
    )

    response = asyncio.run(
        video_routes.video_track(
            _get_request("/releases/video-contract/tracks/private-track/video"),
            "video-contract",
            "private-track",
        )
    )
    body = response.body.decode()

    assert response.status_code == 200
    assert "Import assets by local path" in body
    assert "Run prepare" in body
    assert "Run analyze" in body
    assert "Run align" in body
    assert "Run render" in body


def test_workspace_dispatch_renders_optional_video_matrix(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    record = yaml.safe_load(ENRICHED.read_text(encoding="utf-8"))
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(workspace_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        workspace_routes.stage_page(
            _get_request("/releases/video-contract/video"),
            "video-contract",
            "video",
        )
    )
    body = response.body.decode()

    assert response.status_code == 200
    assert "Music videos" in body
    assert "/releases/video-contract/tracks/private-track/video" in body
    assert "A release can publish without a video" in body


def test_video_job_events_persist_progress_and_result(tmp_path: Path):
    db.init(tmp_path / "admin.db")
    _create_job(tmp_path)

    video_jobs._apply_event(
        "job-1",
        {
            "event": "started",
            "timestamp": _now(),
            "progress": 5,
            "phase": "preflight",
            "message": "Validating",
        },
    )
    video_jobs._apply_event(
        "job-1",
        {
            "event": "result",
            "timestamp": _now(),
            "result": {"status": "passed"},
            "artifact_path": "assets/processed/video/artist--track/analysis/cache.npz",
        },
    )

    job = db.get_video_job("job-1")
    assert job is not None
    assert job["status"] == "done"
    assert job["progress"] == 100
    assert json.loads(job["output"])["status"] == "passed"
    assert job["artifact_path"].endswith("cache.npz")


def test_launch_uses_worker_process_and_blocks_second_render(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    launches: list[tuple[list[str], dict]] = []

    class FakeProcess:
        pid = 43210

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        launches.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(video_jobs.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(video_jobs, "_start_monitor", lambda *_args: None)

    job_id = video_jobs.launch(tmp_path, "release", "track", "artist--track", "render")

    assert db.get_video_job(job_id)["pid"] == 43210
    command, kwargs = launches[0]
    assert command[1:3] == ["-m", "mrp.video.worker"]
    assert "--job-id" in command
    assert kwargs["start_new_session"] is True
    align_job_id = video_jobs.launch(
        tmp_path, "release", "track", "artist--track", "align"
    )
    assert db.get_video_job(align_job_id)["kind"] == "align"
    assert launches[1][0][3] == "align"
    with pytest.raises(video_jobs.VideoJobConflict, match="active full render"):
        video_jobs.launch(tmp_path, "release", "track", "artist--track", "render")


def test_cancellation_and_restart_recovery_reach_terminal_states(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    _create_job(tmp_path, job_id="pending")
    cancelled = video_jobs.request_cancel("pending")
    assert cancelled["status"] == "cancelled"

    _create_job(tmp_path, job_id="lost", kind="render", track_key="artist--lost")
    db.update_video_job("lost", status="running", pid=999999)
    monkeypatch.setattr(video_jobs, "_process_matches", lambda _pid, _job_id: False)

    assert video_jobs.recover() == []
    assert db.get_video_job("lost")["status"] == "interrupted"


def test_active_cancellation_signals_the_worker_process_group(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    _create_job(tmp_path, job_id="active")
    db.update_video_job("active", status="running", pid=32123)
    signals: list[tuple[int, int]] = []

    class FakeProcess:
        pid = 32123

        def poll(self):
            return None

    with video_jobs._LOCK:
        video_jobs._PROCESSES["active"] = FakeProcess()
    monkeypatch.setattr(video_jobs.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    try:
        job = video_jobs.request_cancel("active")
    finally:
        with video_jobs._LOCK:
            video_jobs._PROCESSES.pop("active", None)

    assert job["cancel_requested_at"]
    assert signals == [(32123, video_jobs.signal.SIGTERM)]


def test_worker_progress_events_are_structured(tmp_path: Path):
    events = tmp_path / "events.jsonl"
    writer = EventWriter(events)
    mapper = ProgressMapper("render", writer, __import__("threading").Event())

    mapper("Streaming deterministic RGB frames to FFmpeg")
    mapper("Encoded frame 50 of 100 (50.0%, 10 fps, ETA 5s)")

    payloads = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    assert payloads[-1]["event"] == "progress"
    assert payloads[-1]["phase"] == "rendering"
    assert payloads[-1]["progress"] == 55.0
