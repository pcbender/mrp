from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest
import yaml
from starlette.requests import Request

from mrp.admin import video_live_preview
from mrp.admin.routes import video as video_routes
from mrp.admin.video_live_preview import (
    LivePreviewError,
    STATE_SCHEMA,
    build_live_preview_document,
)
from mrp.video.analysis import (
    ANALYSIS_FEATURES,
    AnalysisBundle,
    FeatureTimeline,
    SemanticControl,
    _analysis_key,
    _write_cache,
)
from mrp.video.choreography import ChoreographyState
from mrp.video.mappings import AudioVisualState, SemanticSample, map_layer_state
from mrp.video.presets import MappingPreset
from mrp.video.project import VisualLayerConfig
from mrp.video.project import load_project_manifest
from mrp.video.track_project import TrackProjectDocument


@pytest.fixture(autouse=True)
def _isolate_document_memo():
    """Keep the process-wide build memo from leaking between tests."""
    video_live_preview._DOCUMENT_MEMO.clear()
    yield
    video_live_preview._DOCUMENT_MEMO.clear()


def _layer(trace_id: str = "lead", *, radius: int = 96) -> dict:
    return {
        "id": trace_id,
        "role": "vocals",
        "geometry": {
            "fixed_radius": radius,
            "moving_radius": 32,
            "pen_offset": 48,
            "samples": 900,
        },
        "trace": {
            "cycles_per_second": 0.08,
            "trail_fraction": 0.3,
            "ghost_count": 1,
            "ghost_spacing": 0.08,
            "head_radius": 3,
        },
        "color": "#ff5fd2",
        "anchor_x": 0.5,
        "anchor_y": 0.5,
    }


def _write_repo(
    root: Path,
    *,
    duration: str = "0:08",
    visuals: dict | None = None,
) -> tuple[dict, dict, Path]:
    release = {
        "id": "video-contract",
        "slug": "video-contract",
        "title": "Video Contract",
        "artist_id": "pcbender",
        "model": "album",
        "release_type": "album",
        "status": "draft",
        "tracks": [
            {
                "number": 1,
                "title": "Private Track",
                "slug": "private-track",
                "duration": duration,
                "instrumental": False,
                "master_path": "private/master.bin",
                "music_video": {
                    "project": (
                        "assets/source/video/pcbender--private-track/project.yaml"
                    ),
                    "status": "cast",
                },
            }
        ],
    }
    release_path = root / "content" / "releases" / "video-contract.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        yaml.safe_dump({"release": release}, sort_keys=False),
        encoding="utf-8",
    )
    track = release["tracks"][0]
    project_value = {
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
            "analysis": {"cache_dir": "cache/analysis"},
            "visuals": visuals
            or {
                "auto_casting": True,
                "layers": [_layer()],
            },
        },
    }
    document = TrackProjectDocument.model_validate(project_value)
    source = root / "assets" / "source" / "video" / "pcbender--private-track"
    source.mkdir(parents=True)
    project_path = source / "project.yaml"
    project_path.write_text(
        yaml.safe_dump(
            document.model_dump(mode="json", exclude_none=True),
            sort_keys=False,
        ),
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
                            {
                                "text": "The public lyric stays visible.",
                                "start": 0,
                                "end": 4,
                            }
                        ],
                    },
                    {
                        "id": "chorus_1",
                        "type": "chorus",
                        "label": "Chorus",
                        "start": 4,
                        "end": 8,
                        "lines": [
                            {"text": "A chorus line", "start": 4, "end": 8}
                        ],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    master = root / "private" / "master.bin"
    master.parent.mkdir()
    master.write_bytes(b"private master fixture")
    return release, track, project_path


def _semantic_controls() -> dict[str, SemanticControl]:
    return {
        "master": SemanticControl("master", "rms", "onset_strength"),
        "drums": SemanticControl("master", "high_energy", "onset_strength"),
        "bass": SemanticControl("master", "low_energy", "spectral_flux"),
        "vocals": SemanticControl("master", "mid_energy", "vocal_activity"),
        "instruments": SemanticControl("master", "mid_energy", "spectral_flux"),
    }


def _write_analysis(
    root: Path,
    document: TrackProjectDocument,
    *,
    duration: float = 8,
) -> str:
    key_root = root / "assets" / "processed" / "video" / "pcbender--private-track"
    runtime_path = key_root / "analysis" / "project.runtime.yaml"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    master = root / "private" / "master.bin"
    runtime_value = document.project.model_dump(mode="json", exclude_none=True)
    runtime_value["audio"] = {
        "master": Path(os.path.relpath(master, runtime_path.parent)).as_posix(),
        "stems": {},
        "duration_tolerance": document.project.audio.duration_tolerance,
    }
    runtime_path.write_text(
        yaml.safe_dump(runtime_value, sort_keys=False),
        encoding="utf-8",
    )
    runtime = load_project_manifest(runtime_path)
    master_hash = hashlib.sha256(master.read_bytes()).hexdigest()
    cache_key = _analysis_key(runtime, {"master": master_hash})
    values = {
        name: np.asarray([0.1, 0.9], dtype=np.float32)
        for name in ANALYSIS_FEATURES
    }
    timeline = FeatureTimeline(
        times=np.asarray([0, duration], dtype=np.float64),
        features=values,
        tempo_bpm=120,
        beat_times=np.asarray([0, 0.5], dtype=np.float64),
    )
    bundle = AnalysisBundle(
        cache_key=cache_key,
        duration=duration,
        sample_rate=22_050,
        frame_length=2_048,
        hop_length=512,
        input_hashes={"master": master_hash},
        tracks={"master": timeline},
        semantic_controls=_semantic_controls(),
    )
    cache_path = runtime_path.parent / "cache" / "analysis" / f"{cache_key}.npz"
    _write_cache(cache_path, bundle)
    logs = key_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "preflight.json").write_text(
        json.dumps(
            {
                "version": 1,
                "status": "passed",
                "input_hashes": {"audio.master": master_hash},
                "master_duration": duration,
            }
        ),
        encoding="utf-8",
    )
    return cache_key


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def _build(root: Path, release: dict, track: dict):
    return build_live_preview_document(
        root,
        "video-contract",
        release,
        "private-track",
        track,
    )


