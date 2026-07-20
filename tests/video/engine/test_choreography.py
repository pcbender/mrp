from pathlib import Path

import numpy as np
import pytest

from mrp.video.analysis import (
    ANALYSIS_FEATURES,
    AnalysisBundle,
    FeatureTimeline,
    SemanticControl,
)
from mrp.video.choreography import ChoreographyState, choreography_at
from mrp.video.mappings import (
    AudioVisualState,
    SemanticSample,
    map_layer_state,
    sample_audio_visual_state,
)
from mrp.video.project import (
    AlignedLyricLine,
    AlignedLyrics,
    AlignedLyricSection,
    ProjectManifest,
)


def _aligned_sections() -> AlignedLyrics:
    return AlignedLyrics(
        version=1,
        source=Path("lyrics.yaml"),
        sections=[
            AlignedLyricSection(
                id="verse",
                type="verse",
                label="Verse",
                start=0,
                end=2,
                lines=[AlignedLyricLine(text="Verse line", start=0.2, end=1.8)],
            ),
            AlignedLyricSection(
                id="chorus",
                type="chorus",
                label="Chorus",
                start=2,
                end=4,
                lines=[AlignedLyricLine(text="Chorus line", start=2.2, end=3.8)],
            ),
            AlignedLyricSection(
                id="instrumental",
                type="instrumental",
                start=4,
                end=6,
                lines=[],
            ),
        ],
    )


def _analysis_bundle() -> AnalysisBundle:
    role_values = {
        "master": (0.4, 0.7),
        "drums": (0.5, 0.9),
        "bass": (0.8, 0.2),
        "vocals": (0.65, 0.75),
        "instruments": (0.55, 0.45),
    }
    tracks: dict[str, FeatureTimeline] = {}
    for role, (energy, accent) in role_values.items():
        values = {
            feature: np.asarray([energy, energy], dtype=np.float32)
            for feature in ANALYSIS_FEATURES
        }
        values["onset_strength"][:] = accent
        values["spectral_flux"][:] = accent
        values["vocal_activity"][:] = accent
        values["spectral_centroid"][:] = 0.6
        tracks[role] = FeatureTimeline(
            times=np.asarray([0, 6], dtype=np.float64),
            features=values,
            tempo_bpm=120,
            beat_times=np.asarray([0, 0.5, 1], dtype=np.float64),
        )
    return AnalysisBundle(
        cache_key="fixture",
        duration=6,
        sample_rate=8000,
        frame_length=512,
        hop_length=128,
        input_hashes={},
        tracks=tracks,
        semantic_controls={
            "master": SemanticControl("master", "rms", "onset_strength"),
            "drums": SemanticControl("drums", "rms", "onset_strength"),
            "bass": SemanticControl("bass", "rms", "spectral_flux"),
            "vocals": SemanticControl("vocals", "rms", "vocal_activity"),
            "instruments": SemanticControl(
                "instruments",
                "rms",
                "spectral_flux",
            ),
        },
    )


def test_section_choreography_interpolates_into_the_chorus() -> None:
    lyrics = _aligned_sections()

    verse = choreography_at(lyrics, 1, transition_seconds=0.5)
    chorus_start = choreography_at(lyrics, 2, transition_seconds=0.5)
    chorus = choreography_at(lyrics, 2.5, transition_seconds=0.5)
    instrumental = choreography_at(lyrics, 4.5, transition_seconds=0.5)

    assert verse.section_id == "verse"
    assert verse.layer_fraction == pytest.approx(0.58)
    assert chorus_start.layer_fraction == pytest.approx(verse.layer_fraction)
    assert chorus.transition_progress == 1
    assert chorus.layer_fraction == 1
    assert chorus.scale > verse.scale
    assert chorus.onset_response > verse.onset_response
    assert instrumental.lyrics_opacity == 0


def test_vocal_intro_and_outro_sections_keep_lyrics_visible() -> None:
    lyrics = AlignedLyrics(
        version=1,
        source=Path("lyrics.yaml"),
        sections=[
            AlignedLyricSection(
                id="intro",
                type="intro",
                start=0,
                end=1,
                lines=[AlignedLyricLine(text="Opening line", start=0.1, end=0.9)],
            ),
            AlignedLyricSection(
                id="outro",
                type="outro",
                start=1,
                end=2,
                lines=[AlignedLyricLine(text="Closing line", start=1.1, end=1.9)],
            ),
        ],
    )

    intro = choreography_at(lyrics, 0.5, transition_seconds=0)
    outro = choreography_at(lyrics, 1.5, transition_seconds=0)

    assert intro.lyrics_opacity == 1
    assert outro.lyrics_opacity == 1


def test_semantic_mapping_keeps_geometry_stable_and_modulates_style() -> None:
    project = ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Mapping Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "text": {"font": "font.ttf"},
        }
    )
    audio = sample_audio_visual_state(_analysis_bundle(), 1)
    chorus = ChoreographyState(
        section_id="chorus",
        section_type="chorus",
        section_label="Chorus",
        section_progress=0.5,
        transition_progress=1,
        layer_fraction=1,
        scale=1.08,
        motion=1.18,
        color_intensity=1.16,
        onset_response=1.35,
        rotation_direction=1,
        palette_shift=0,
        lyrics_opacity=1,
    )
    bass_layer = next(layer for layer in project.visuals.layers if layer.role == "bass")
    drums_layer = next(
        layer for layer in project.visuals.layers if layer.role == "drums"
    )

    bass = map_layer_state(bass_layer, audio, chorus, 1)
    drums = map_layer_state(drums_layer, audio, chorus, 1)

    assert bass.scale == pytest.approx(bass_layer.base_scale * 1.08 * 1.16)
    assert bass.opacity > 0
    assert drums.line_width > drums_layer.line_width * 2
    assert drums.opacity > 0
    assert drums.hue_shift_degrees > drums_layer.hue_shift_degrees


