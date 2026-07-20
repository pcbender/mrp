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
