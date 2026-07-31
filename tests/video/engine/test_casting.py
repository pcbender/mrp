from mrp.video.casting import (
    generate_auto_composition,
    resolve_section_composition,
)
from mrp.video.project import VisualConfig


def _trace(trace_id: str, fixed_radius: int) -> dict[str, object]:
    return {
        "id": trace_id,
        "role": "vocals",
        "geometry": {
            "fixed_radius": fixed_radius,
            "moving_radius": 40,
            "pen_offset": 80,
        },
        "color": "#ff5fd2",
        "drivers": {
            "scale": "bass.energy",
            "opacity": "master.energy",
            "color": "vocals.energy",
            "pulse": "drums.accent",
        },
    }


def test_auto_casting_is_deterministic_and_distinct_by_section_type() -> None:
    first_verse = generate_auto_composition("verse", 4821)
    second_verse = generate_auto_composition("verse", 4821)
    chorus = generate_auto_composition("chorus", 4821)

    assert first_verse == second_verse
    assert first_verse.casting.source == "auto"
    assert first_verse.casting.seed is not None
    assert [trace.geometry for trace in first_verse.traces] != [
        trace.geometry for trace in chorus.traces
    ]
    assert len(first_verse.traces) == 2
    assert len(chorus.traces) == 3


def test_bridge_auto_cast_is_one_oversized_multi_driver_flower() -> None:
    bridge = generate_auto_composition("bridge", 4821)

    assert len(bridge.traces) == 1
    hero = bridge.traces[0]
    assert hero.id == "bridge-hero-flower"
    assert hero.base_scale > 1.5
    assert hero.anchor_x < 0.5
    assert hero.drivers.scale == "bass.energy"
    assert hero.drivers.opacity == "master.energy"
    assert hero.drivers.color == "vocals.energy"
    assert hero.drivers.pulse == "drums.accent"


def test_composition_resolution_prefers_exact_id_then_type_then_auto() -> None:
    visuals = VisualConfig.model_validate(
        {
            "section_compositions": {
                "Chorus": {
                    "casting": {"source": "manual"},
                    "traces": [_trace("normal-chorus", 160)],
                }
            },
            "composition_overrides": {
                "final_chorus": {
                    "casting": {"source": "ai", "seed": 73},
                    "traces": [_trace("final-chorus", 240)],
                }
            },
        }
    )

    chorus = resolve_section_composition(visuals, "chorus", "chorus_1", 4821)
    final = resolve_section_composition(
        visuals,
        "chorus",
        "final_chorus",
        4821,
    )
    verse = resolve_section_composition(visuals, "verse", "verse_1", 4821)

    assert chorus.key == "type:chorus"
    assert chorus.composition.traces[0].id == "normal-chorus"
    assert final.key == "section:final_chorus"
    assert final.composition.casting.source == "ai"
    assert final.composition.traces[0].id == "final-chorus"
    # Nothing casts a verse, so a verse draws nothing.
    assert verse.key == "uncast:empty"
    assert verse.composition.traces == []


def test_an_uncast_scene_draws_nothing() -> None:
    """No cast, no shapes — whatever else the project carries.

    A scene used to fill itself in from the deterministic look, or from the
    global layer list when auto-casting was off, so a video showed shapes its
    author never chose. The default look is a button in Scene Casting now.
    """
    populated = VisualConfig()
    assert populated.layers, "fixture should carry global layers to fall back to"

    for visuals in (VisualConfig(), VisualConfig(auto_casting=False)):
        resolved = resolve_section_composition(visuals, "bridge", "bridge", 4821)

        assert resolved.key == "uncast:empty"
        assert resolved.composition.traces == []


