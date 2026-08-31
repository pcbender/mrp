"""The admin's promoter invocation.

Each mode takes different flags — keywords has no --model because the
triumvirate's seats are fixed — and getting that wrong fails only at runtime,
inside a subprocess whose stderr lands in a job record. These assert the
command line without running the promoter.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from urllib.parse import urlencode

import pytest
import yaml
from starlette.requests import Request

from mrp.admin import pipeline
from mrp.admin import workspace as workspace_helpers
from mrp.admin.routes import workspace as workspace_routes
from mrp.core.migrate_site import load_structured_record


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


def _album_release() -> dict:
    return {
        "model": "album",
        "release_type": "album",
        "tracks": [
            {"slug": "first", "title": "First", "preview_audio": "/samples/first.mp3"},
            {"slug": "second", "title": "Second", "preview_audio": "/samples/second.mp3"},
        ],
    }


def test_album_promo_track_defaults_to_first_until_selection_is_saved():
    release = _album_release()
    assert workspace_helpers.configured_promo_track_slug(release) is None
    assert workspace_helpers.promo_track_unit(release)["slug"] == "first"

    workspace_helpers.set_promo_track_slug(release, "second")

    assert release["promoter"] == {"promo_track_slug": "second"}
    assert workspace_helpers.promo_track_unit(release)["slug"] == "second"


def test_stale_album_promo_track_does_not_silently_fall_back():
    release = _album_release()
    release["promoter"] = {"promo_track_slug": "removed-track"}

    with pytest.raises(ValueError, match="no longer in this release"):
        workspace_helpers.promo_track_unit(release)


def _form_request(values: dict[str, str]) -> Request:
    body = urlencode(values).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("test", 50000),
        "server": ("test", 80),
    }, receive)


def test_promoter_track_route_persists_selection(tmp_path, monkeypatch):
    releases = tmp_path / "content" / "releases"
    releases.mkdir(parents=True)
    fixture = Path("tests/fixtures/content/valid/release-album.yaml").read_text()
    (releases / "triati.yaml").write_text(fixture)
    monkeypatch.setattr(workspace_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(workspace_routes.promoter_track_save(
        _form_request({"promo_track_slug": "aiteo"}), "triati"
    ))

    assert response.status_code == 200
    saved = load_structured_record(releases / "triati.yaml")["release"]
    assert saved["promoter"]["promo_track_slug"] == "aiteo"
    assert response.headers["hx-trigger"] == "releaseSaved, promoterSaved"


def test_promoter_page_shows_one_shared_track_picker_only_for_album_models(tmp_path, monkeypatch):
    releases = tmp_path / "content" / "releases"
    artists = tmp_path / "content" / "artists"
    releases.mkdir(parents=True)
    artists.mkdir(parents=True)
    (releases / "triati.yaml").write_text(
        Path("tests/fixtures/content/valid/release-album.yaml").read_text()
    )
    ep_data = yaml.safe_load(Path("tests/fixtures/content/valid/release-album.yaml").read_text())
    ep_data["release"].update({
        "id": "short-ep", "slug": "short-ep", "title": "Short EP", "release_type": "ep",
    })
    (releases / "short-ep.yaml").write_text(yaml.safe_dump(ep_data, sort_keys=False))
    (releases / "a-single.yaml").write_text(
        Path("tests/fixtures/content/valid/release-song.yaml").read_text()
    )
    (artists / "pcbender.yaml").write_text(
        yaml.safe_dump({"artist": {"id": "pcbender", "name": "PCBender"}})
    )
    monkeypatch.setattr(workspace_routes, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(workspace_routes.db, "get_latest_job_by_command", lambda command: None)
    monkeypatch.setattr(workspace_routes.nim, "connected", lambda: False)
    request = Request({
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/", "raw_path": b"/", "query_string": b"", "headers": [],
        "client": ("test", 50000), "server": ("test", 80),
    })

    album_response = asyncio.run(workspace_routes.stage_page(request, "triati", "promoter"))
    ep_response = asyncio.run(workspace_routes.stage_page(request, "short-ep", "promoter"))
    single_response = asyncio.run(workspace_routes.stage_page(request, "a-single", "promoter"))

    album_body = album_response.body.decode()
    ep_body = ep_response.body.decode()
    single_body = single_response.body.decode()
    assert album_body.count('name="promo_track_slug"') == 1
    assert ep_body.count('name="promo_track_slug"') == 1
    assert "1. Apa" in album_body and "2. Aiteo" in album_body
    assert "Both video jobs currently default to track 1" in album_body
    assert 'name="promo_track_slug"' not in single_body


def test_both_promo_videos_use_the_same_selected_album_track(tmp_path, monkeypatch):
    from mrp.admin import critic_io, nim

    release_dir = tmp_path / "content" / "releases"
    artist_dir = tmp_path / "content" / "artists"
    cover_dir = tmp_path / "site" / "public" / "assets" / "releases" / "demo"
    samples_dir = tmp_path / "site" / "public" / "samples"
    for directory in (release_dir, artist_dir, cover_dir, samples_dir):
        directory.mkdir(parents=True, exist_ok=True)

    release = {
        "id": "demo",
        "slug": "demo",
        "title": "Demo Album",
        "artist_id": "demo-artist",
        "model": "album",
        "release_type": "album",
        "cover_image": "site/public/assets/releases/demo/cover.jpg",
        "promoter": {"promo_track_slug": "second"},
        "tracks": [
            {"slug": "first", "title": "First", "preview_audio": "/samples/first.mp3"},
            {"slug": "second", "title": "Second", "preview_audio": "/samples/second.mp3"},
        ],
    }
    (release_dir / "demo.yaml").write_text(yaml.safe_dump({"release": release}, sort_keys=False))
    (artist_dir / "demo-artist.yaml").write_text(
        yaml.safe_dump({"artist": {"id": "demo-artist", "name": "Demo Artist"}})
    )
    (cover_dir / "cover.jpg").write_bytes(b"cover")
    (samples_dir / "first.mp3").write_bytes(b"first audio")
    (samples_dir / "second.mp3").write_bytes(b"second audio")

    static_audio = []
    animated_audio = []

    def fake_run(cmd, **kwargs):
        copy_path = Path(cmd[cmd.index("--out") + 1])
        copy_path.write_text(json.dumps({"_meta": {"model": "test"}, "hashtags": []}))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    def fake_static(cover, audio, output):
        static_audio.append(audio)
        output.write_bytes(b"static")

    def fake_image(cover, output, composite):
        output.write_bytes(b"image")

    def fake_generate(**kwargs):
        Path(kwargs["output"]).write_bytes(b"visual")
        return {"adapter": "test", "model": "test", "model_id": "test"}

    def fake_mux(visual, audio, output):
        animated_audio.append(audio)
        output.write_bytes(b"animated")

    def fake_canvas(visual, output):
        output.write_bytes(b"canvas")
        return 5.0

    monkeypatch.setattr(critic_io, "promoter_bin", lambda root: "promoter")
    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline, "_render_video_short", fake_static)
    monkeypatch.setattr(pipeline, "_render_image", fake_image)
    monkeypatch.setattr(nim, "generate_animated_cover_visual", fake_generate)
    monkeypatch.setattr(pipeline, "_mux_visual_with_audio", fake_mux)
    monkeypatch.setattr(pipeline, "_render_spotify_canvas", fake_canvas)

    static_result = pipeline.run_promo_kit(tmp_path, "demo")
    animated_result = pipeline.run_promo_kit_animated_cover(tmp_path, "demo")

    selected_audio = samples_dir / "second.mp3"
    assert static_audio == [selected_audio]
    assert animated_audio == [selected_audio]
    assert static_result["promo_track_slug"] == "second"
    assert animated_result["promo_track_slug"] == "second"
    manifest = json.loads(
        (tmp_path / "assets" / "processed" / "promo" / "demo" / "kit.json").read_text()
    )
    assert manifest["promo_track"]["slug"] == "second"
    assert manifest["animated_cover"]["promo_track_slug"] == "second"


def test_album_default_does_not_skip_track_one_when_only_later_track_has_audio(tmp_path):
    release = _album_release()
    release["tracks"][0].pop("preview_audio")
    (tmp_path / "site" / "public" / "samples").mkdir(parents=True)
    (tmp_path / "site" / "public" / "samples" / "second.mp3").write_bytes(b"audio")

    with pytest.raises(ValueError, match="Promo track 'First' has no snippet"):
        pipeline._preview_audio_path(tmp_path, release)
