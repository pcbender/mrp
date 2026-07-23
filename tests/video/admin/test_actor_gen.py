from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mrp.admin import actor_gen
from mrp.admin.video_casting import CastingEditorError
from mrp.video.project import LayerGeometryConfig
from mrp.video.track_project import TrackProjectDocument
from tests.video.engine.test_workspace import _write_repo
from tests.video.engine.test_alignment import FONT_PATH


def _prepared_repo(tmp_path: Path) -> Path:
    from mrp.video.workspace import prepare_track

    repo, _ = _write_repo(tmp_path)
    prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    return repo


def test_title_text_prefers_title() -> None:
    assert actor_gen.title_text({"title": "My Song", "slug": "my-song"}) == "My Song"
    assert actor_gen.title_text({"slug": "fallback"}) == "fallback"
    assert actor_gen.title_text({}) == ""


def test_build_title_document_inserts_text_actor() -> None:
    payload = {"project": {}}
    d = "M 0 0 L 10 0 L 10 10 Z M 20 0 L 30 0 L 30 10 Z"
    actor_gen.build_title_document(payload, "Hi", d)
    actor = payload["project"]["visuals"]["actors"]["song-title"]
    assert actor["components"][0]["geometry"]["family"] == "text"
    # The component's geometry validates as a text layer.
    LayerGeometryConfig(**actor["components"][0]["geometry"])
    assert actor["character"] == "vocals"


def test_generate_title_actor_end_to_end(tmp_path: Path) -> None:
    repo = _prepared_repo(tmp_path)
    result = actor_gen.generate_title_actor(repo, "fixture-release", "fixture-track")

    assert result["status"] == "generated"
    assert result["actor"] == "song-title"
    assert result["title"] == "Fixture Track"
    assert result["contours"] >= 1

    project_path = (
        repo
        / "assets/source/video/fixture-artist--fixture-track/project.yaml"
    )
    document = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    actor = document.project.visuals.actors["song-title"]
    assert actor.components[0].geometry.family == "text"
    assert actor.character == "vocals"


def test_generate_title_actor_only_if_missing_skips(tmp_path: Path) -> None:
    repo = _prepared_repo(tmp_path)
    first = actor_gen.generate_title_actor(repo, "fixture-release", "fixture-track")
    assert first["status"] == "generated"

    skipped = actor_gen.generate_title_actor(
        repo, "fixture-release", "fixture-track", only_if_missing=True
    )
    assert skipped["status"] == "skipped"

    # Without the flag it regenerates (replaces).
    again = actor_gen.generate_title_actor(repo, "fixture-release", "fixture-track")
    assert again["status"] == "generated"


def test_generate_title_actor_requires_prepared_project(tmp_path: Path) -> None:
    repo, _ = _write_repo(tmp_path)  # no prepare
    with pytest.raises(CastingEditorError):
        actor_gen.generate_title_actor(repo, "fixture-release", "fixture-track")


def test_after_prepare_hook_launches_only_for_prepare(monkeypatch) -> None:
    from mrp.admin import video_jobs

    calls: list[tuple] = []

    def fake_launch(command, fn, *args, **kwargs):
        calls.append((command, fn.__name__, args, kwargs))
        return "job123"

    monkeypatch.setattr("mrp.admin.jobs.launch", fake_launch)

    monkeypatch.setattr(
        video_jobs.db,
        "get_video_job",
        lambda job_id: {
            "kind": "prepare",
            "repo_root": "/tmp/repo",
            "release_slug": "rel",
            "track_slug": "trk",
        },
    )
    video_jobs._after_prepare_success("j1")
    assert len(calls) == 1
    assert calls[0][1] == "generate_title_actor"
    assert calls[0][3] == {"only_if_missing": True}

    # A non-prepare job does not trigger title generation.
    calls.clear()
    monkeypatch.setattr(
        video_jobs.db, "get_video_job", lambda job_id: {"kind": "render"}
    )
    video_jobs._after_prepare_success("j2")
    assert calls == []