def test_actor_cast_compiles_identity_and_scene_direction_to_traces() -> None:
    visuals = VisualConfig.model_validate(
        {
            "actors": {
                "vocal-bloom": {
                    "id": "vocal-bloom",
                    "name": "Vocal Bloom",
                    "character": "bass",
                    "components": [
                        {
                            **_trace("petals", 180),
                            "anchor_x": 0.4,
                            "anchor_y": 0.3,
                            "base_scale": 0.5,
                            "opacity": 0.8,
                        },
                        {
                            **_trace("halo", 120),
                            "anchor_x": 0.6,
                            "anchor_y": 0.3,
                            "base_scale": 0.3,
                        },
                    ],
                }
            },
            "section_casts": {
                "Verse": {
                    "actors": [
                        {
                            "id": "lead",
                            "actor": "vocal-bloom",
                            "direction": {
                                "anchor_x": 0.6,
                                "anchor_y": 0.45,
                                "scale": 1.5,
                                "opacity": 0.5,
                                "rotation_wobble_degrees": 7.5,
                                "hue_shift_degrees": 20,
                            },
                        }
                    ]
                }
            },
        }
    )

    resolved = resolve_section_composition(visuals, "verse", "verse_1", 4821)

    assert resolved.key == "actors:type:verse"
    assert [trace.id for trace in resolved.composition.traces] == [
        "lead--petals",
        "lead--halo",
    ]
    petals = resolved.composition.traces[0]
    assert petals.geometry.fixed_radius == 180
    assert petals.anchor_x == 0.5
    assert petals.anchor_y == 0.25
    assert petals.base_scale == 0.75
    assert petals.opacity == 0.4
    assert petals.rotation_wobble_degrees == 7.5
    assert petals.role == "bass"
    assert petals.drivers.scale == "bass.energy"
    assert petals.drivers.pulse == "bass.accent"
    assert petals.hue_shift_degrees == 20


def test_actor_cast_adds_scene_pitch_yaw_and_tumble_to_spatial_identity() -> None:
    component = _trace("woven", 180) | {
        "spatial": {
            "mode": "wave",
            "amplitude": 0.4,
            "windings": 6,
            "pitch_degrees": 20,
            "yaw_degrees": -10,
            "pitch_degrees_per_second": 2,
            "yaw_degrees_per_second": -3,
        }
    }
    visuals = VisualConfig.model_validate(
        {
            "actors": {
                "weaver": {
                    "id": "weaver",
                    "name": "Weaver",
                    "character": "vocals",
                    "components": [component],
                }
            },
            "section_casts": {
                "verse": {
                    "actors": [
                        {
                            "id": "lead",
                            "actor": "weaver",
                            "direction": {
                                "pitch_offset_degrees": 12,
                                "yaw_offset_degrees": 5,
                                "pitch_degrees_per_second": 1.5,
                                "yaw_degrees_per_second": 4,
                            },
                        }
                    ]
                }
            },
        }
    )

    trace = resolve_section_composition(
        visuals, "verse", "verse_1", 4821
    ).composition.traces[0]

    assert trace.spatial is not None
    assert trace.spatial.mode == "wave"
    assert trace.spatial.amplitude == 0.4
    assert trace.spatial.pitch_degrees == 32
    assert trace.spatial.yaw_degrees == -5
    assert trace.spatial.pitch_degrees_per_second == 3.5
    assert trace.spatial.yaw_degrees_per_second == 1


def test_scene_orientation_can_tilt_an_originally_2d_actor() -> None:
    visuals = VisualConfig.model_validate(
        {
            "actors": {
                "flat": {
                    "id": "flat",
                    "name": "Flat",
                    "character": "vocals",
                    "components": [_trace("line", 180)],
                }
            },
            "section_casts": {
                "verse": {
                    "actors": [
                        {
                            "id": "lead",
                            "actor": "flat",
                            "direction": {"pitch_offset_degrees": 30},
                        }
                    ]
                }
            },
        }
    )

    trace = resolve_section_composition(
        visuals, "verse", "verse_1", 4821
    ).composition.traces[0]

    assert trace.spatial is not None
    assert trace.spatial.mode == "tilted"
    assert trace.spatial.pitch_degrees == 30


def test_presentation_direction_is_actor_local() -> None:
    visuals = VisualConfig.model_validate(
        {
            "actors": {
                "outlined": {
                    "id": "outlined",
                    "name": "Outlined",
                    "character": "vocals",
                    "components": [_trace("mark", 180)],
                },
                "traced": {
                    "id": "traced",
                    "name": "Traced",
                    "character": "bass",
                    "components": [_trace("mark", 140)],
                },
                "filled": {
                    "id": "filled",
                    "name": "Filled",
                    "character": "instruments",
                    "components": [_trace("mark", 120)],
                },
            },
            "section_casts": {
                "verse": {
                    "actors": [
                        {
                            "id": "outlined-role",
                            "actor": "outlined",
                            "direction": {"presentation": "full_outline"},
                        },
                        {
                            "id": "traced-role",
                            "actor": "traced",
                        },
                        {
                            "id": "filled-role",
                            "actor": "filled",
                            "direction": {"presentation": "filled_shape"},
                        },
                    ]
                }
            },
        }
    )

    traces = resolve_section_composition(
        visuals, "verse", "verse_1", 4821
    ).composition.traces

    assert [trace.presentation for trace in traces] == [
        "full_outline",
        "animated_trace",
        "filled_shape",
    ]


