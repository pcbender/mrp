"""Workspace steps fail fast and loud.

A promoter or critic subprocess that exits non-zero used to come back as a
"done" job with ``ok: false`` buried in its payload — the badge stayed green
and the reason (the Gemini error) was never rendered. Now the pipeline raises
StepFailure: the job lands in the ``error`` state, the badge is red, and the
last line of the process output is the message on it.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from mrp.admin import db, jobs, pipeline
from mrp.admin.routes import workspace as workspace_routes

_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "generate.py", line 20, in _call_gemini\n'
    "google.genai.errors.ClientError: 404 NOT_FOUND. model no longer available\n"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    releases = tmp_path / "content" / "releases"
    releases.mkdir(parents=True)
    (releases / "a-single.yaml").write_text(
        yaml.dump({"release": {"slug": "a-single", "artist_id": "stab", "title": "A Single"}}),
        encoding="utf-8",
    )
    (releases / "an-album.yaml").write_text(
        yaml.dump({"release": {
            "slug": "an-album", "artist_id": "stab", "title": "An Album", "model": "album",
            "tracks": [
                {"slug": "one", "title": "One", "master_path": "/m/one.wav"},
                {"slug": "two", "title": "Two", "master_path": "/m/two.wav"},
                {"slug": "three", "title": "Three", "master_path": "/m/three.wav"},
            ],
        }}),
        encoding="utf-8",
    )
    return tmp_path


def _fail_when(monkeypatch, predicate):
    """Fake subprocess.run: exit 1 with a traceback when predicate(cmd) holds."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if predicate(cmd):
            return subprocess.CompletedProcess(cmd, 1, stdout="  calling gemini…\n", stderr=_TRACEBACK)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    return calls


def test_promoter_failure_raises_with_the_exception_line(repo, monkeypatch):
    _fail_when(monkeypatch, lambda cmd: True)
    with pytest.raises(pipeline.StepFailure) as info:
        pipeline.run_promoter(repo, "a-single", mode="blurb", model="default")
    assert str(info.value) == (
        "promoter blurb: google.genai.errors.ClientError: 404 NOT_FOUND. model no longer available"
    )
    out = info.value.job_output()
    assert out["ok"] is False and out["mode"] == "blurb" and out["artist_id"] == "stab"
    assert "Traceback" in out["stderr"]


def test_critic_stops_at_the_first_failing_track(repo, monkeypatch):
    calls = _fail_when(monkeypatch, lambda cmd: "--track-slug" in cmd and cmd[cmd.index("--track-slug") + 1] == "two")
    with pytest.raises(pipeline.StepFailure) as info:
        pipeline.run_critic(repo, "an-album")
    assert str(info.value).startswith("critic two: google.genai.errors.ClientError")
    # Track three was never attempted; track one's success is kept in the record.
    assert [c[c.index("--track-slug") + 1] for c in calls] == ["one", "two"]
    assert info.value.job_output()["tracks"] == [{"track_slug": "one", "ok": True}]


def test_album_critic_failure_raises(repo, monkeypatch):
    _fail_when(monkeypatch, lambda cmd: True)
    with pytest.raises(pipeline.StepFailure, match=r"^critic album: google\.genai"):
        pipeline.run_critic_album(repo, "an-album")


def test_job_runner_stores_the_failure_as_an_error_job(tmp_path, monkeypatch):
    db.init(tmp_path / "admin.db")

    def step():
        raise pipeline.StepFailure("promoter blurb: boom", stderr="trace", mode="blurb")

    db.create_job("j1", "a-single/promoter-blurb")
    jobs._run("j1", step, (), {})
    job = db.get_job("j1")
    assert job["status"] == "error"
    assert json.loads(job["output"]) == {
        "ok": False, "message": "promoter blurb: boom", "stdout": "", "stderr": "trace", "mode": "blurb",
    }


def _render_badge(job: dict) -> str:
    template = workspace_routes._templates.env.get_template("releases/workspace/_ws_job.html")
    return template.render(job=job, slug="a-single", step="promoter-blurb", dom_id="ws-promoter-blurb")


def test_failed_badge_shows_the_step_message():
    output = json.dumps({"ok": False, "message": "promoter blurb: 404 NOT_FOUND", "stderr": "Traceback…"})
    html = _render_badge({"id": "j1", "status": "error", "output": output, "completed_at": None})
    assert "badge-failed" in html
    assert "promoter blurb: 404 NOT_FOUND" in html
    assert 'title="Traceback…"' in html


def test_done_badge_goes_red_when_a_track_did_not_run():
    output = json.dumps({"ok_count": 1, "tracks": [
        {"track_slug": "one", "ok": True},
        {"track_slug": "two", "ok": False, "error": "no master_path — set it in the track editor"},
    ]})
    html = _render_badge({"id": "j2", "status": "done", "output": output, "completed_at": "2026-09-18T15:00:00"})
    assert "1/2 ok" in html and "var(--danger)" in html
    assert "two: no master_path" in html
