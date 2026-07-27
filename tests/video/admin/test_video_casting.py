from __future__ import annotations

import asyncio
import json
import subprocess
import sys
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
    save_track_actor,
)
from mrp.core.migrate_site import load_structured_record
from mrp.video.track_project import TrackProjectDocument

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
        "geometry_family": ["spirogram"],
        "liss_freq_x": ["3"],
        "liss_freq_y": ["2"],
        "liss_delta": ["1.5708"],
        "rose_n": ["5"],
        "rose_d": ["1"],
        "sf_m": ["6"],
        "sf_n1": ["0.3"],
        "sf_n2": ["0.3"],
        "sf_n3": ["0.3"],
        "path_data": [""],
        "harm_freq_x": ["3.01"],
        "harm_freq_y": ["2"],
        "harm_delta": ["1.5708"],
        "harm_damping": ["0.02"],
        "harm_turns": ["12"],
        "fixed_radius": [fixed_radius],
        "moving_radius": ["77"],
        "pen_offset": ["155"],
        "phase": ["0.5"],
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
        "color_flow_source": [""],
        "color_flow_swing": ["90"],
        "driver_scale": ["bass.energy"],
        "driver_opacity": ["master.energy"],
        "driver_color": ["vocals.energy"],
        "driver_pulse": ["drums.accent"],
    }


def _actor_fields(*, action: str = "actor_save") -> dict[str, list[str]]:
    fields = _manual_fields(fixed_radius="205")
    fields.update(
        {
            "action": [action],
            "scope": ["type"],
            "actor_original_id": [""],
            "actor_edit_id": ["vocal-lantern"],
            "actor_name": ["Vocal Lantern"],
            "actor_description": ["A rose-colored lead identity."],
            "actor_character": ["bass"],
            "trace_id": ["shape"],
            "color_flow_source": ["curvature"],
            "color_flow_swing": ["120"],
        }
    )
    return fields