def _assert_private_data_absent(body: bytes) -> None:
    text = body.decode("utf-8").casefold()
    for forbidden in (
        "/home/",
        "/mnt/",
        "master_path",
        "cache_dir",
        ".wav",
        ".mp3",
        ".flac",
    ):
        assert forbidden not in text


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


def test_geometry_only_document_is_deterministic_private_and_read_only(
    tmp_path: Path,
) -> None:
    release, track, _project_path = _write_repo(tmp_path)
    before = _snapshot(tmp_path)

    first = _build(tmp_path, release, track)
    second = _build(tmp_path, release, track)

    assert first.body == second.body
    assert first.etag == second.etag
    assert first.payload["mode"] == "geometry-only"
    assert first.payload["mode_reason"]["code"] == "analysis_missing"
    assert first.payload["mode_reason"]["action_url"].endswith(
        "/video-contract/tracks/private-track/video"
    )
    assert "state_samples_base64" not in first.payload
    assert first.payload["sections"][1]["previous_section_id"] == "verse_1"
    # This fixture casts nothing, so every scene resolves to the empty
    # composition and the preview draws the background alone.
    assert first.payload["compositions"]["uncast:empty"]["traces"] == []
    assert all(
        section["composition_key"] == "uncast:empty"
        for section in first.payload["sections"]
    )
    assert first.payload["text"] == {
        "size": 60,
        "maximum_width_fraction": 0.82,
        "position": "bottom",
        "active_color": "#ffffff",
    }
    assert _snapshot(tmp_path) == before
    assert len(first.body) < video_live_preview.MAX_RESPONSE_BYTES
    _assert_private_data_absent(first.body)


