from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from mrp.video.analysis import (
    ANALYSIS_FEATURES,
    AnalysisBundle,
    FeatureTimeline,
    SemanticControl,
)
from mrp.video.choreography import (
    ChoreographyState,
    _ease,
    _ease_integral,
    choreography_at,
    scene_settle_seconds,
)
from mrp.video.mappings import (
    AudioVisualState,
    SemanticSample,
    map_layer_state,
    sample_audio_visual_state,
)
from mrp.video.presets import get_mapping_preset
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

    assert bass.scale == pytest.approx(bass_layer.base_scale * 1.08 * 1.28)
    assert bass.opacity > 0
    assert drums.line_width > drums_layer.line_width * 2
    assert drums.opacity > 0
    assert drums.hue_shift_degrees > drums_layer.hue_shift_degrees


def test_rotation_and_explicit_wobble_are_independent_and_default_still() -> None:
    project = ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Wobble Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "text": {"font": "font.ttf"},
        }
    )
    sample = SemanticSample(0.5, 0)
    audio = AudioVisualState(
        master=sample,
        drums=sample,
        bass=sample,
        vocals=sample,
        instruments=sample,
        spectral_centroid=0.5,
    )
    choreography = ChoreographyState(
        section_id="intro",
        section_type="intro",
        section_label="Intro",
        section_progress=0.5,
        transition_progress=1,
        layer_fraction=1,
        scale=1,
        motion=0,
        color_intensity=1,
        onset_response=0,
        rotation_direction=1,
        palette_shift=0,
        lyrics_opacity=1,
    )
    component = project.visuals.layers[0].model_copy(
        update={"rotation_degrees_per_second": 0}
    )

    still = map_layer_state(component, audio, choreography, 0)
    wobble_only = map_layer_state(
        component.model_copy(update={"rotation_wobble_degrees": 12}),
        audio,
        choreography,
        0,
    )
    rotate_and_wobble = map_layer_state(
        component.model_copy(
            update={
                "rotation_degrees_per_second": 3,
                "rotation_wobble_degrees": 12,
            }
        ),
        audio,
        replace(choreography, rotation_time=2),
        0,
    )

    assert still.rotation_radians == 0
    assert wobble_only.rotation_radians == pytest.approx(np.radians(12))
    assert rotate_and_wobble.rotation_radians > wobble_only.rotation_radians


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


def _transition_project(visuals: dict) -> ProjectManifest:
    return ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Scene Transition Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "text": {"font": "font.ttf"},
            "visuals": visuals,
        }
    )


def test_scene_transition_seconds_override_only_the_scene_that_sets_them() -> None:
    project = _transition_project(
        {"section_transitions": {"chorus": {"seconds": 2}}}
    )
    lyrics = _aligned_sections()

    chorus = choreography_at(
        lyrics,
        2.25,
        transition_seconds=0.5,
        visuals=project.visuals,
    )
    instrumental = choreography_at(
        lyrics,
        4.25,
        transition_seconds=0.5,
        visuals=project.visuals,
    )

    # A quarter second into a two second transition, against half of a half
    # second one for the scene that took no note.
    assert chorus.transition_progress == pytest.approx(_ease("smooth", 0.125))
    assert instrumental.transition_progress == pytest.approx(_ease("smooth", 0.5))


def test_exact_scene_transition_beats_the_type_which_beats_the_track() -> None:
    project = _transition_project(
        {
            "section_transitions": {"chorus": {"seconds": 2}},
            "transition_overrides": {"chorus": {"seconds": 0}},
        }
    )

    chorus = choreography_at(
        _aligned_sections(),
        2.001,
        transition_seconds=0.5,
        visuals=project.visuals,
    )

    assert chorus.transition_progress == 1


@pytest.mark.parametrize(
    ("curve", "expected"),
    [
        ("linear", 0.5),
        ("smooth", 0.5),
        ("ease_in", 0.25),
        ("ease_out", 0.75),
    ],
)
def test_each_transition_curve_shapes_the_midpoint_of_the_change(
    curve: str,
    expected: float,
) -> None:
    project = _transition_project(
        {"section_transitions": {"chorus": {"seconds": 0.5, "curve": curve}}}
    )

    midpoint = choreography_at(
        _aligned_sections(),
        2.25,
        transition_seconds=0.5,
        visuals=project.visuals,
    )

    assert midpoint.transition_progress == pytest.approx(expected)