def test_sections_change_landscape_spread_without_collapsing_anchors() -> None:
    lyrics = _aligned_sections()
    verse = choreography_at(lyrics, 1, transition_seconds=0)
    chorus = choreography_at(lyrics, 2.5, transition_seconds=0)
    instrumental = choreography_at(lyrics, 4.5, transition_seconds=0)

    assert chorus.spatial_spread > verse.spatial_spread
    assert instrumental.spatial_spread >= chorus.spatial_spread
    assert verse.spatial_spread > 0


def test_manifest_section_type_and_id_settings_resolve_in_precedence_order() -> None:
    project = ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Section Style Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "text": {"font": "font.ttf"},
            "visuals": {
                "section_styles": {
                    "verse": {
                        "scale": 1.05,
                        "trace_speed": 0.5,
                        "beat_gain": 0.25,
                        "visible_roles": ["bass"],
                    }
                },
                "section_overrides": {
                    "verse": {"scale": 1.25, "trail_length": 1.4}
                },
            },
        }
    )

    state = choreography_at(
        _aligned_sections(),
        1,
        transition_seconds=0,
        visuals=project.visuals,
    )

    assert state.scale == 1.25
    assert state.trace_speed == 0.5
    assert state.trail_length == 1.4
    assert state.beat_gain == 0.25
    assert state.role_visibility["bass"] == 1
    assert state.role_visibility["vocals"] == 0


def test_section_transition_interpolates_without_trace_or_rotation_jump() -> None:
    project = ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Section Transition Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "text": {"font": "font.ttf"},
            "visuals": {
                "section_styles": {
                    "verse": {"trace_speed": 0.5, "motion": 0.4},
                    "chorus": {
                        "scale": 1.5,
                        "trace_speed": 1.8,
                        "motion": 1.6,
                    },
                }
            },
        }
    )
    lyrics = _aligned_sections()
    before = choreography_at(
        lyrics,
        1.999,
        transition_seconds=0.5,
        visuals=project.visuals,
    )
    boundary = choreography_at(
        lyrics,
        2,
        transition_seconds=0.5,
        visuals=project.visuals,
    )
    after = choreography_at(
        lyrics,
        2.001,
        transition_seconds=0.5,
        visuals=project.visuals,
    )
    midpoint = choreography_at(
        lyrics,
        2.25,
        transition_seconds=0.5,
        visuals=project.visuals,
    )

    assert boundary.scale == pytest.approx(before.scale, abs=0.01)
    assert 1.05 < midpoint.scale < 1.5
    assert 0 < boundary.trace_time - before.trace_time < 0.01
    assert 0 < after.trace_time - boundary.trace_time < 0.01
    assert abs(after.rotation_time - boundary.rotation_time) < 0.01


def test_trace_and_rotation_continue_through_unlabeled_section_gaps() -> None:
    lyrics = _aligned_sections().model_copy(deep=True)
    lyrics.sections[1].start = 3
    lyrics.sections[1].end = 5
    lyrics.sections[1].lines[0].start = 3.2
    lyrics.sections[1].lines[0].end = 4.8
    lyrics.sections[2].start = 5
    lyrics.sections[2].end = 7

    section_end = choreography_at(lyrics, 2, transition_seconds=0.5)
    gap_middle = choreography_at(lyrics, 2.5, transition_seconds=0.5)
    next_start = choreography_at(lyrics, 3, transition_seconds=0.5)

    assert gap_middle.section_id == "verse"
    assert gap_middle.trace_time > section_end.trace_time
    assert next_start.trace_time > gap_middle.trace_time
    assert gap_middle.rotation_time > section_end.rotation_time
    assert next_start.rotation_time > gap_middle.rotation_time


def test_percussion_flash_and_background_intensity_have_distinct_controls() -> None:
    project = ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Mapping Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "text": {"font": "font.ttf"},
        }
    )
    choreography = choreography_at(_aligned_sections(), 4.5, transition_seconds=0)
    quiet = AudioVisualState(
        master=SemanticSample(0.1, 0),
        drums=SemanticSample(0.2, 0.05),
        bass=SemanticSample(0.2, 0),
        vocals=SemanticSample(0.2, 0),
        instruments=SemanticSample(0.2, 0),
        spectral_centroid=0.3,
    )
    strong = AudioVisualState(
        master=SemanticSample(0.95, 0),
        drums=SemanticSample(0.8, 1),
        bass=SemanticSample(0.6, 0),
        vocals=SemanticSample(0.6, 0),
        instruments=SemanticSample(0.6, 0),
        spectral_centroid=0.6,
    )
    background = next(
        layer for layer in project.visuals.layers if layer.depth == "background"
    )
    drums = next(layer for layer in project.visuals.layers if layer.role == "drums")

    quiet_background = map_layer_state(background, quiet, choreography, 1)
    strong_background = map_layer_state(background, strong, choreography, 1)
    quiet_drums = map_layer_state(drums, quiet, choreography, 1)
    strong_drums = map_layer_state(drums, strong, choreography, 1)

    assert strong_background.opacity > quiet_background.opacity
    assert strong_background.color_intensity > quiet_background.color_intensity
    assert strong_drums.beat_pulse > 0.9
    assert quiet_drums.beat_pulse < 0.1
    assert quiet_background.beat_pulse == 0
