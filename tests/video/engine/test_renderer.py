import hashlib
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest
import soundfile as sf
import yaml
from typer.testing import CliRunner

from mrp.video.choreography import choreography_at
from mrp.video.cli import app
from mrp.video.project import ProjectManifest, load_project_manifest
from mrp.video.renderer import (
    SpirophonicRendererError,
    _weighted_compositions,
    build_render_context,
    plan_frame_range,
    render_dimensions,
    render_frame,
    render_frame_file,
    render_frame_sequence,
)
from mrp.video.text import lyric_cue_at
from tests.video.engine.test_choreography import _aligned_sections, _analysis_bundle

runner = CliRunner()
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _auto_composition(section_type: str, seed: int) -> dict:
    """The default look for a section type, as a stored composition.

    An uncast scene draws nothing now, so a renderer fixture has to say what it
    casts. Generating it keeps these tests on the same shapes they always used,
    while making the cast explicit rather than something the resolver supplied.
    """
    from mrp.video.casting import generate_auto_composition

    return generate_auto_composition(section_type, seed).model_dump(
        mode="json", exclude_none=True
    )


def _project(*, seed: int = 4821, cast: bool = True) -> ProjectManifest:
    return ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Render Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "video": {
                "width": 320,
                "height": 180,
                "fps": 10,
                "seed": seed,
            },
            "text": {"font": FONT_PATH.name, "size": 28},
            "visuals": {
                "section_compositions": {
                    "verse": _auto_composition("verse", seed),
                    "chorus": _auto_composition("chorus", seed),
                }
            }
            if cast
            else {},
        }
    )


def _context(*, seed: int = 4821):
    return build_render_context(
        _project(seed=seed),
        _analysis_bundle(),
        _aligned_sections(),
        root=FONT_PATH.parent,
    )


def _audio_signal(sample_rate: int, duration: float) -> np.ndarray:
    times = np.arange(round(sample_rate * duration)) / sample_rate
    return np.asarray(0.2 * np.sin(2 * np.pi * 220 * times), dtype=np.float32)


