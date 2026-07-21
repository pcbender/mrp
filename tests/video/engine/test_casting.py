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
    assert verse.key == "auto:verse"


def test_disabling_auto_casting_uses_the_global_layer_fallback() -> None:
    visuals = VisualConfig(auto_casting=False)

    resolved = resolve_section_composition(
        visuals,
        "bridge",
        "bridge",
        4821,
    )

    assert resolved.key == "legacy:global-layers"
    assert resolved.composition.traces == visuals.layers


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
    assert petals.role == "bass"
    assert petals.drivers.scale == "bass.energy"
    assert petals.drivers.pulse == "bass.accent"
    assert petals.hue_shift_degrees == 20


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