def test_current_cache_samples_state_and_visual_edits_do_not_stale_audio(
    tmp_path: Path,
) -> None:
    release, track, project_path = _write_repo(tmp_path)
    document = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    cache_key = _write_analysis(tmp_path, document)
    before = _snapshot(tmp_path)

    first = _build(tmp_path, release, track)

    assert first.payload["mode"] == "audio-reactive"
    assert first.payload["source_revision"]["analysis_key"] == cache_key
    assert first.payload["state_rate_hz"] == 20
    assert first.payload["state_width"] == len(STATE_SCHEMA) == 28
    assert first.payload["state_sample_count"] == 161
    decoded = base64.b64decode(first.payload["state_samples_base64"])
    assert len(decoded) == 161 * 28 * 4
    state = np.frombuffer(decoded, dtype="<f4").reshape(161, 28)
    assert state[0, 0] == 0
    assert state[-1, 0] == 1
    assert np.all(np.isfinite(state))
    assert _snapshot(tmp_path) == before
    _assert_private_data_absent(first.body)

    value = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    value["project"]["video"]["background"] = "#202030"
    project_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    changed = _build(tmp_path, release, track)
    assert changed.payload["mode"] == "audio-reactive"
    assert changed.payload["source_revision"]["analysis_key"] == cache_key
    assert (
        changed.payload["source_revision"]["project_sha256"]
        != first.payload["source_revision"]["project_sha256"]
    )

    value["project"]["analysis"]["release_seconds"] = 0.5
    project_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    settings_changed = _build(tmp_path, release, track)
    assert settings_changed.payload["mode"] == "geometry-only"
    assert settings_changed.payload["mode_reason"]["code"] == "analysis_stale"


def test_newer_audio_falls_back_without_creating_analysis(tmp_path: Path) -> None:
    release, track, project_path = _write_repo(tmp_path)
    document = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    _write_analysis(tmp_path, document)
    cache_files = tuple(tmp_path.rglob("*.npz"))
    newest = max(path.stat().st_mtime_ns for path in cache_files)
    master = tmp_path / "private" / "master.bin"
    os.utime(master, ns=(newest + 1_000_000, newest + 1_000_000))
    before = _snapshot(tmp_path)

    result = _build(tmp_path, release, track)

    assert result.payload["mode"] == "geometry-only"
    assert result.payload["mode_reason"]["code"] == "analysis_stale"
    assert tuple(tmp_path.rglob("*.npz")) == cache_files
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("visuals", "expected_key"),
    [
        (
            {
                "auto_casting": True,
                "layers": [_layer()],
                "composition_overrides": {
                    "verse_1": {"traces": [_layer("exact")]}
                },
            },
            "section:verse_1",
        ),
        (
            {
                "auto_casting": True,
                "layers": [_layer()],
                "section_compositions": {
                    "Verse": {"traces": [_layer("typed")]}
                },
            },
            "type:verse",
        ),
        # Nothing casts this scene, so it draws nothing — global layers and the
        # auto-casting flag no longer stand in for a cast that was never made.
        (
            {"auto_casting": True, "layers": [_layer()]},
            "uncast:empty",
        ),
        (
            {"auto_casting": False, "layers": [_layer("legacy")]},
            "uncast:empty",
        ),
    ],
)
def test_canonical_composition_resolution_modes(
    tmp_path: Path,
    visuals: dict,
    expected_key: str,
) -> None:
    release, track, _project_path = _write_repo(tmp_path, visuals=visuals)

    result = _build(tmp_path, release, track)

    assert result.payload["sections"][0]["composition_key"] == expected_key
    assert expected_key in result.payload["compositions"]


def test_project_timing_and_analysis_each_change_source_revision(
    tmp_path: Path,
) -> None:
    release, track, project_path = _write_repo(tmp_path)
    document = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    _write_analysis(tmp_path, document)
    first = _build(tmp_path, release, track)

    lyrics_path = project_path.with_name("lyrics.aligned.yaml")
    lyrics_value = yaml.safe_load(lyrics_path.read_text(encoding="utf-8"))
    lyrics_value["sections"][0]["lines"][0]["text"] = "Changed lyric"
    lyrics_path.write_text(
        yaml.safe_dump(lyrics_value, sort_keys=False),
        encoding="utf-8",
    )
    timing_changed = _build(tmp_path, release, track)
    assert (
        timing_changed.payload["source_revision"]["lyrics_sha256"]
        != first.payload["source_revision"]["lyrics_sha256"]
    )

    master = tmp_path / "private" / "master.bin"
    master.write_bytes(b"changed private master fixture")
    _write_analysis(tmp_path, document)
    analysis_changed = _build(tmp_path, release, track)
    assert (
        analysis_changed.payload["source_revision"]["analysis_key"]
        != first.payload["source_revision"]["analysis_key"]
    )