def _write_cli_project(root: Path) -> Path:
    project = {
        "version": 1,
        "title": "CLI Render Fixture",
        "audio": {
            "master": "audio/master.wav",
            "stems": {"vocals": "audio/vocals.wav"},
        },
        "lyrics": {
            "source": "lyrics.yaml",
            "aligned": "build/lyrics.aligned.yaml",
            "language": "en",
        },
        "cards": {
            "opening": {"file": "cards/opening.jpg", "duration": 1},
            "closing": {"file": "cards/closing.jpg", "duration": 1},
        },
        "video": {"width": 320, "height": 180, "fps": 10, "seed": 73},
        "text": {"font": "assets/font.ttf", "size": 28},
        "analysis": {
            "sample_rate": 8000,
            "frame_length": 512,
            "hop_length": 128,
            "low_cutoff_hz": 200,
            "high_cutoff_hz": 1500,
            "attack_seconds": 0.02,
            "release_seconds": 0.1,
            "cache_dir": "build/test-analysis",
        },
    }
    for relative in ("cards/opening.jpg", "cards/closing.jpg"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    font = root / "assets" / "font.ttf"
    font.parent.mkdir(parents=True)
    shutil.copyfile(FONT_PATH, font)
    (root / "lyrics.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sections": [
                    {
                        "id": "verse",
                        "type": "verse",
                        "label": "Verse",
                        "lines": [{"text": "Visible lyric line"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    aligned = root / "build" / "lyrics.aligned.yaml"
    aligned.parent.mkdir()
    aligned.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "source": "lyrics.yaml",
                "sections": [
                    {
                        "id": "verse",
                        "type": "verse",
                        "label": "Verse",
                        "start": 0,
                        "end": 1,
                        "lines": [
                            {
                                "text": "Visible lyric line",
                                "start": 0.1,
                                "end": 0.9,
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    audio = root / "audio"
    audio.mkdir()
    sf.write(audio / "master.wav", _audio_signal(8000, 1), 8000)
    sf.write(audio / "vocals.wav", _audio_signal(16000, 1), 16000)
    manifest = root / "project.yaml"
    manifest.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")
    return manifest


def test_lyric_cues_fade_and_instrumentals_hide_text() -> None:
    lyrics = _aligned_sections()
    verse_choreography = choreography_at(lyrics, 0.2, transition_seconds=0.5)
    beginning = lyric_cue_at(
        lyrics,
        0.2,
        fade_seconds=0.25,
        choreography_opacity=verse_choreography.lyrics_opacity,
    )
    visible = lyric_cue_at(
        lyrics,
        1,
        fade_seconds=0.25,
        choreography_opacity=1,
    )
    instrumental = lyric_cue_at(
        lyrics,
        4.5,
        fade_seconds=0.25,
        choreography_opacity=0,
    )

    assert beginning is not None and beginning.alpha == 0
    assert visible is not None and visible.alpha == 1
    assert visible.text == "Verse line"
    assert instrumental is None


def test_renderer_is_deterministic_and_seeded() -> None:
    context = _context()
    first = render_frame(context, 4.5, 45, width=320, height=180)
    second = render_frame(context, 4.5, 45, width=320, height=180)
    another_seed = render_frame(_context(seed=99), 4.5, 45, width=320, height=180)

    assert first.shape == (180, 320, 3)
    assert first.dtype == np.uint8
    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, another_seed)
    digest = hashlib.sha256(first.tobytes()).hexdigest()
    assert digest == "7f6a2d55423c30c8ed765217814696499c2f44af5ec3dbe4116441b0d411e94c"


def test_saved_exact_section_cast_reproduces_the_same_frame(tmp_path: Path) -> None:
    payload = _project().model_dump(mode="json", exclude_none=True)
    payload["visuals"]["composition_overrides"] = {
        "instrumental": {
            "casting": {"source": "manual", "seed": 4821},
            "traces": [
                {
                    "id": "saved-hero",
                    "role": "bass",
                    "geometry": {
                        "fixed_radius": 310,
                        "moving_radius": 47,
                        "pen_offset": 221,
                        "rotation": "outside",
                        "samples": 1600,
                    },
                    "trace": {
                        "cycles_per_second": 0.031,
                        "trail_fraction": 0.61,
                        "ghost_count": 3,
                    },
                    "color": "#4c78ff",
                    "anchor_x": 0.31,
                    "anchor_y": 0.42,
                    "base_scale": 1.7,
                }
            ],
        }
    }
    path = tmp_path / "saved-project.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    loaded = load_project_manifest(path)
    context = build_render_context(
        loaded,
        _analysis_bundle(),
        _aligned_sections(),
        root=FONT_PATH.parent,
    )

    first = render_frame(context, 4.5, 45, width=320, height=180)
    second = render_frame(context, 4.5, 45, width=320, height=180)

    assert context.section_compositions["instrumental"].key == "section:instrumental"
    assert context.section_compositions["instrumental"].layers[0].config.id == "saved-hero"
    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, render_frame(_context(), 4.5, 45, width=320, height=180))


def test_an_uncast_scene_renders_the_background_alone() -> None:
    """No cast, no shapes.

    A scene used to fill itself in from the deterministic look, or from the
    global layer list when auto-casting was off, so a video showed shapes its
    author never chose. Neither stands in for a cast now, so the frame is the
    background and nothing else.
    """
    for auto_casting in (True, False):
        project = _project(cast=False)
        project = project.model_copy(
            update={
                "visuals": project.visuals.model_copy(
                    update={"auto_casting": auto_casting}
                )
            }
        )
        assert project.visuals.layers, "fixture keeps global layers to fall back to"

        context = build_render_context(
            project,
            _analysis_bundle(),
            _aligned_sections(),
            root=FONT_PATH.parent,
        )
        frame = render_frame(context, 4.5, 45, width=320, height=180)

        colors = np.unique(frame.reshape(-1, frame.shape[-1]), axis=0)
        assert len(colors) == 1, f"auto_casting={auto_casting} drew {len(colors)} colors"


def test_render_context_builds_and_crossfades_distinct_section_casts() -> None:
    context = _context()

    assert [
        layer.config.id for layer in context.section_compositions["verse"].layers
    ] == ["verse-orbit", "verse-bloom"]
    assert len(context.section_compositions["chorus"].layers) == 3
    assert context.section_compositions["verse"].key != (
        context.section_compositions["chorus"].key
    )

    boundary = choreography_at(
        context.lyrics,
        2,
        transition_seconds=context.project.visuals.transition_seconds,
        visuals=context.project.visuals,
    )
    midpoint = choreography_at(
        context.lyrics,
        2 + context.project.visuals.transition_seconds / 2,
        transition_seconds=context.project.visuals.transition_seconds,
        visuals=context.project.visuals,
    )
    settled = choreography_at(
        context.lyrics,
        2 + context.project.visuals.transition_seconds,
        transition_seconds=context.project.visuals.transition_seconds,
        visuals=context.project.visuals,
    )

    boundary_casts = _weighted_compositions(context, boundary)
    midpoint_casts = _weighted_compositions(context, midpoint)
    settled_casts = _weighted_compositions(context, settled)

    assert [(cast.key, weight) for cast, weight in boundary_casts] == [
        ("type:verse", 1),
        ("type:chorus", 0),
    ]
    assert [weight for _, weight in midpoint_casts] == pytest.approx([0.5, 0.5])
    assert [(cast.key, weight) for cast, weight in settled_casts] == [
        ("type:chorus", 1),
    ]


def test_active_section_uses_all_three_landscape_regions() -> None:
    frame = render_frame(_context(), 4.5, 45, width=320, height=180)
    background = frame[0, 0]
    active = np.any(frame != background, axis=2)
    thirds = np.array_split(active, 3, axis=1)

    assert all(np.count_nonzero(third) > 40 for third in thirds)


def test_draft_and_time_range_share_absolute_song_time() -> None:
    project = _project()
    full = render_dimensions(project, draft=False)
    draft = render_dimensions(project, draft=True)
    plan = plan_frame_range(
        project,
        6,
        start_seconds=1.01,
        end_seconds=1.41,
        draft=True,
    )

    assert full == (320, 180, 10)
    assert draft == full
    assert plan.start_frame == 11
    assert plan.end_frame == 15
    assert plan.start_time == pytest.approx(1.1)
    assert plan.frame_count == 4

    large_project = project.model_copy(
        update={
            "video": project.video.model_copy(
                update={"width": 1920, "height": 1080, "fps": 30}
            )
        }
    )
    assert render_dimensions(large_project, draft=True) == (960, 540, 15)


def test_preview_and_bounded_sequence_outputs_are_safe(tmp_path: Path) -> None:
    context = _context()
    preview = tmp_path / "preview.png"
    result = render_frame_file(context, preview, time_seconds=4.5)

    assert result.output_path == preview
    decoded = cv2.imread(str(preview))
    assert decoded is not None and decoded.shape == (180, 320, 3)
    with pytest.raises(SpirophonicRendererError, match="--force"):
        render_frame_file(context, preview, time_seconds=4.5)

    plan = plan_frame_range(
        context.project,
        context.analysis.duration,
        start_seconds=4,
        end_seconds=4.2,
    )
    sequence = render_frame_sequence(context, tmp_path / "sequence", plan)
    metadata = json.loads(
        (sequence.output_path / "frames.json").read_text(encoding="utf-8")
    )
    assert metadata["format"] == "spirophonic-frame-sequence"
    assert metadata["frame_count"] == 2
    assert len(list(sequence.output_path.glob("frame-*.png"))) == 2
    with pytest.raises(SpirophonicRendererError, match="--force"):
        render_frame_sequence(context, sequence.output_path, plan)
    render_frame_sequence(context, sequence.output_path, plan, force=True)

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    protected = foreign / "keep.txt"
    protected.write_text("do not replace", encoding="utf-8")
    with pytest.raises(SpirophonicRendererError, match="non-Spirophonic"):
        render_frame_sequence(context, foreign, plan, force=True)
    assert protected.read_text(encoding="utf-8") == "do not replace"


@pytest.mark.skipif(not FONT_PATH.is_file(), reason="target Ubuntu font unavailable")
def test_frame_cli_renders_an_inspectable_png(tmp_path: Path) -> None:
    manifest = _write_cli_project(tmp_path)
    output = tmp_path / "inspect.png"

    result = runner.invoke(
        app,
        [
            "frame",
            str(manifest),
            "--time",
            "0.5",
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["output_path"] == str(output)
    assert summary["time_seconds"] == 0.5
    assert output.is_file()


def test_build_curve_honors_geometry_phase() -> None:
    from mrp.video.project import VisualLayerConfig
    from mrp.video.renderer import _build_curve

    base = {
        "id": "phase-probe",
        "role": "vocals",
        "color": "#ffffff",
        "geometry": {
            "fixed_radius": 120,
            "moving_radius": 45,
            "pen_offset": 60,
            "samples": 128,
        },
    }
    plain = _build_curve(VisualLayerConfig.model_validate(base), 7)
    shifted = _build_curve(
        VisualLayerConfig.model_validate(
            base | {"geometry": base["geometry"] | {"phase": 1.25}}
        ),
        7,
    )
    # Phase rotates the sampled curve, so the point cloud must move while the
    # normalization extent stays comparable.
    assert not np.allclose(plain.points, shifted.points)


def test_build_curve_precomputes_color_flow_values_only_when_configured() -> None:
    from mrp.video.project import VisualLayerConfig
    from mrp.video.renderer import _build_curve

    base = {
        "id": "flow-probe",
        "role": "vocals",
        "color": "#ff5fd2",
        "geometry": {
            "fixed_radius": 120,
            "moving_radius": 45,
            "pen_offset": 60,
            "samples": 128,
        },
    }
    solid = _build_curve(VisualLayerConfig.model_validate(base), 7)
    assert solid.hue_values is None

    flowing = _build_curve(
        VisualLayerConfig.model_validate(
            base | {"color_flow": {"source": "radius", "swing_degrees": 90}}
        ),
        7,
    )
    assert flowing.hue_values is not None
    assert len(flowing.hue_values) == 128
    assert float(flowing.hue_values.min()) >= 0
    assert float(flowing.hue_values.max()) <= 1


def test_composite_trace_color_flow_varies_hue_deterministically() -> None:
    from mrp.video.renderer import _composite_trace, _layer_color

    xs = np.linspace(10, 110, 24)
    points = (
        np.stack([xs, np.full(24, 30.0)], axis=1)
        .round()
        .astype(np.int32)
        .reshape((-1, 1, 2))
    )
    values = np.linspace(0, 1, 24, dtype=np.float32)
    kwargs = {
        "color": _layer_color("#ff5fd2", 0, 1),
        "opacity": 1.0,
        "line_width": 3.0,
        "blend_mode": "normal",
        "head_radius": 0.0,
    }
    frame = np.zeros((60, 120, 3), dtype=np.uint8)

    def flow_color(value: float) -> tuple[int, int, int]:
        return _layer_color("#ff5fd2", (value - 0.5) * 240, 1)

    solid = _composite_trace(frame, ((points, 1.0, None),), **kwargs)
    flowing = _composite_trace(
        frame,
        ((points, 1.0, values),),
        **kwargs,
        color_for_value=flow_color,
    )
    repeat = _composite_trace(
        frame,
        ((points, 1.0, values),),
        **kwargs,
        color_for_value=flow_color,
    )

    # The hue sweeps along the stroke: at equal trail fade, flow pixels must
    # disagree with the solid render at both ends, deterministically. (The
    # solid ends differ from each other too — that is the fading trail.)
    assert not np.array_equal(solid, flowing)
    assert not np.array_equal(flowing[30, 20], solid[30, 20])
    assert not np.array_equal(flowing[30, 100], solid[30, 100])
    assert np.array_equal(flowing, repeat)


def test_build_curve_supports_non_spirogram_families() -> None:
    from mrp.video.project import VisualLayerConfig
    from mrp.video.renderer import _build_curve

    layer = VisualLayerConfig.model_validate(
        {
            "id": "liss-probe",
            "role": "vocals",
            "color": "#5fd2ff",
            "geometry": {"family": "lissajous", "liss_freq_x": 3, "liss_freq_y": 2, "samples": 128},
            "color_flow": {"source": "velocity", "swing_degrees": 90},
        }
    )
    curve = _build_curve(layer, 7)
    assert curve.points.shape == (128, 2)
    assert float(np.max(np.linalg.norm(curve.points, axis=1))) == pytest.approx(1.0)
    assert curve.hue_values is not None and len(curve.hue_values) == 128

    harmonograph = _build_curve(
        VisualLayerConfig.model_validate(
            {
                "id": "harm-probe",
                "role": "vocals",
                "color": "#5fd2ff",
                "geometry": {"family": "harmonograph", "samples": 128},
            }
        ),
        7,
    )
    # Ping-pong closure: forward = samples // 2 + 1 stations, palindromed.
    assert harmonograph.points.shape == (129, 2)
    assert float(np.max(np.linalg.norm(harmonograph.points, axis=1))) == pytest.approx(1.0)
    assert np.array_equal(harmonograph.points[0], harmonograph.points[-1])


def test_build_curve_supports_path_family_deterministically() -> None:
    import hashlib

    from mrp.video.project import VisualLayerConfig
    from mrp.video.renderer import _build_curve

    layer = VisualLayerConfig.model_validate(
        {
            "id": "path-probe",
            "role": "vocals",
            "color": "#f1d36b",
            "geometry": {
                "family": "path",
                "path_data": "M 0 0 L 10 0 L 10 10 L 0 10 Z",
                "samples": 128,
            },
        }
    )
    curve = _build_curve(layer, 7)
    repeat = _build_curve(layer, 7)

    assert curve.points.shape == (128, 2)
    assert float(np.max(np.linalg.norm(curve.points, axis=1))) == pytest.approx(1.0)
    assert np.array_equal(curve.points, repeat.points)
    # Line-segment paths interpolate exactly, so the sampled bytes are a
    # stable probe digest for the whole path pipeline.
    digest = hashlib.sha256(curve.points.tobytes()).hexdigest()
    assert digest == hashlib.sha256(repeat.points.tobytes()).hexdigest()


def test_directed_wardrobe_color_outranks_the_production_palette() -> None:
    """A palette dresses actors that took no wardrobe note; it never overrules one."""
    from types import SimpleNamespace

    from mrp.video.presets import get_palette_preset
    from mrp.video.project import VisualConfig, VisualLayerConfig
    from mrp.video.renderer import _base_layer_color

    def layer(color: str, locked: bool) -> VisualLayerConfig:
        return VisualLayerConfig.model_validate(
            {
                "id": "mark",
                "role": "vocals",
                "geometry": {
                    "fixed_radius": 180,
                    "moving_radius": 40,
                    "pen_offset": 80,
                },
                "color": color,
                "color_locked": locked,
            }
        )

    context = SimpleNamespace(
        project=SimpleNamespace(visuals=VisualConfig.model_validate({})),
        palette_preset=get_palette_preset("aurora"),
    )

    assert _base_layer_color(context, layer("#ffffff", False), 0) == "#ff5fd2"
    assert _base_layer_color(context, layer("#ff0000", True), 0) == "#ff0000"
