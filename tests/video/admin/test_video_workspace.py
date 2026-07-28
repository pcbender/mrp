from __future__ import annotations

import asyncio
import hashlib
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    # Preparation always records a hash per consumed input, and staleness is
    # decided by re-hashing them rather than by comparing file timestamps.
    (logs / "preflight.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "input_fingerprint": "fingerprint",
                "input_hashes": {
                    "audio.master": _sha256(master),
                    "lyrics.aligned": _sha256(source / "lyrics.aligned.yaml"),
                },
            }
        ),
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
    monkeypatch.setattr(
        video_jobs,
        "renderer_environment",
        lambda _root: (True, "/repo/.venv/bin/python"),
    )
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
    assert next(
        check for check in report["checks"] if check["name"] == "Renderer Python"
    )["ok"] is True
    assert next(check for check in report["checks"] if check["name"] == "Stems")["detail"] == "0 enabled"


def test_scan_stem_directory_infers_editable_rows(tmp_path: Path):
    directory = tmp_path / "Track Stems"
    directory.mkdir()
    for name in (
        "Bass.wav",
        "Drums.WAV",
        "Guitar L.aiff",
        "Lead Vocals.flac",
        "Room Tone.m4a",
    ):
        (directory / name).write_bytes(b"audio")
    (directory / "notes.txt").write_text("not audio", encoding="utf-8")
    nested = directory / "nested"
    nested.mkdir()
    (nested / "Piano.wav").write_bytes(b"nested")

    stems = video_workspace.scan_stem_directory(tmp_path, directory)

    assert [stem["id"] for stem in stems] == [
        "bass",
        "drums",
        "guitar-l",
        "lead-vocals",
        "room-tone",
    ]
    assert [stem["role"] for stem in stems] == [
        "bass",
        "drums",
        "instruments",
        "vocals",
        "other",
    ]
    assert all(stem["enabled"] is True for stem in stems)
    assert all(Path(str(stem["path"])).parent == directory for stem in stems)


def test_scan_stem_directory_rejects_missing_or_empty_path(tmp_path: Path):
    with pytest.raises(video_workspace.StemImportError, match="Enter a directory"):
        video_workspace.scan_stem_directory(tmp_path, "")

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(video_workspace.StemImportError, match="No supported audio"):
        video_workspace.scan_stem_directory(tmp_path, empty)


