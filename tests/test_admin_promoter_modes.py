"""The admin's promoter invocation.

Each mode takes different flags — keywords has no --model because the
triumvirate's seats are fixed — and getting that wrong fails only at runtime,
inside a subprocess whose stderr lands in a job record. These assert the
command line without running the promoter.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from mrp.admin import pipeline


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    releases = tmp_path / "content" / "releases"
    releases.mkdir(parents=True)
    (releases / "a-single.yaml").write_text(
        yaml.dump({"release": {"slug": "a-single", "artist_id": "stab", "title": "A Single"}}),
        encoding="utf-8",
    )
    return tmp_path


def _capture(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    return calls


def test_keywords_mode_passes_no_model_flag(repo, monkeypatch):
    calls = _capture(monkeypatch)
    result = pipeline.run_promoter(repo, "a-single", mode="keywords", model="default")
    assert "--model" not in calls[0]
    assert calls[0][1:] == ["keywords", "--artist", "stab"]
    assert result["ok"] and result["model"] == "triumvirate"


def test_bio_mode_still_forces_and_takes_a_model(repo, monkeypatch):
    calls = _capture(monkeypatch)
    pipeline.run_promoter(repo, "a-single", mode="bio", model="dev")
    assert calls[0][1:] == ["bio", "--artist", "stab", "--model", "dev", "--force"]


def test_blurb_mode_takes_a_model_and_does_not_force(repo, monkeypatch):
    calls = _capture(monkeypatch)
    pipeline.run_promoter(repo, "a-single", mode="blurb", model="default")
    assert calls[0][1:] == ["blurb", "--artist", "stab", "--model", "default"]


def test_unknown_mode_is_rejected(repo, monkeypatch):
    _capture(monkeypatch)
    with pytest.raises(ValueError, match="Unknown promoter mode"):
        pipeline.run_promoter(repo, "a-single", mode="hashtags")


def test_release_without_an_artist_is_rejected(tmp_path, monkeypatch):
    releases = tmp_path / "content" / "releases"
    releases.mkdir(parents=True)
    (releases / "orphan.yaml").write_text(
        yaml.dump({"release": {"slug": "orphan", "title": "Orphan"}}), encoding="utf-8"
    )
    _capture(monkeypatch)
    with pytest.raises(ValueError, match="No artist_id"):
        pipeline.run_promoter(tmp_path, "orphan", mode="keywords")
