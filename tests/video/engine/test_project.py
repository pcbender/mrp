from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from mrp.video.project import (
    AlignedLyricLine,
    AlignedLyricSection,
    LyricLine,
    ProjectManifest,
    SpirophonicValidationError,
    load_aligned_lyrics,
    validate_project,
)


def test_timing_review_markers_are_optional_and_structure_tags_are_not_cues() -> None:
    line = AlignedLyricLine(
        text="A displayed lyric",
        start=0,
        end=1,
        confidence=0.5,
        status="uncertain",
    )
    section = AlignedLyricSection(
        id="verse",
        type="verse",
        start=0,
        end=1,
        lines=[line],
    )

    assert line.reviewed is None
    assert section.reviewed is None
    with pytest.raises(ValidationError, match="section labels"):
        LyricLine(text="[Verse]")


def _valid_project() -> dict[str, Any]:
    return {
        "version": 1,
        "title": "Fixture Song",
        "audio": {
            "master": "audio/master.wav",
            "stems": {
                "vocals": "audio/vocals.wav",
                "drums": "audio/drums.wav",
            },
        },
        "lyrics": {
            "source": "lyrics.yaml",
            "aligned": "build/lyrics.aligned.yaml",
            "language": "en",
        },
        "cards": {
            "opening": {
                "file": "cards/opening.jpg",
                "duration": 3,
                "fit": "contain",
                "fade": 0.5,
            },
            "closing": {
                "file": "cards/closing.jpg",
                "duration": 4,
                "fit": "contain",
                "fade": 0.75,
            },
        },
        "video": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "background": "#101014",
            "seed": 4821,
        },
        "text": {
            "font": "assets/lyrics-font.ttf",
            "size": 60,
            "position": "bottom",
            "active_color": "#ffffff",
        },
    }


