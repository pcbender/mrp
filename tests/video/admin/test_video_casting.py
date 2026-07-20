from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
import yaml
from starlette.requests import Request

from mrp.admin import db
from mrp.admin.routes import video as video_routes
from mrp.admin.video_casting import (
    CastingEditorError,
    load_casting,
    save_casting,
)
from mrp.core.migrate_site import load_structured_record
from mrp.video.workspace import TrackProjectDocument

ROOT = Path(__file__).resolve().parents[3]
ENRICHED = ROOT / "tests" / "video" / "fixtures" / "releases" / "enriched-album.yaml"


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


def _write_cast_repo(tmp_path: Path) -> tuple[dict, dict, Path, Path]:
    record = yaml.safe_load(ENRICHED.read_text(encoding="utf-8"))
    release_path = tmp_path / "content" / "releases" / "video-contract.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    release = record["release"]
    track = release["tracks"][0]
    source = tmp_path / "assets" / "source" / "video" / "pcbender--private-track"
    source.mkdir(parents=True)
    document = TrackProjectDocument.model_validate(
        {
            "source": {
                "release": "content/releases/video-contract.yaml",
                "track_slug": "private-track",
                "track_key": "pcbender--private-track",
                "artist_id": "pcbender",
            },
            "project": {
                "version": 1,
                "title": "Private Track",
                "audio": {"master": "@mrp/master"},
                "lyrics": {
                    "source": "@mrp/lyrics",
                    "aligned": "lyrics.aligned.yaml",
                    "language": "en",
                },
                "cards": {
                    "opening": {"file": "@mrp/cover", "duration": 3},
                    "closing": {"file": "@mrp/cover", "duration": 4},
                },
                "text": {"font": "@mrp/font"},
            },
        }
    )
    project_path = source / "project.yaml"
    project_path.write_text(
        yaml.safe_dump(document.model_dump(mode="json", exclude_none=True), sort_keys=False),
        encoding="utf-8",
    )
    (source / "lyrics.aligned.yaml").write_text(
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
                        "lines": [
                            {"text": "The public lyric stays visible.", "start": 0, "end": 4}
                        ],
                    },
                    {
                        "id": "chorus_1",
                        "type": "chorus",
                        "label": "Chorus",
                        "start": 4,
                        "end": 8,
                        "lines": [{"text": "A chorus line", "start": 4, "end": 8}],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    processed = tmp_path / "assets" / "processed" / "video" / "pcbender--private-track"
    previews = processed / "previews"
    logs = processed / "logs"
    previews.mkdir(parents=True)
    logs.mkdir(parents=True)
    (previews / "frame-2.000.png").write_bytes(b"private preview")
    (logs / "preflight.json").write_text(
        json.dumps({"version": 1, "status": "passed", "input_fingerprint": "old"}),
        encoding="utf-8",
    )
    (logs / "artifacts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "artifacts": [
                    {
                        "kind": "preview",
                        "path": "assets/processed/video/pcbender--private-track/previews/frame-2.000.png",
                        "input_fingerprint": "old",
                        "recorded_at": "2026-07-20T12:00:00Z",
                        "details": {"preview_type": "frame", "time_seconds": 2},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return release, track, release_path, project_path


def _manual_fields(*, fixed_radius: str = "333") -> dict[str, list[str]]:
    return {
        "section_id": ["verse_1"],
        "section_type": ["verse"],
        "scope": ["section"],
        "action": ["save"],
        "mapping_preset": ["kinetic"],
        "palette_preset": ["aurora"],
        "auto_casting": ["true"],
        "style_visible_roles": ["vocals", "bass"],
        "style_beat_gain": ["1.8"],
        "trace_id": ["verse-hero"],
        "trace_role": ["vocals"],
        "fixed_radius": [fixed_radius],
        "moving_radius": ["77"],
        "pen_offset": ["155"],
        "geometry_rotation": ["outside"],
        "samples": ["1200"],
        "cycles_per_second": ["0.07"],
        "trail_fraction": ["0.31"],
        "ghost_count": ["2"],
        "ghost_spacing": ["0.09"],
        "head_radius": ["4"],
        "color": ["#ff5fd2"],
        "depth": ["foreground"],
        "anchor_x": ["0.25"],
        "anchor_y": ["0.4"],
        "base_scale": ["1.4"],
        "opacity": ["0.85"],
        "line_width": ["2.5"],
        "rotation_speed": ["-1.2"],
        "hue_shift": ["12"],
        "blend_mode": ["screen"],
        "driver_scale": ["bass.energy"],
        "driver_opacity": ["master.energy"],
        "driver_color": ["vocals.energy"],
        "driver_pulse": ["drums.accent"],
    }


def test_load_casting_resolves_deterministic_type_scenes(tmp_path: Path) -> None:
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)

    result = load_casting(tmp_path, release, track, section_id="chorus_1")

    assert result["selected_section"].id == "chorus_1"
    assert result["composition_source"] == "deterministic auto: chorus"
    assert [scene["trace_count"] for scene in result["sections"]] == [2, 3]
    assert result["gallery"] == [
        {
            "name": "frame-2.000.png",
            "recorded_at": "2026-07-20T12:00:00Z",
            "preview_type": "frame",
            "time_seconds": 2,
            "section_count": None,
            "stale": False,
        }
    ]


def test_save_exact_cast_is_atomic_versioned_and_invalidates_previews(tmp_path: Path) -> None:
    release, track, _release_path, project_path = _write_cast_repo(tmp_path)
    preview = (
        tmp_path
        / "assets"
        / "processed"
        / "video"
        / "pcbender--private-track"
        / "previews"
        / "frame-2.000.png"
    )

    saved = save_casting(tmp_path, release, track, _manual_fields())

    trace = saved["project"].visuals.composition_overrides["verse_1"].traces[0]
    assert trace.geometry.fixed_radius == 333
    assert trace.anchor_x == 0.25
    assert trace.drivers.pulse == "drums.accent"
    assert saved["project"].visuals.section_overrides["verse_1"].beat_gain == 1.8
    assert saved["project"].visuals.mapping_preset == "kinetic"
    assert preview.read_bytes() == b"private preview"
    preflight = json.loads(
        (
            tmp_path
            / "assets/processed/video/pcbender--private-track/logs/preflight.json"
        ).read_text()
    )
    assert preflight["status"] == "stale"
    assert saved["gallery"][0]["stale"] is True

    before = project_path.read_bytes()
    with pytest.raises(CastingEditorError, match="fixed_radius"):
        save_casting(tmp_path, release, track, _manual_fields(fixed_radius="0"))
    assert project_path.read_bytes() == before


def test_casting_route_updates_only_selected_track_and_renders_controls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release, _track, release_path, _project_path = _write_cast_repo(tmp_path)
    release["tracks"][0]["music_video"]["status"] = "timed"
    record = {"release": release}
    release_path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    untouched = release["tracks"][1].copy()
    db.init(tmp_path / "admin.db")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    fields = [
        (name, value)
        for name, values in _manual_fields().items()
        for value in values
    ]
    response = asyncio.run(
        video_routes.video_casting_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/casting",
                fields,
            ),
            "video-contract",
            "private-track",
        )
    )
    saved_release = load_structured_record(release_path)["release"]

    assert response.status_code == 200
    assert response.headers["HX-Redirect"].endswith("section=verse_1&scope=section")
    assert saved_release["tracks"][0]["music_video"]["status"] == "cast"
    assert saved_release["tracks"][1] == untouched

    page = asyncio.run(
        video_routes.video_casting(
            _get_request(
                "/releases/video-contract/tracks/private-track/video/casting"
            ),
            "video-contract",
            "private-track",
            "verse_1",
            "section",
        )
    )
    body = page.body.decode()
    assert page.status_code == 200
    assert "exact section" in body
    assert 'name="fixed_radius"' in body
    assert 'name="style_beat_gain"' in body
    assert "Reset to deterministic auto" in body
    assert "Run frame" in body
    assert "Run contact" in body


def test_private_preview_route_rejects_traversal(tmp_path: Path, monkeypatch) -> None:
    _write_cast_repo(tmp_path)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_preview_image(
            "video-contract",
            "private-track",
            "frame-2.000.png",
        )
    )
    rejected = asyncio.run(
        video_routes.video_preview_image(
            "video-contract",
            "private-track",
            "../project.yaml",
        )
    )

    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert rejected.status_code == 404