def test_exact_actor_cast_direction_precedes_type_and_legacy_compositions() -> None:
    visuals = VisualConfig.model_validate(
        {
            "actors": {
                "solo": {
                    "id": "solo",
                    "name": "Solo",
                    "character": "vocals",
                    "components": [_trace("shape", 180)],
                }
            },
            "section_casts": {
                "chorus": {"actors": [{"id": "group", "actor": "solo"}]}
            },
            "cast_overrides": {
                "final_chorus": {
                    "actors": [
                        {
                            "id": "hero",
                            "actor": "solo",
                            "direction": {"scale": 1.5, "visible": False},
                        }
                    ]
                }
            },
            "composition_overrides": {
                "final_chorus": {"traces": [_trace("legacy", 240)]}
            },
        }
    )

    resolved = resolve_section_composition(
        visuals,
        "chorus",
        "final_chorus",
        4821,
    )

    assert resolved.key == "actors:section:final_chorus"
    assert resolved.composition.traces[0].id == "hero--shape"
    assert resolved.composition.traces[0].opacity == 0


def test_scene_wardrobe_replaces_actor_look_and_survives_the_palette() -> None:
    """A directed color is a costume for one scene, not a new identity.

    The actor keeps its own white in scenes that gave no wardrobe note, and the
    directed scene locks its color so a production palette cannot restyle it.
    """
    visuals = VisualConfig.model_validate(
        {
            "actors": {
                "title": {
                    "id": "title",
                    "name": "Song Title",
                    "character": "vocals",
                    "components": [
                        {
                            **_trace("mark", 200),
                            "color": "#ffffff",
                            "line_width": 2.5,
                            "blend_mode": "screen",
                        }
                    ],
                }
            },
            "section_casts": {
                "intro": {
                    "actors": [
                        {
                            "id": "billing",
                            "actor": "title",
                            "direction": {
                                "color": "#ff0000",
                                "line_width": 6,
                                "blend_mode": "normal",
                            },
                        }
                    ]
                },
                "outro": {"actors": [{"id": "billing", "actor": "title"}]},
            },
        }
    )

    dressed = resolve_section_composition(visuals, "intro", "intro_1", 4821)
    bare = resolve_section_composition(visuals, "outro", "outro_1", 4821)

    assert dressed.composition.traces[0].color == "#ff0000"
    assert dressed.composition.traces[0].color_locked is True
    assert dressed.composition.traces[0].line_width == 6
    assert dressed.composition.traces[0].blend_mode == "normal"

    assert bare.composition.traces[0].color == "#ffffff"
    assert bare.composition.traces[0].color_locked is False
    assert bare.composition.traces[0].line_width == 2.5
    assert bare.composition.traces[0].blend_mode == "screen"


def test_scene_energy_overrides_merge_onto_the_actors_own_trace() -> None:
    """A scene changes the energy it names and inherits the rest.

    The trace override is partial on purpose: a scene that only speeds an actor
    up must not silently reset its ghosts or trail to schema defaults.
    """
    visuals = VisualConfig.model_validate(
        {
            "actors": {
                "orbit": {
                    "id": "orbit",
                    "name": "Orbit",
                    "character": "drums",
                    "components": [
                        {
                            **_trace("ring", 160),
                            "trace": {
                                "cycles_per_second": 0.1,
                                "trail_fraction": 0.3,
                                "ghost_count": 2,
                                "ghost_spacing": 0.05,
                                "head_radius": 4,
                            },
                        }
                    ],
                }
            },
            "section_casts": {
                "bridge": {
                    "actors": [
                        {
                            "id": "lead",
                            "actor": "orbit",
                            "direction": {
                                "trace": {
                                    "cycles_per_second": 0.9,
                                    "ghost_count": 0,
                                }
                            },
                        }
                    ]
                },
                "verse": {"actors": [{"id": "lead", "actor": "orbit"}]},
            },
        }
    )

    driven = resolve_section_composition(visuals, "bridge", "bridge_1", 4821)
    calm = resolve_section_composition(visuals, "verse", "verse_1", 4821)

    trace = driven.composition.traces[0].trace
    assert trace.cycles_per_second == 0.9
    assert trace.ghost_count == 0
    # Untouched by this scene, so still the actor's own.
    assert trace.trail_fraction == 0.3
    assert trace.ghost_spacing == 0.05
    assert trace.head_radius == 4

    assert calm.composition.traces[0].trace.cycles_per_second == 0.1
    assert calm.composition.traces[0].trace.ghost_count == 2