def _write_valid_inputs(root: Path, project: dict[str, Any]) -> Path:
    files = [
        "audio/master.wav",
        "audio/vocals.wav",
        "audio/drums.wav",
        "cards/opening.jpg",
        "cards/closing.jpg",
        "assets/lyrics-font.ttf",
    ]
    for relative in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    (root / "lyrics.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sections": [
                    {
                        "id": "verse_1",
                        "type": "verse",
                        "label": "Verse 1",
                        "lines": [{"text": "First line"}],
                    },
                    {
                        "id": "instrumental_1",
                        "type": "instrumental",
                        "lines": [],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    manifest = root / "project.yaml"
    manifest.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")
    return manifest


def test_valid_project_resolves_required_inputs(tmp_path: Path) -> None:
    manifest = _write_valid_inputs(tmp_path, _valid_project())

    report = validate_project(manifest, require_tools=False, probe_media=False)

    assert report.project.title == "Fixture Song"
    assert [section.id for section in report.lyrics.sections] == [
        "verse_1",
        "instrumental_1",
    ]
    assert report.master_duration == 0


def test_missing_required_input_is_reported(tmp_path: Path) -> None:
    manifest = _write_valid_inputs(tmp_path, _valid_project())
    (tmp_path / "cards" / "closing.jpg").unlink()

    with pytest.raises(SpirophonicValidationError, match="cards.closing.file"):
        validate_project(manifest, require_tools=False, probe_media=False)


def test_absolute_project_paths_are_rejected(tmp_path: Path) -> None:
    project = _valid_project()
    project["audio"]["master"] = "/tmp/master.wav"
    manifest = _write_valid_inputs(tmp_path, project)

    with pytest.raises(SpirophonicValidationError, match="must be relative"):
        validate_project(manifest, require_tools=False, probe_media=False)


def test_video_dimensions_must_support_yuv420p(tmp_path: Path) -> None:
    project = _valid_project()
    project["video"]["width"] = 1919
    manifest = _write_valid_inputs(tmp_path, project)

    with pytest.raises(SpirophonicValidationError, match="must be even"):
        validate_project(manifest, require_tools=False, probe_media=False)


def test_duplicate_lyric_section_ids_are_rejected(tmp_path: Path) -> None:
    manifest = _write_valid_inputs(tmp_path, _valid_project())
    lyrics_path = tmp_path / "lyrics.yaml"
    lyrics = yaml.safe_load(lyrics_path.read_text(encoding="utf-8"))
    lyrics["sections"].append(lyrics["sections"][0])
    lyrics_path.write_text(yaml.safe_dump(lyrics), encoding="utf-8")

    with pytest.raises(SpirophonicValidationError, match="section ids must be unique"):
        validate_project(manifest, require_tools=False, probe_media=False)


def test_duplicate_visual_layer_ids_are_rejected(tmp_path: Path) -> None:
    project = _valid_project()
    layer = {
        "id": "same-layer",
        "role": "vocals",
        "geometry": {
            "fixed_radius": 180,
            "moving_radius": 65,
            "pen_offset": 95,
        },
        "color": "#ff5fd2",
    }
    project["visuals"] = {"layers": [layer, layer]}
    manifest = _write_valid_inputs(tmp_path, project)

    with pytest.raises(SpirophonicValidationError, match="visual layer ids"):
        validate_project(manifest, require_tools=False, probe_media=False)


def test_unknown_artistic_preset_is_rejected(tmp_path: Path) -> None:
    project = _valid_project()
    project["visuals"] = {"mapping_preset": "maximum-chaos"}
    manifest = _write_valid_inputs(tmp_path, project)

    with pytest.raises(SpirophonicValidationError, match="mapping_preset"):
        validate_project(manifest, require_tools=False, probe_media=False)


def test_default_visual_layout_has_three_distributed_foreground_systems() -> None:
    project = _valid_project()
    manifest = ProjectManifest.model_validate(project)
    foreground = [
        layer for layer in manifest.visuals.layers if layer.depth == "foreground"
    ]
    background = [
        layer for layer in manifest.visuals.layers if layer.depth == "background"
    ]

    assert len(foreground) == 3
    assert [layer.role for layer in foreground] == ["bass", "vocals", "drums"]
    anchors = [layer.anchor_x for layer in foreground]
    assert anchors == sorted(anchors)
    assert anchors[1] - anchors[0] >= 0.3
    assert anchors[2] - anchors[1] >= 0.3
    assert len(background) == 1
    assert background[0].role == "instruments"


def test_section_visual_settings_are_validated() -> None:
    project = _valid_project()
    project["visuals"] = {
        "section_styles": {
            "verse": {
                "visible_roles": ["vocals", "instruments"],
                "scale": 0.9,
                "trace_speed": 0.8,
                "trail_length": 0.7,
                "beat_gain": 0.5,
                "intensity_gain": 0.8,
            }
        },
        "section_overrides": {"final_chorus": {"beat_gain": 1.7}},
    }

    manifest = ProjectManifest.model_validate(project)

    assert manifest.visuals.section_styles["verse"].trace_speed == 0.8
    assert manifest.visuals.section_overrides["final_chorus"].beat_gain == 1.7


def test_section_visual_settings_reject_ambiguous_or_duplicate_roles() -> None:
    project = _valid_project()
    project["visuals"] = {
        "section_styles": {
            "Verse": {"visible_roles": ["vocals"]},
            "verse": {"visible_roles": ["vocals"]},
        }
    }
    with pytest.raises(ValidationError, match="section style names"):
        ProjectManifest.model_validate(project)

    project["visuals"] = {
        "section_styles": {
            "verse": {"visible_roles": ["vocals", "vocals"]},
        }
    }
    with pytest.raises(ValidationError, match="visible_roles"):
        ProjectManifest.model_validate(project)


def test_section_compositions_validate_casting_traces_and_audio_drivers() -> None:
    project = _valid_project()
    project["visuals"] = {
        "section_compositions": {
            "bridge": {
                "casting": {
                    "source": "ai",
                    "seed": 73,
                    "generator_version": 2,
                },
                "traces": [
                    {
                        "id": "hero-flower",
                        "role": "vocals",
                        "geometry": {
                            "fixed_radius": 240,
                            "moving_radius": 80,
                            "pen_offset": 180,
                        },
                        "color": "#ff5fd2",
                        "base_scale": 1.6,
                        "drivers": {
                            "scale": "bass.energy",
                            "opacity": "master.energy",
                            "color": "vocals.energy",
                            "pulse": "drums.accent",
                        },
                    }
                ],
            }
        }
    }

    manifest = ProjectManifest.model_validate(project)
    bridge = manifest.visuals.section_compositions["bridge"]

    assert bridge.casting.source == "ai"
    assert bridge.casting.generator_version == 2
    assert bridge.traces[0].drivers.opacity == "master.energy"


def test_section_compositions_reject_duplicates_and_unknown_signals() -> None:
    project = _valid_project()
    trace = {
        "id": "same-trace",
        "role": "vocals",
        "geometry": {
            "fixed_radius": 180,
            "moving_radius": 60,
            "pen_offset": 100,
        },
        "color": "#ff5fd2",
    }
    project["visuals"] = {
        "section_compositions": {
            "Bridge": {"traces": [trace]},
            "bridge": {"traces": [trace]},
        }
    }
    with pytest.raises(ValidationError, match="composition names"):
        ProjectManifest.model_validate(project)

    project["visuals"] = {
        "section_compositions": {
            "bridge": {"traces": [trace, trace]},
        }
    }
    with pytest.raises(ValidationError, match="composition trace ids"):
        ProjectManifest.model_validate(project)

    trace["drivers"] = {"opacity": "guitar.energy"}
    project["visuals"] = {
        "section_compositions": {"bridge": {"traces": [trace]}},
    }
    with pytest.raises(ValidationError, match="drivers.opacity"):
        ProjectManifest.model_validate(project)


def test_aligned_lyrics_reject_overlapping_lines(tmp_path: Path) -> None:
    aligned_path = tmp_path / "lyrics.aligned.yaml"
    aligned_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "source": "lyrics.yaml",
                "sections": [
                    {
                        "id": "verse_1",
                        "type": "verse",
                        "start": 1.0,
                        "end": 5.0,
                        "lines": [
                            {"text": "One", "start": 1.0, "end": 3.0},
                            {"text": "Two", "start": 2.5, "end": 5.0},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SpirophonicValidationError, match="non-overlapping"):
        load_aligned_lyrics(aligned_path)


def test_stem_duration_must_match_master(tmp_path: Path) -> None:
    manifest = _write_valid_inputs(tmp_path, _valid_project())
    durations = {
        "master.wav": 30.0,
        "vocals.wav": 30.02,
        "drums.wav": 30.2,
    }

    def probe(path: Path, _ffprobe: str) -> float:
        return durations[path.name]

    with pytest.raises(SpirophonicValidationError, match="drums.*0.200s"):
        validate_project(
            manifest,
            require_tools=False,
            probe_media=True,
            duration_probe=probe,
        )