def test_stem_import_route_scans_without_saving_release(tmp_path: Path, monkeypatch):
    record = yaml.safe_load(ENRICHED.read_text(encoding="utf-8"))
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    original = path.read_text(encoding="utf-8")
    stems = tmp_path / "stems"
    stems.mkdir()
    (stems / "Bass.wav").write_bytes(b"bass")
    (stems / "Vocals.wav").write_bytes(b"vocals")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_stems_import(
            _request(
                "/releases/video-contract/tracks/private-track/video/stems/import",
                [("stem_directory", str(stems))],
            ),
            "video-contract",
            "private-track",
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["count"] == 2
    assert [stem["role"] for stem in payload["stems"]] == ["bass", "vocals"]
    assert path.read_text(encoding="utf-8") == original


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
    assert "Import from path&hellip;" in body
    assert "Run prepare" in body
    assert "Run analyze" in body
    assert "Run align" in body
    assert "Open rendering workspace" in body


def test_video_track_page_makes_legacy_master_an_explicit_import(
    tmp_path: Path, monkeypatch
):
    db.init(tmp_path / "admin.db")
    legacy_master = tmp_path / "legacy master.wav"
    legacy_master.write_bytes(b"audio")
    record = {
        "release": {
            "slug": "single",
            "artist_id": "artist",
            "model": "song",
            "automation": {"master_path": str(legacy_master)},
            "song": {"slug": "track", "title": "Track", "master_path": None},
        }
    }
    path = tmp_path / "content" / "releases" / "single.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_track(
            _get_request("/releases/single/tracks/track/video"),
            "single",
            "track",
        )
    )
    body = response.body.decode()

    assert response.status_code == 200
    assert 'id="video-master-path" type="text" name="master_path" value=""' in body
    assert 'placeholder="/path/to/master.wav"' in body
    assert f'data-master-path="{legacy_master}"' in body
    assert "Import legacy master" in body


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
    video_python = tmp_path / ".venv" / "bin" / "python"
    video_python.parent.mkdir(parents=True)
    video_python.write_text("", encoding="utf-8")

    class FakeProcess:
        pid = 43210

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        launches.append((command, kwargs))
        return FakeProcess()

    monkeypatch.setattr(video_jobs.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(video_jobs, "_start_monitor", lambda *_args: None)
    monkeypatch.setattr(
        video_jobs,
        "renderer_environment",
        lambda _root: (True, str(video_python)),
    )

    job_id = video_jobs.launch(
        tmp_path,
        "release",
        "track",
        "artist--track",
        "render",
        expected_fingerprint="fingerprint",
    )

    assert db.get_video_job(job_id)["pid"] == 43210
    command, kwargs = launches[0]
    assert command[0] == str(video_python.absolute())
    assert command[1:3] == ["-m", "mrp.video.worker"]
    assert "--job-id" in command
    assert command[-2:] == ["--expected-fingerprint", "fingerprint"]
    assert kwargs["start_new_session"] is True
    align_job_id = video_jobs.launch(
        tmp_path, "release", "track", "artist--track", "align"
    )
    assert db.get_video_job(align_job_id)["kind"] == "align"
    assert launches[1][0][3] == "align"
    frame_job_id = video_jobs.launch(
        tmp_path,
        "release",
        "track",
        "artist--track",
        "frame",
        time_seconds=12.345,
    )
    assert db.get_video_job(frame_job_id)["command"].endswith("frame@12.345000")
    assert launches[2][0][-2:] == ["--time", "12.345000"]
    contact_job_id = video_jobs.launch(
        tmp_path, "release", "track", "artist--track", "contact"
    )
    assert db.get_video_job(contact_job_id)["kind"] == "contact"
    assert launches[3][0][3] == "contact"
    draft_job_id = video_jobs.launch(
        tmp_path,
        "release",
        "track",
        "artist--track",
        "draft",
        start_seconds=2.5,
        end_seconds=7.75,
    )
    assert db.get_video_job(draft_job_id)["command"].endswith(
        "draft@2.500000:7.750000"
    )
    assert launches[4][0][-4:] == ["--from", "2.500000", "--to", "7.750000"]
    plan_job_id = video_jobs.launch(
        tmp_path, "release", "track", "artist--track", "render_plan"
    )
    assert db.get_video_job(plan_job_id)["kind"] == "render_plan"
    assert launches[5][0][3] == "render_plan"
    with pytest.raises(video_jobs.VideoJobError, match="require.*time"):
        video_jobs.launch(tmp_path, "release", "track", "artist--track", "frame")
    with pytest.raises(video_jobs.VideoJobError, match="require.*range"):
        video_jobs.launch(tmp_path, "release", "track", "artist--track", "draft")
    with pytest.raises(video_jobs.VideoJobConflict, match="active full render"):
        video_jobs.launch(
            tmp_path,
            "release",
            "track",
            "artist--track",
            "render",
            expected_fingerprint="fingerprint",
        )


def test_launch_refuses_before_spawning_when_renderer_python_is_incomplete(
    tmp_path: Path, monkeypatch
):
    """A missing renderer dependency must fail submission, not the child process.

    Falling through to an interpreter without the video stack used to create a
    job row and spawn a worker that died mid-render with a bare
    "No module named 'librosa'".
    """
    db.init(tmp_path / "admin.db")
    monkeypatch.setattr(
        video_jobs,
        "renderer_environment",
        lambda _root: (
            False,
            "missing librosa; install requirements-video.txt into /usr/bin/python3",
        ),
    )

    def fail_popen(*_args, **_kwargs):
        raise AssertionError("launch must not spawn a worker without the renderer")

    monkeypatch.setattr(video_jobs.subprocess, "Popen", fail_popen)

    with pytest.raises(video_jobs.VideoJobError, match="renderer environment is not ready"):
        video_jobs.launch(tmp_path, "release", "track", "artist--track", "analyze")

    assert db.list_video_jobs() == []


def test_renderer_environment_reports_invalid_explicit_python(
    tmp_path: Path, monkeypatch
):
    missing = tmp_path / "missing-video-python"
    monkeypatch.setenv("MRP_VIDEO_PYTHON", str(missing))

    ready, detail = video_jobs.renderer_environment(tmp_path)

    assert ready is False
    assert detail == f"not found: {missing}"


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


def _drift_fixture(tmp_path: Path) -> tuple[dict, dict, dict]:
    master = tmp_path / "private" / "master.wav"
    stem = tmp_path / "private" / "vocals.wav"
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_bytes(b"master")
    stem.write_bytes(b"vocals")
    release = {"artist_id": "artist", "model": "song", "song": {"slug": "track"}}
    track = {
        "slug": "track",
        "master_path": str(master),
        "stems": [{"id": "vocals", "path": str(stem), "enabled": True}],
    }
    source = tmp_path / "assets" / "source" / "video" / "artist--track"
    source.mkdir(parents=True, exist_ok=True)
    aligned = source / "lyrics.aligned.yaml"
    aligned.write_text("version: 1\n", encoding="utf-8")
    preflight = {
        "status": "passed",
        "input_hashes": {
            "audio.master": _sha256(master),
            "audio.stem.vocals": _sha256(stem),
            "lyrics.aligned": _sha256(aligned),
        },
    }
    return release, track, preflight


def test_timing_edits_do_not_invalidate_cached_audio_analysis(tmp_path: Path):
    """Re-cutting scenes must not force a re-analyse.

    Analysis keys its cache on the master and stems alone and its features are
    time-indexed, so section boundaries cannot change it. Checking every
    preflight input uniformly sent the Live Preview back to geometry-only after
    every timing save.
    """
    release, track, preflight = _drift_fixture(tmp_path)
    aligned = tmp_path / "assets" / "source" / "video" / "artist--track" / "lyrics.aligned.yaml"

    assert video_workspace.preflight_input_drift(tmp_path, release, track, preflight) is None

    aligned.write_text("version: 1\nsections: []\n", encoding="utf-8")

    # Rendering depends on aligned timing and must still notice.
    assert video_workspace.preflight_input_drift(
        tmp_path, release, track, preflight
    ) == "aligned timing changed after preparation"
    # The cached audio analysis does not, so the preview stays audio-reactive.
    assert (
        video_workspace.preflight_input_drift(
            tmp_path, release, track, preflight, audio_only=True
        )
        is None
    )


def test_audio_scoped_drift_still_catches_audio_changes(tmp_path: Path):
    """Narrowing the question must not stop it detecting a real audio change."""
    release, track, preflight = _drift_fixture(tmp_path)
    stem = Path(track["stems"][0]["path"])

    stem.write_bytes(b"vocals-remixed")
    assert (
        video_workspace.preflight_input_drift(
            tmp_path, release, track, preflight, audio_only=True
        )
        == "stem vocals changed after preparation"
    )

    stem.write_bytes(b"vocals")
    track["stems"][0]["enabled"] = False
    assert (
        video_workspace.preflight_input_drift(
            tmp_path, release, track, preflight, audio_only=True
        )
        == "stem vocals was removed or disabled after preparation"
    )