def test_duration_and_response_bounds_are_structured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, track, _project_path = _write_repo(tmp_path, duration="6:01")
    with pytest.raises(LivePreviewError) as duration_error:
        _build(tmp_path, release, track)
    assert duration_error.value.code == "duration_limit"
    assert duration_error.value.status_code == 413

    release, track, _project_path = _write_repo(tmp_path / "small")
    monkeypatch.setattr(video_live_preview, "MAX_RESPONSE_BYTES", 100)
    with pytest.raises(LivePreviewError) as response_error:
        _build(tmp_path / "small", release, track)
    assert response_error.value.code == "response_limit"
    assert response_error.value.status_code == 413


def test_oversized_state_falls_back_to_bounded_geometry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, track, project_path = _write_repo(tmp_path)
    document = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    _write_analysis(tmp_path, document)
    audio_reactive = _build(tmp_path, release, track)
    monkeypatch.setattr(
        video_live_preview,
        "MAX_RESPONSE_BYTES",
        len(audio_reactive.body) - 1,
    )

    fallback = _build(tmp_path, release, track)

    assert fallback.payload["mode"] == "geometry-only"
    assert fallback.payload["mode_reason"]["code"] == "state_payload_too_large"
    assert "state_samples_base64" not in fallback.payload
    assert len(fallback.body) < len(audio_reactive.body)