def test_a_cut_arrives_whole_however_long_the_track_default_is() -> None:
    project = _transition_project(
        {"section_transitions": {"chorus": {"curve": "cut"}}}
    )
    lyrics = _aligned_sections()

    boundary = choreography_at(
        lyrics,
        2.001,
        transition_seconds=4,
        visuals=project.visuals,
    )
    before = choreography_at(
        lyrics,
        1.999,
        transition_seconds=4,
        visuals=project.visuals,
    )

    assert boundary.transition_progress == 1
    assert boundary.scale > before.scale


def _gapped_sections() -> AlignedLyrics:
    """The verse ends at 1.5 but the chorus does not start until 2.0."""
    lyrics = _aligned_sections().model_copy(deep=True)
    lyrics.sections[0].end = 1.5
    lyrics.sections[0].lines[0].end = 1.4
    return lyrics


def test_a_gap_is_covered_by_the_arriving_scene_without_being_asked() -> None:
    """Alignment gaps are the norm, so covering one is the default."""
    lyrics = _gapped_sections()

    for time in (1.6, 1.8, 1.99):
        state = choreography_at(lyrics, time, transition_seconds=0.5)
        assert state.section_id == "chorus"
        assert 0 < state.transition_progress < 1


def test_hold_opts_a_scene_out_of_covering_its_gap() -> None:
    project = _transition_project(
        {"section_transitions": {"chorus": {"gap": "hold"}}}
    )
    lyrics = _gapped_sections()

    for time in (1.6, 1.8, 1.99):
        state = choreography_at(
            lyrics, time, transition_seconds=0.5, visuals=project.visuals
        )
        assert state.section_id == "verse"
        assert state.transition_progress == 1


def test_scenes_that_merely_touch_are_left_alone_by_the_default() -> None:
    """A rounding-width hole is not dead air; it must not move the transition."""
    lyrics = _aligned_sections().model_copy(deep=True)
    lyrics.sections[0].end = 1.98  # 20ms short of the chorus, under the epsilon

    boundary = choreography_at(lyrics, 1.99, transition_seconds=0.5)

    assert boundary.section_id == "verse"
    assert boundary.transition_progress == 1


def test_a_spanning_transition_covers_the_whole_gap_and_lands_on_the_scene() -> None:
    project = _transition_project(
        {"section_transitions": {"chorus": {"seconds": 0.2, "gap": "span"}}}
    )
    lyrics = _gapped_sections()

    def progress(time: float) -> float:
        return choreography_at(
            lyrics,
            time,
            transition_seconds=0.5,
            visuals=project.visuals,
        ).transition_progress

    # The gap runs 1.5 -> 2.0, so it outranks the configured 0.2s: the change
    # starts the instant the verse ends and arrives exactly at the chorus.
    assert choreography_at(
        lyrics, 1.6, transition_seconds=0.5, visuals=project.visuals
    ).section_id == "chorus"
    assert progress(1.5) == pytest.approx(0)
    assert progress(1.75) == pytest.approx(_ease("smooth", 0.5))
    assert progress(2.0) == pytest.approx(1)
    assert progress(1.6) < progress(1.75) < progress(1.9)


def test_an_early_transition_arrives_and_then_plays_out_the_rest_of_the_gap() -> None:
    project = _transition_project(
        {"section_transitions": {"chorus": {"seconds": 0.2, "gap": "early"}}}
    )
    lyrics = _gapped_sections()

    states = {
        time: choreography_at(
            lyrics,
            time,
            transition_seconds=0.5,
            visuals=project.visuals,
        )
        for time in (1.5, 1.6, 1.8, 2.4)
    }

    assert states[1.5].transition_progress == pytest.approx(0)
    assert 0 < states[1.6].transition_progress < 1
    # Arrived after its own 0.2s, with most of the gap still to play.
    assert states[1.8].transition_progress == pytest.approx(1)
    assert states[2.4].transition_progress == pytest.approx(1)
    assert all(state.section_id == "chorus" for state in states.values())