def _actor_cast_fields() -> dict[str, list[str]]:
    return {
        "section_id": ["verse_1"],
        "section_type": ["verse"],
        "scope": ["type"],
        "action": ["save_cast"],
        "mapping_preset": ["balanced"],
        "palette_preset": ["layer"],
        "auto_casting": ["true"],
        "assignment_id": ["lead"],
        "assigned_actor": ["vocal-lantern"],
        "direction_anchor_x": ["0.62"],
        "direction_anchor_y": ["0.35"],
        "direction_scale": ["1.25"],
        "direction_opacity": ["0.9"],
        "direction_rotation": ["0.4"],
        "direction_hue": ["12"],
        "direction_depth": ["foreground"],
        "direction_visible": ["true"],
        "style_beat_gain": ["1.4"],
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


def test_casting_project_load_does_not_import_audio_workspace(tmp_path: Path) -> None:
    _release, _track, _release_path, project_path = _write_cast_repo(tmp_path)
    script = f"""
import builtins
import sys
from pathlib import Path

original_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name == "librosa" or name.startswith("librosa."):
        raise ModuleNotFoundError("blocked renderer dependency: librosa")
    return original_import(name, *args, **kwargs)

builtins.__import__ = guarded_import
from mrp.admin.video_casting import _load_project

document = _load_project(Path({str(project_path)!r}))
assert document.source.track_slug == "private-track"
assert "mrp.video.workspace" not in sys.modules
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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
    assert trace.geometry.phase == 0.5
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


def test_actor_identity_cast_and_direction_compile_without_rewriting_renderer(
    tmp_path: Path,
) -> None:
    release, track, _release_path, project_path = _write_cast_repo(tmp_path)

    actor_id = save_track_actor(tmp_path, release, track, _actor_fields())
    assert actor_id == "vocal-lantern"
    actor_result = load_casting(tmp_path, release, track)
    assert actor_result["project"].visuals.actors["vocal-lantern"].name == "Vocal Lantern"
    assert actor_result["project"].visuals.actors["vocal-lantern"].character == "bass"

    cast_result = save_casting(tmp_path, release, track, _actor_cast_fields())

    actor_cast = cast_result["project"].visuals.section_casts["verse"]
    assert actor_cast.actors[0].actor == "vocal-lantern"
    assert cast_result["composition_source"] == "actor cast for all verse scenes"
    compiled = cast_result["composition"].traces[0]
    assert compiled.id == "lead--shape"
    assert compiled.geometry.fixed_radius == 205
    assert compiled.color_flow is not None
    assert compiled.color_flow.source == "curvature"
    assert compiled.color_flow.swing_degrees == 120
    assert compiled.anchor_x == pytest.approx(0.37)
    assert compiled.base_scale == pytest.approx(1.75)
    assert compiled.drivers.scale == "bass.energy"

    stored = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    assert stored.project.visuals.actors["vocal-lantern"].components[0].anchor_x == 0.25


def test_storyboard_payload_carries_compiled_placement_and_actor_identities(
    tmp_path: Path,
) -> None:
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())
    cast_result = save_casting(tmp_path, release, track, _actor_cast_fields())

    storyboard = cast_result["storyboard"]

    # Every compiled trace the renderer would draw is available for the canvas,
    # tagged with the assignment prefix so a dragged shape maps back to its card.
    assert storyboard["margin"] == 0.08
    trace = storyboard["traces"][0]
    assert trace["assignment"] == "lead"
    assert trace["anchor_x"] == pytest.approx(0.37)
    assert trace["base_scale"] == pytest.approx(1.75)
    assert {"family", "fixed_radius", "phase", "rotation", "samples", "color", "opacity"} <= set(trace)
    assert trace["family"] == "spirogram"
    assert trace["phase"] == 0.5
    assert trace["color_flow"] == {"source": "curvature", "swing_degrees": 120.0}

    # Actor identities let the browser recompile placement live from the fields.
    identity = storyboard["actors"]["vocal-lantern"]
    assert identity["character"] == "bass"
    assert identity["components"][0]["anchor_x"] == 0.25

    # Samples are capped so a large curve does not bloat the client payload.
    assert all(shape["samples"] <= 1200 for shape in storyboard["traces"])


def test_recommended_actor_onboarding_and_exact_scene_direction(tmp_path: Path) -> None:
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)

    recommended = save_casting(
        tmp_path,
        release,
        track,
        {
            "section_id": ["verse_1"],
            "section_type": ["verse"],
            "scope": ["type"],
            "action": ["recommended"],
        },
    )

    type_cast = recommended["project"].visuals.section_casts["verse"]
    assert len(type_cast.actors) == 2
    assert len(recommended["project"].visuals.actors) == 2
    first = type_cast.actors[0]
    exact_fields = {
        "section_id": ["verse_1"],
        "section_type": ["verse"],
        "scope": ["section"],
        "action": ["save_cast"],
        "assignment_id": [first.id],
        "assigned_actor": [first.actor],
        "direction_anchor_x": ["0.7"],
        "direction_anchor_y": [""],
        "direction_scale": ["1.1"],
        "direction_opacity": ["1"],
        "direction_rotation": ["0"],
        "direction_hue": ["0"],
        "direction_depth": [""],
        "direction_visible": ["true"],
    }

    exact = save_casting(tmp_path, release, track, exact_fields)

    assert exact["composition_source"] == "exact scene actor cast"
    assert exact["project"].visuals.cast_overrides["verse_1"].actors[0].direction.scale == 1.1
    assert exact["project"].visuals.actors[first.actor].character == "bass"


def test_global_actor_library_imports_a_pinned_project_snapshot(tmp_path: Path) -> None:
    release, track, _release_path, project_path = _write_cast_repo(tmp_path)
    fields = _actor_fields(action="actor_publish")

    actor_id = save_track_actor(tmp_path, release, track, fields)
    assert actor_id == "vocal-lantern"
    published = load_casting(tmp_path, release, track)
    library_path = (
        tmp_path / "assets/source/video/actors/vocal-lantern.yaml"
    )
    assert library_path.is_file()
    library_actor_payload = yaml.safe_load(library_path.read_text(encoding="utf-8"))["actor"]
    assert "character" not in library_actor_payload
    assert library_actor_payload["components"][0]["color_flow"] == {
        "source": "curvature",
        "swing_degrees": 120.0,
    }
    revision = published["library_actors"][0]["revision"]

    payload = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    payload["project"]["visuals"]["actors"] = {}
    project_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    imported_id = save_track_actor(
        tmp_path,
        release,
        track,
        {
            "action": ["actor_import"],
            "library_actor_id": ["vocal-lantern"],
        },
    )
    assert imported_id == "vocal-lantern"
    imported = load_casting(tmp_path, release, track)

    snapshot = imported["project"].visuals.actors["vocal-lantern"]
    assert snapshot.library_source is not None
    assert snapshot.library_source.revision == revision
    assert snapshot.description == "A rose-colored lead identity."
    assert snapshot.character == "vocals"

    library_payload = yaml.safe_load(library_path.read_text(encoding="utf-8"))
    library_payload["actor"]["name"] = "Library Name Changed Later"
    library_path.write_text(
        yaml.safe_dump(library_payload, sort_keys=False),
        encoding="utf-8",
    )
    reloaded = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    assert reloaded.project.visuals.actors["vocal-lantern"].name == "Vocal Lantern"


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
    # The anchor keeps a saved cast on the scene it was edited on: HX-Redirect
    # is a full page load, so without it the editor reopens at the top.
    assert response.headers["HX-Redirect"].endswith(
        "section=verse_1&scope=section#scene-casting"
    )
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
    assert "Only this scene" in body
    assert "Actor Library" in body
    assert "Actor Designer" in body
    assert "Scene Casting" in body
    assert body.index("<h2>Actor Library") < body.index("<h2>Scene Casting")
    assert body.index("<h2>Actor Designer") < body.index("<h2>Scene Casting")
    assert "Create recommended actors" in body
    assert 'name="actor_character"' in body
    assert 'name="reacts_to"' not in body
    assert "/video/actors" in body
    assert 'name="fixed_radius"' in body
    assert 'name="geometry_family"' in body
    assert 'data-family="lissajous"' in body
    # The path_data field serves both the path and text families.
    assert 'data-family="path text"' in body
    assert 'name="path_data"' in body
    assert 'data-family="harmonograph"' in body
    assert 'name="harm_damping"' in body
    assert 'name="phase"' in body
    assert 'name="color_flow_source"' in body
    assert 'type="range"' in body
    assert "/static/spiro-preview.js" in body
    assert 'id="track-actor-designer"' in body
    assert 'class="actor-designer-live-layout"' in body
    assert 'class="actor-designer-controls"' in body
    assert 'width="720" height="720"' in body
    assert "Component offset X" in body
    assert (
        'title="Horizontal position inside the actor identity preview. '
        'Scene position is set later in Scene Casting."'
    ) in body
    assert "Run frame" in body
    assert "Run contact" in body


def test_track_actor_route_does_not_depend_on_or_mutate_scene_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release, _track, release_path, project_path = _write_cast_repo(tmp_path)
    release["tracks"][0]["music_video"]["status"] = "timed"
    release_path.write_text(
        yaml.safe_dump({"release": release}, sort_keys=False),
        encoding="utf-8",
    )
    db.init(tmp_path / "admin.db")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)
    fields = [
        (name, value)
        for name, values in _actor_fields().items()
        for value in values
    ] + [("return_section", "chorus_1"), ("return_scope", "section")]

    response = asyncio.run(
        video_routes.video_actor_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/actors",
                fields,
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 200
    assert "section=chorus_1" in response.headers["HX-Redirect"]
    assert "scope=section" in response.headers["HX-Redirect"]
    assert "actor=vocal-lantern" in response.headers["HX-Redirect"]
    stored = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    assert stored.project.visuals.actors["vocal-lantern"].character == "bass"
    assert stored.project.visuals.section_casts == {}
    assert stored.project.visuals.cast_overrides == {}
    saved_release = load_structured_record(release_path)["release"]
    assert saved_release["tracks"][0]["music_video"]["status"] == "timed"


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


def test_lissajous_actor_round_trips_family_geometry(tmp_path: Path) -> None:
    release, track, _release_path, project_path = _write_cast_repo(tmp_path)
    fields = _actor_fields()
    fields.update(
        {
            "geometry_family": ["lissajous"],
            "liss_freq_x": ["5"],
            "liss_freq_y": ["4"],
            "liss_delta": ["0.7"],
            # Hidden inputs for the inactive family post blank values.
            "fixed_radius": [""],
            "moving_radius": [""],
            "pen_offset": [""],
        }
    )

    actor_id = save_track_actor(tmp_path, release, track, fields)

    stored = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    geometry = stored.project.visuals.actors[actor_id].components[0].geometry
    assert geometry.family == "lissajous"
    assert geometry.liss_freq_x == 5
    assert geometry.liss_freq_y == 4
    assert geometry.liss_delta == 0.7
    assert geometry.fixed_radius is None
    payload = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    raw = payload["project"]["visuals"]["actors"][actor_id]["components"][0]["geometry"]
    assert "fixed_radius" not in raw
    assert raw["family"] == "lissajous"


def test_scene_wardrobe_fields_round_trip_and_blank_keeps_the_actor_look(
    tmp_path: Path,
) -> None:
    """Blank wardrobe posts must stay absent, not freeze the actor's look in.

    The cast form always submits one value per column, so an untouched wardrobe
    arrives as an empty string. If that were stored, the scene would silently
    pin whatever the actor happened to look like at cast time.
    """
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())

    bare = save_casting(tmp_path, release, track, _actor_cast_fields())
    direction = bare["project"].visuals.section_casts["verse"].actors[0].direction
    assert direction.color is None
    assert direction.line_width is None
    assert direction.blend_mode is None
    assert bare["composition"].traces[0].color_locked is False

    dressed = save_casting(
        tmp_path,
        release,
        track,
        _actor_cast_fields()
        | {
            "direction_color": ["#ff0000"],
            "direction_line_width": ["6"],
            "direction_blend": ["normal"],
        },
    )

    direction = dressed["project"].visuals.section_casts["verse"].actors[0].direction
    assert direction.color == "#ff0000"
    assert direction.line_width == 6
    assert direction.blend_mode == "normal"
    compiled = dressed["composition"].traces[0]
    assert compiled.color == "#ff0000"
    assert compiled.color_locked is True
    assert compiled.line_width == 6
    assert compiled.blend_mode == "normal"


def test_scene_transition_round_trips_and_the_track_default_stores_nothing(
    tmp_path: Path,
) -> None:
    """A scene that arrives the ordinary way must leave no entry behind.

    Storing "0.65s smooth" for every scene would pin each one to whatever the
    track default was the day it was cast, which is exactly what inheriting is
    supposed to avoid.
    """
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())

    bare = save_casting(tmp_path, release, track, _actor_cast_fields())
    assert bare["project"].visuals.section_transitions == {}
    assert bare["transition"].seconds is None
    assert bare["transition"].curve == "smooth"
    assert bare["transition_source"] == "track default"

    directed = save_casting(
        tmp_path,
        release,
        track,
        _actor_cast_fields()
        | {"transition_seconds": ["1.2"], "transition_curve": ["ease_in"]},
    )
    transition = directed["project"].visuals.section_transitions["verse"]
    assert transition.seconds == 1.2
    assert transition.curve == "ease_in"
    assert directed["transition_source"] == "transition for all verse scenes"

    # A curve alone still inherits the track's duration.
    curve_only = save_casting(
        tmp_path,
        release,
        track,
        _actor_cast_fields() | {"transition_curve": ["cut"]},
    )
    stored = curve_only["project"].visuals.section_transitions["verse"]
    assert stored.model_dump(exclude_none=True) == {"curve": "cut", "gap": "span"}

    restored = save_casting(tmp_path, release, track, _actor_cast_fields())
    assert restored["project"].visuals.section_transitions == {}


def test_gap_covering_round_trips_and_the_editor_reports_the_dead_air(
    tmp_path: Path,
) -> None:
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())

    # Opting out is the choice worth storing now that spanning is the default.
    saved = save_casting(
        tmp_path,
        release,
        track,
        _actor_cast_fields() | {"transition_gap": ["hold"]},
    )

    stored = saved["project"].visuals.section_transitions["verse"]
    assert stored.gap == "hold"
    # A curve nobody touched still stores its default alongside the gap, so the
    # entry reads as a complete instruction rather than a fragment.
    assert stored.model_dump(exclude_none=True) == {"curve": "smooth", "gap": "hold"}
    assert saved["transition"].gap == "hold"
    assert "selected_gap" in saved
    assert saved["selected_gap"] == 0.0

    spanned = save_casting(tmp_path, release, track, _actor_cast_fields())
    assert spanned["project"].visuals.section_transitions == {}
    assert spanned["transition"].gap == "span"


def test_unknown_gap_behaviour_is_refused(tmp_path: Path) -> None:
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())

    with pytest.raises(CastingEditorError):
        save_casting(
            tmp_path,
            release,
            track,
            _actor_cast_fields() | {"transition_gap": ["stretch"]},
        )


def test_exact_scene_transition_is_stored_against_the_scene_not_its_type(
    tmp_path: Path,
) -> None:
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())

    saved = save_casting(
        tmp_path,
        release,
        track,
        _actor_cast_fields()
        | {
            "scope": ["section"],
            "transition_seconds": ["0"],
            "transition_curve": ["linear"],
        },
    )

    visuals = saved["project"].visuals
    assert visuals.section_transitions == {}
    assert visuals.transition_overrides["verse_1"].seconds == 0
    assert visuals.transition_overrides["verse_1"].curve == "linear"
    assert saved["transition_source"] == "exact scene transition"

    cleared = save_casting(
        tmp_path,
        release,
        track,
        _actor_cast_fields() | {"scope": ["section"], "action": ["clear"]},
    )
    assert cleared["project"].visuals.transition_overrides == {}


def test_saving_a_cast_from_a_form_predating_transitions_still_works(
    tmp_path: Path,
) -> None:
    """The transition columns are optional, like wardrobe and energy before them."""
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())
    fields = _actor_cast_fields()
    assert "transition_curve" not in fields

    saved = save_casting(tmp_path, release, track, fields)

    assert saved["project"].visuals.section_casts["verse"].actors[0].actor == (
        "vocal-lantern"
    )


def test_casting_page_offers_the_transition_on_a_cast_scene(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release, track, release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())
    save_casting(
        tmp_path,
        release,
        track,
        _actor_cast_fields() | {"transition_seconds": ["1.2"]},
    )
    db.init(tmp_path / "admin.db")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    page = asyncio.run(
        video_routes.video_casting(
            _get_request(
                "/releases/video-contract/tracks/private-track/video/casting"
            ),
            "video-contract",
            "private-track",
            "verse_1",
            "type",
        )
    )
    body = page.body.decode()

    assert page.status_code == 200
    assert "Transition in" in body
    assert 'name="transition_seconds"' in body
    assert 'name="transition_curve"' in body
    assert 'name="transition_gap"' in body
    assert "No gap before this scene" in body
    assert 'value="1.2"' in body
    assert "transition for all verse scenes" in body
    # The transition belongs to the scene, ahead of the advanced style block.
    assert body.index("Transition in") < body.index("Advanced whole-scene response")


def test_unknown_transition_curves_are_refused(tmp_path: Path) -> None:
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())

    with pytest.raises(CastingEditorError):
        save_casting(
            tmp_path,
            release,
            track,
            _actor_cast_fields() | {"transition_curve": ["wipe_left"]},
        )


def test_scene_energy_fields_round_trip_and_blank_leaves_no_override(
    tmp_path: Path,
) -> None:
    """An untouched energy block must not be stored at all.

    Writing an empty trace override would be harmless today but would pin the
    actor's energy the moment a default changed, so absence has to survive.
    """
    release, track, _release_path, _project_path = _write_cast_repo(tmp_path)
    save_track_actor(tmp_path, release, track, _actor_fields())

    bare = save_casting(tmp_path, release, track, _actor_cast_fields())
    direction = bare["project"].visuals.section_casts["verse"].actors[0].direction
    assert direction.trace.model_dump(exclude_none=True) == {}

    driven = save_casting(
        tmp_path,
        release,
        track,
        _actor_cast_fields()
        | {
            "direction_cycles": ["0.9"],
            "direction_ghosts": ["0"],
        },
    )

    direction = driven["project"].visuals.section_casts["verse"].actors[0].direction
    assert direction.trace.cycles_per_second == 0.9
    assert direction.trace.ghost_count == 0
    assert direction.trace.trail_fraction is None

    compiled = driven["composition"].traces[0].trace
    assert compiled.cycles_per_second == 0.9
    assert compiled.ghost_count == 0
    # Inherited from the actor rather than reset to the schema default of 0.24.
    assert compiled.trail_fraction == 0.31
    assert compiled.ghost_spacing == 0.09