def test_private_data_route_returns_contract_headers_and_structured_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, track, project_path = _write_repo(tmp_path)
    document = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    _write_analysis(tmp_path, document)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        video_routes,
        "_context",
        lambda _root, slug: (
            {"release": release} if slug == "video-contract" else None
        ),
    )

    response = asyncio.run(
        video_routes.video_live_preview_data("video-contract", "private-track")
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["etag"].startswith('"')
    assert payload["format"] == "mrp-music-video-live-preview"
    assert payload["mode"] == "audio-reactive"

    missing = asyncio.run(
        video_routes.video_live_preview_data("missing", "private-track")
    )
    assert missing.status_code == 404
    assert json.loads(missing.body)["error"]["code"] == "release_not_found"

    monkeypatch.setattr(
        video_routes,
        "_context",
        lambda _root, _slug: {"release": release},
    )
    missing_track = asyncio.run(
        video_routes.video_live_preview_data("video-contract", "missing")
    )
    assert missing_track.status_code == 404
    assert json.loads(missing_track.body)["error"]["code"] == "track_not_found"


@pytest.mark.parametrize(
    ("missing_name", "expected_code"),
    [
        ("project.yaml", "project_missing"),
        ("lyrics.aligned.yaml", "timing_missing"),
    ],
)
def test_private_data_route_refuses_missing_saved_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
    expected_code: str,
) -> None:
    _release, _track, project_path = _write_repo(tmp_path)
    project_path.with_name(missing_name).unlink()
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_live_preview_data(
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["error"]["code"] == expected_code
    _assert_private_data_absent(response.body)


def test_full_track_page_is_private_read_only_and_linked_in_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release, _track, _project_path = _write_repo(tmp_path)
    before = _snapshot(tmp_path)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(video_routes.db, "get_latest_video_job", lambda *_args: None)

    page = asyncio.run(
        video_routes.video_live_preview(
            _get_request(
                "/releases/video-contract/tracks/private-track/video/live-preview"
            ),
            "video-contract",
            "private-track",
        )
    )
    body = page.body.decode()

    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store"
    assert "Full-track Live Preview" in body
    assert 'id="track-live-preview-canvas"' in body
    assert 'id="track-preview-scrubber"' in body
    assert 'id="track-preview-scenes"' in body
    assert 'id="track-preview-scene"' in body
    assert 'id="track-preview-lyric"' in body
    assert 'id="track-preview-performance"' in body
    assert 'aria-label="Preview position"' in body
    assert 'aria-label="Full-track preview transport"' in body
    assert "Render the" in body
    assert "/static/spiro-preview.js" in body
    assert "/static/video-live-preview.js" in body
    assert (
        'data-preview-url="/releases/video-contract/tracks/private-track/video/live-preview/data"'
        in body
    )

    workspace = asyncio.run(
        video_routes.video_track(
            _get_request("/releases/video-contract/tracks/private-track/video"),
            "video-contract",
            "private-track",
        )
    )
    workspace_body = workspace.body.decode()
    casting_link = "/video-contract/tracks/private-track/video/casting"
    preview_link = "/video-contract/tracks/private-track/video/live-preview"
    rendering_link = "/video-contract/tracks/private-track/video/rendering"
    assert workspace_body.index(casting_link) < workspace_body.index(preview_link)
    assert workspace_body.index(preview_link) < workspace_body.index(rendering_link)
    assert _snapshot(tmp_path) == before


def test_admin_without_video_imports_dispatches_to_isolated_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, track, _project_path = _write_repo(tmp_path)
    expected = _build(tmp_path, release, track)
    # That first build only produces a sentinel document; drop it so the
    # dispatch below is a real build rather than a memo hit.
    video_live_preview._DOCUMENT_MEMO.clear()
    calls: list[tuple[Path, str, str]] = []
    monkeypatch.setattr(
        video_live_preview,
        "_video_dependencies_available",
        lambda: False,
    )

    def isolated(root: Path, release_slug: str, track_slug: str):
        calls.append((root, release_slug, track_slug))
        return expected

    monkeypatch.setattr(video_live_preview, "_build_in_video_environment", isolated)

    result = _build(tmp_path, release, track)

    assert result is expected
    assert calls == [(tmp_path.resolve(), "video-contract", "private-track")]


def test_javascript_mapping_fixture_is_generated_from_canonical_python() -> None:
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "live-preview-mapping-v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    values = fixture["audio_state"]
    audio = AudioVisualState(
        **{
            role: SemanticSample(
                values[f"{role}_energy"],
                values[f"{role}_accent"],
            )
            for role in ("master", "drums", "bass", "vocals", "instruments")
        },
        spectral_centroid=values["spectral_centroid"],
    )
    choreography = ChoreographyState(
        section_id="chorus_1",
        section_type="chorus",
        section_label="Chorus",
        **{
            name: value
            for name, value in values.items()
            if name
            not in {
                "master_energy",
                "master_accent",
                "drums_energy",
                "drums_accent",
                "bass_energy",
                "bass_accent",
                "vocals_energy",
                "vocals_accent",
                "instruments_energy",
                "instruments_accent",
                "spectral_centroid",
                "visibility_master",
                "visibility_drums",
                "visibility_bass",
                "visibility_vocals",
                "visibility_instruments",
            }
        },
        role_visibility={
            role: values[f"visibility_{role}"]
            for role in ("master", "drums", "bass", "vocals", "instruments")
        },
    )
    for case in fixture["cases"]:
        preset = MappingPreset(
            name="fixture",
            description="Python-to-JavaScript parity fixture",
            **case["preset"],
        )
        actual = map_layer_state(
            VisualLayerConfig.model_validate(case["layer"]),
            audio,
            choreography,
            fixture["time_seconds"],
            preset,
            visibility_override=case["visibility_override"],
        )
        assert asdict(actual) == pytest.approx(case["expected"], abs=1e-12)


def test_text_traces_carry_renderer_phase_for_each_contour(tmp_path: Path) -> None:
    text_layer = _layer("title")
    text_layer["presentation"] = "filled_shape"
    text_layer["geometry"] = {
        "family": "text",
        "path_data": "M0 0 L1 0 L1 1 Z M2 0 L3 0 L3 1 Z",
        "samples": 128,
    }
    # Cast onto the scene rather than leaning on the old global-layer fallback:
    # an uncast scene now draws nothing.
    release, track, _project_path = _write_repo(
        tmp_path,
        visuals={"section_compositions": {"verse": {"traces": [text_layer]}}},
    )

    result = _build(tmp_path, release, track)
    trace = result.payload["compositions"]["type:verse"]["traces"][0]

    assert len(trace["phase_fractions"]) == 2
    assert trace["presentation"] == "filled_shape"
    assert trace["phase_fraction"] == trace["phase_fractions"][0]
    assert trace["phase_fractions"][0] != trace["phase_fractions"][1]


def test_text_phases_skip_subpaths_the_renderer_drops(tmp_path: Path) -> None:
    """A degenerate leading subpath must not shift every contour's phase.

    ``M5 5`` draws nothing, so ``_build_curves`` never keys a curve for it.
    Counting move commands instead would hand contour ``:0``'s phase to the
    dropped subpath and put every real contour one phase out of step.
    """
    text_layer = _layer("title")
    text_layer["geometry"] = {
        "family": "text",
        "path_data": "M5 5 M0 0 L1 0 L1 1 Z M2 0 L3 0 L3 1 Z",
        "samples": 128,
    }
    release, track, _project_path = _write_repo(
        tmp_path,
        visuals={"section_compositions": {"verse": {"traces": [text_layer]}}},
    )

    result = _build(tmp_path, release, track)
    composition = result.payload["compositions"]["type:verse"]
    trace = composition["traces"][0]
    seed = composition["casting"]["seed"]

    assert len(trace["phase_fractions"]) == 2
    # Through _phase_key rather than restating its namespacing rule here.
    assert trace["phase_fractions"] == [
        video_live_preview._phase_fraction(
            seed, video_live_preview._phase_key("type:verse", "title", 0)
        ),
        video_live_preview._phase_fraction(
            seed, video_live_preview._phase_key("type:verse", "title", 1)
        ),
    ]


def test_whole_second_track_duration_never_vetoes_aligned_timing(
    tmp_path: Path,
) -> None:
    """Release YAML durations are whole seconds and must not refuse a preview.

    A master that really runs 8.4s is recorded as ``'0:08'``, so treating that
    rounded value as the master length would reject timing the renderer
    accepts. Without preflight there is no measured duration to check against.
    """
    release, track, _project_path = _write_repo(tmp_path, duration="0:07")

    result = _build(tmp_path, release, track)

    assert result.payload["mode"] == "geometry-only"
    assert result.payload["duration_seconds"] == 8


def test_measured_duration_still_refuses_timing_beyond_the_master(
    tmp_path: Path,
) -> None:
    release, track, project_path = _write_repo(tmp_path)
    document = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    _write_analysis(tmp_path, document, duration=6)

    with pytest.raises(LivePreviewError) as error:
        _build(tmp_path, release, track)

    assert error.value.code == "timing_exceeds_duration"


def test_unchanged_sources_reuse_the_memoized_document(tmp_path: Path) -> None:
    release, track, project_path = _write_repo(tmp_path)
    first = _build(tmp_path, release, track)

    assert _build(tmp_path, release, track) is first

    value = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    value["project"]["video"]["background"] = "#202030"
    project_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    rebuilt = _build(tmp_path, release, track)

    assert rebuilt is not first
    assert rebuilt.payload["video"]["background"] == "#202030"


def test_matching_validator_revalidates_without_resending_the_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release, track, project_path = _write_repo(tmp_path)
    document = TrackProjectDocument.model_validate(
        yaml.safe_load(project_path.read_text(encoding="utf-8"))
    )
    _write_analysis(tmp_path, document)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        video_routes,
        "_context",
        lambda _root, slug: (
            {"release": release} if slug == "video-contract" else None
        ),
    )
    before = _snapshot(tmp_path)

    first = asyncio.run(
        video_routes.video_live_preview_data("video-contract", "private-track")
    )
    etag = first.headers["etag"]
    assert first.status_code == 200

    revalidated = asyncio.run(
        video_routes.video_live_preview_data(
            "video-contract",
            "private-track",
            etag,
        )
    )
    assert revalidated.status_code == 304
    assert revalidated.body == b""
    assert revalidated.headers["etag"] == etag

    superseded = asyncio.run(
        video_routes.video_live_preview_data(
            "video-contract",
            "private-track",
            '"an-older-revision"',
        )
    )
    assert superseded.status_code == 200
    assert superseded.body == first.body
    assert _snapshot(tmp_path) == before