def test_a_touching_scene_settles_only_after_its_transition_has_played() -> None:
    """The frame at a butted scene's start still belongs to the scene before."""
    lyrics = _aligned_sections()  # contiguous: verse ends exactly at chorus start

    settle = scene_settle_seconds(lyrics, 1, transition_seconds=0.5)

    assert settle == pytest.approx(2.5)
    assert choreography_at(
        lyrics, lyrics.sections[1].start, transition_seconds=0.5
    ).transition_progress == pytest.approx(0)
    assert choreography_at(
        lyrics, settle, transition_seconds=0.5
    ).transition_progress == pytest.approx(1)


def test_a_gap_covering_scene_settles_on_its_own_start() -> None:
    """A transition played over the hole has already arrived by the downbeat."""
    lyrics = _gapped_sections()

    assert scene_settle_seconds(lyrics, 1, transition_seconds=0.5) == pytest.approx(2.0)


def test_the_first_scene_and_a_cut_settle_immediately() -> None:
    lyrics = _aligned_sections()
    project = _transition_project(
        {"section_transitions": {"chorus": {"curve": "cut"}}}
    )

    assert scene_settle_seconds(lyrics, 0, transition_seconds=0.5) == 0
    assert scene_settle_seconds(
        lyrics, 1, transition_seconds=0.5, visuals=project.visuals
    ) == 2


def test_a_transition_wider_than_its_scene_settles_at_the_midpoint() -> None:
    """Never hand the editor a reset point at the far end of the scene."""
    project = _transition_project(
        {"section_transitions": {"chorus": {"seconds": 9}}}
    )
    lyrics = _aligned_sections()  # the chorus runs 2 -> 4

    settle = scene_settle_seconds(
        lyrics, 1, transition_seconds=0.5, visuals=project.visuals
    )

    assert settle == pytest.approx(3)


def test_gap_covering_does_nothing_when_the_scenes_already_touch() -> None:
    project = _transition_project(
        {"section_transitions": {"chorus": {"seconds": 0.5, "gap": "span"}}}
    )
    # _aligned_sections is contiguous: the verse ends exactly where chorus starts.
    lyrics = _aligned_sections()

    before = choreography_at(
        lyrics, 1.9, transition_seconds=0.5, visuals=project.visuals
    )
    midpoint = choreography_at(
        lyrics, 2.25, transition_seconds=0.5, visuals=project.visuals
    )

    assert before.section_id == "verse"
    assert midpoint.transition_progress == pytest.approx(_ease("smooth", 0.5))


@pytest.mark.parametrize("mode", ["hold", "span", "early"])
def test_trace_time_stays_continuous_however_a_gap_is_covered(mode: str) -> None:
    """The integral bounds move with the transition, so phase must not jump."""
    project = _transition_project(
        {
            "section_styles": {
                "verse": {"trace_speed": 0.5},
                "chorus": {"trace_speed": 1.8},
            },
            "section_transitions": {"chorus": {"seconds": 0.2, "gap": mode}},
        }
    )
    lyrics = _gapped_sections()
    times = [1.4, 1.5, 1.51, 1.7, 2.0, 2.4, 2.49, 2.5, 2.6, 3.0]
    samples = [
        choreography_at(
            lyrics, time, transition_seconds=0.5, visuals=project.visuals
        ).trace_time
        for time in times
    ]

    assert all(later >= earlier for earlier, later in zip(samples, samples[1:]))
    # No step at either edge of the gap.
    assert samples[2] - samples[1] < 0.05
    assert samples[7] - samples[6] < 0.05


@pytest.mark.parametrize("curve", ["cut", "linear", "smooth", "ease_in", "ease_out"])
@pytest.mark.parametrize("upto", [0.4, 1])
def test_transition_curve_integral_matches_the_curve_it_eases(
    curve: str,
    upto: float,
) -> None:
    """The integral drives trace phase, so it must be the curve's true area.

    A mismatch here does not fail loudly — it silently shifts the phase of
    every trace after the first scene change.
    """
    steps = 20000
    numeric = (
        sum(_ease(curve, upto * (index + 0.5) / steps) for index in range(steps))
        * upto
        / steps
    )

    assert _ease_integral(curve, upto) == pytest.approx(numeric, abs=1e-5)


