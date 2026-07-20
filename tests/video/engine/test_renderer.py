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
from mrp.video.project import ProjectManifest
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


def _project(*, seed: int = 4821) -> ProjectManifest:
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
    assert digest == "b94401ba693f046413208be2422c661defc3723d11b963302147ae77d5b5e68d"


def test_disabling_auto_casting_preserves_the_global_layer_renderer() -> None:
    project = _project()
    project = project.model_copy(
        update={"visuals": project.visuals.model_copy(update={"auto_casting": False})}
    )
    context = build_render_context(
        project,
        _analysis_bundle(),
        _aligned_sections(),
        root=FONT_PATH.parent,
    )

    frame = render_frame(context, 4.5, 45, width=320, height=180)
    digest = hashlib.sha256(frame.tobytes()).hexdigest()

    assert digest == "f2b468d6b4c36df4ee024f3f4cbfeb40e50c4a4a727605ab4387ba36a20c49e8"


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
        ("auto:verse", 1),
        ("auto:chorus", 0),
    ]
    assert [weight for _, weight in midpoint_casts] == pytest.approx([0.5, 0.5])
    assert [(cast.key, weight) for cast, weight in settled_casts] == [
        ("auto:chorus", 1),
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
