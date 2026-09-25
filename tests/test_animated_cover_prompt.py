"""The Nim animated-cover prompt is visual-only.

It must not carry the artist's promo blurb (which names other releases and
tracks), paces motion from the promo track's BPM, and appends the release's
hand-written visual direction.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from urllib.parse import urlencode

import yaml
from starlette.requests import Request

from mrp.admin import nim, pipeline
from mrp.admin.routes import workspace as workspace_routes
from mrp.admin.workspace import validate_release_dict
from mrp.core.migrate_site import load_structured_record

ARTIST = {
    "name": "Demo Artist",
    "promo_blurb": "Their album Other Thing anchors on the track Cast.",
    "bio_short": "Bio mentioning Other Thing.",
}


def test_prompt_leaves_out_artist_blurb_and_bio():
    prompt = nim.animated_cover_prompt({"title": "Model Man"}, ARTIST)
    assert "Model Man by Demo Artist" in prompt
    assert "Cast" not in prompt and "Other Thing" not in prompt
    assert "Artist voice context" not in prompt


def test_prompt_pace_follows_bpm():
    assert "gentle and slow" in nim.animated_cover_prompt({}, ARTIST, bpm=72)
    assert "steady and unhurried" in nim.animated_cover_prompt({}, ARTIST, bpm=110)
    assert "lively, rhythmic pulse" in nim.animated_cover_prompt({}, ARTIST, bpm=152)
    assert "pulse" not in nim.animated_cover_prompt({}, ARTIST, bpm=None)


def test_prompt_appends_visual_direction():
    release = {"title": "X", "promoter": {"animated_cover_notes": "  gears turn slowly  "}}
    assert nim.animated_cover_prompt(release, ARTIST).endswith(
        "Visual direction: gears turn slowly"
    )


def _song_fixture() -> dict:
    return yaml.safe_load(Path("tests/fixtures/content/valid/release-song.yaml").read_text())


def test_schema_allows_notes_on_singles_but_not_promo_track():
    data = _song_fixture()
    data["release"]["promoter"] = {"animated_cover_notes": "slow drift"}
    assert validate_release_dict(data) == []

    data["release"]["promoter"] = {"promo_track_slug": "anything"}
    assert validate_release_dict(data) != []


def _form_request(fields: dict[str, str]) -> Request:
    body = urlencode(fields).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/", "raw_path": b"/", "query_string": b"",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "client": ("test", 50000), "server": ("test", 80),
    }, receive)


def test_notes_route_saves_and_clears_on_a_single(tmp_path, monkeypatch):
    releases = tmp_path / "content" / "releases"
    releases.mkdir(parents=True)
    (releases / "a-single.yaml").write_text(
        Path("tests/fixtures/content/valid/release-song.yaml").read_text()
    )
    slug = _song_fixture()["release"]["slug"]
    if slug != "a-single":
        (releases / "a-single.yaml").rename(releases / f"{slug}.yaml")
    monkeypatch.setattr(workspace_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(workspace_routes.promoter_animated_notes_save(
        _form_request({"animated_cover_notes": "the dial needle sweeps"}), slug
    ))
    assert response.status_code == 200
    saved = load_structured_record(releases / f"{slug}.yaml")["release"]
    assert saved["promoter"] == {"animated_cover_notes": "the dial needle sweeps"}

    asyncio.run(workspace_routes.promoter_animated_notes_save(
        _form_request({"animated_cover_notes": ""}), slug
    ))
    saved = load_structured_record(releases / f"{slug}.yaml")["release"]
    assert "promoter" not in saved


def test_animated_cover_uses_promo_track_bpm_and_notes(tmp_path, monkeypatch):
    release_dir = tmp_path / "content" / "releases"
    artist_dir = tmp_path / "content" / "artists"
    cover_dir = tmp_path / "site" / "public" / "assets" / "releases" / "demo"
    samples_dir = tmp_path / "site" / "public" / "samples"
    critic_dir = tmp_path / "app" / "critic" / "out"
    kit_dir = tmp_path / "assets" / "processed" / "promo" / "demo"
    for directory in (release_dir, artist_dir, cover_dir, samples_dir, critic_dir, kit_dir):
        directory.mkdir(parents=True, exist_ok=True)

    release = {
        "id": "demo", "slug": "demo", "title": "Demo Album", "artist_id": "demo-artist",
        "model": "album", "release_type": "album",
        "cover_image": "site/public/assets/releases/demo/cover.jpg",
        "promoter": {"promo_track_slug": "second", "animated_cover_notes": "gears turn"},
        "tracks": [
            {"slug": "first", "title": "First", "preview_audio": "/samples/first.mp3"},
            {"slug": "second", "title": "Second", "preview_audio": "/samples/second.mp3"},
        ],
    }
    (release_dir / "demo.yaml").write_text(yaml.safe_dump({"release": release}, sort_keys=False))
    (artist_dir / "demo-artist.yaml").write_text(yaml.safe_dump({"artist": ARTIST | {"id": "demo-artist"}}))
    (cover_dir / "cover.jpg").write_bytes(b"cover")
    (samples_dir / "second.mp3").write_bytes(b"audio")
    (critic_dir / "demo-artist--first.json").write_text(json.dumps({"hard_facts": {"bpm": 70}}))
    (critic_dir / "demo-artist--second.json").write_text(json.dumps({"hard_facts": {"bpm": 152}}))
    (kit_dir / "kit.json").write_text(json.dumps({"promo_track": {"slug": "second"}}))

    prompts = []

    def fake_generate(**kwargs):
        prompts.append(kwargs["prompt"])
        Path(kwargs["output"]).write_bytes(b"visual")
        return {"adapter": "test", "model": "test", "model_id": "test"}

    monkeypatch.setattr(pipeline.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(nim, "generate_animated_cover_visual", fake_generate)
    monkeypatch.setattr(pipeline, "_mux_visual_with_audio",
                        lambda visual, audio, output: output.write_bytes(b"a"))
    monkeypatch.setattr(pipeline, "_render_spotify_canvas",
                        lambda visual, output: (output.write_bytes(b"c"), 5.0)[1])

    pipeline.run_promo_kit_animated_cover(tmp_path, "demo")

    [prompt] = prompts
    assert "lively, rhythmic pulse" in prompt
    assert "Visual direction: gears turn" in prompt
    assert "Other Thing" not in prompt
    manifest = json.loads((kit_dir / "kit.json").read_text())
    assert manifest["animated_cover"]["promo_track_bpm"] == 152