@pytest.mark.parametrize("curve", ["cut", "linear", "smooth", "ease_in", "ease_out"])
def test_every_curve_keeps_trace_time_moving_forward_across_the_boundary(
    curve: str,
) -> None:
    project = _transition_project(
        {
            "section_styles": {
                "verse": {"trace_speed": 0.5},
                "chorus": {"trace_speed": 1.8},
            },
            "section_transitions": {"chorus": {"seconds": 0.5, "curve": curve}},
        }
    )
    lyrics = _aligned_sections()
    samples = [
        choreography_at(
            lyrics,
            time,
            transition_seconds=0.5,
            visuals=project.visuals,
        ).trace_time
        for time in (1.999, 2.0, 2.001, 2.25, 2.5, 3)
    ]

    assert all(later >= earlier for earlier, later in zip(samples, samples[1:]))
    assert samples[2] - samples[1] < 0.01
    assert samples[-1] > samples[0]


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

    # Uncovered time belongs to the scene arriving across it, not the one that
    # just ended: transitions span real gaps by default.
    assert gap_middle.section_id == "chorus"
    assert 0 < gap_middle.transition_progress < 1
    assert gap_middle.trace_time > section_end.trace_time
    assert next_start.trace_time > gap_middle.trace_time
    assert gap_middle.rotation_time > section_end.rotation_time
    assert next_start.rotation_time > gap_middle.rotation_time


def test_silence_renders_every_layer_at_its_identity_opacity() -> None:
    """Rest is the designed look, not a faded version of it.

    A trace with no audio under it must render at exactly the opacity and
    saturation it was authored with, so a designer's `opacity: 0.8` means 0.8
    on screen rather than a ceiling the shape only reaches at peak loudness.
    """
    project = ProjectManifest.model_validate(
        {
            "version": 1,
            "title": "Rest Fixture",
            "audio": {"master": "master.wav"},
            "lyrics": {"source": "lyrics.yaml", "language": "en"},
            "cards": {
                "opening": {"file": "open.jpg", "duration": 1},
                "closing": {"file": "close.jpg", "duration": 1},
            },
            "text": {"font": "font.ttf"},
        }
    )
    silent = AudioVisualState(
        master=SemanticSample(0, 0),
        drums=SemanticSample(0, 0),
        bass=SemanticSample(0, 0),
        vocals=SemanticSample(0, 0),
        instruments=SemanticSample(0, 0),
        spectral_centroid=0,
    )
    choreography = ChoreographyState(
        section_id="intro",
        section_type="intro",
        section_label="Intro",
        section_progress=0.5,
        transition_progress=1,
        layer_fraction=1,
        scale=1,
        motion=0,
        color_intensity=1,
        onset_response=0,
        rotation_direction=1,
        palette_shift=0,
        lyrics_opacity=1,
    )

    for layer in project.visuals.layers:
        state = map_layer_state(layer, silent, choreography, 0)
        assert state.opacity == pytest.approx(layer.opacity)
        assert state.color_intensity == pytest.approx(choreography.color_intensity)
        assert state.line_width == pytest.approx(layer.line_width)


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
        layer for layer in project.visuals.layers if layer.z_index < 0
    )
    drums = next(layer for layer in project.visuals.layers if layer.role == "drums")

    quiet_background = map_layer_state(background, quiet, choreography, 1)
    strong_background = map_layer_state(background, strong, choreography, 1)
    quiet_drums = map_layer_state(drums, quiet, choreography, 1)
    strong_drums = map_layer_state(drums, strong, choreography, 1)

    # `balanced` spends no energy on alpha or saturation: a trace sits at the
    # opacity and saturation it was designed with however loud the passage is,
    # and loudness reads through size and line weight instead.
    assert strong_background.opacity == pytest.approx(quiet_background.opacity)
    assert strong_background.color_intensity == pytest.approx(
        quiet_background.color_intensity
    )
    assert strong_background.scale > quiet_background.scale
    assert strong_background.line_width > quiet_background.line_width

    # A preset opts back in through the lift, and it can only ever add.
    kinetic = get_mapping_preset("kinetic")
    quiet_kinetic = map_layer_state(background, quiet, choreography, 1, kinetic)
    strong_kinetic = map_layer_state(background, strong, choreography, 1, kinetic)
    assert strong_kinetic.opacity > quiet_kinetic.opacity
    assert strong_kinetic.color_intensity > quiet_kinetic.color_intensity
    assert quiet_kinetic.opacity >= quiet_background.opacity

    assert strong_drums.beat_pulse > 0.9
    assert quiet_drums.beat_pulse < 0.1
    assert quiet_background.beat_pulse == 0
