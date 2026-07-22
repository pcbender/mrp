import hashlib
import random
from dataclasses import dataclass

from mrp.video.project import (
    ActorCastConfig,
    CastingConfig,
    LayerGeometryConfig,
    LayerTraceConfig,
    SectionCompositionConfig,
    TraceAudioDriversConfig,
    VisualConfig,
    VisualLayerConfig,
    VisualRole,
)

AUTO_CASTING_GENERATOR_VERSION = 1

_ROLE_COLORS = {
    "master": "#6ee7f2",
    "drums": "#ffd166",
    "bass": "#4c78ff",
    "vocals": "#ff5fd2",
    "instruments": "#8c5cff",
}


@dataclass(frozen=True, slots=True)
class ResolvedComposition:
    key: str
    composition: SectionCompositionConfig


def _stable_seed(project_seed: int, section_type: str) -> int:
    digest = hashlib.sha256(
        f"{AUTO_CASTING_GENERATOR_VERSION}:{project_seed}:{section_type.casefold()}".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big")


def _jitter(rng: random.Random, value: int, amount: int) -> int:
    return max(1, value + rng.randint(-amount, amount))


def _trace(
    *,
    trace_id: str,
    role: VisualRole,
    fixed_radius: int,
    moving_radius: int,
    pen_offset: int,
    phase: float = 0.0,
    rotation: str = "inside",
    samples: int = 1200,
    anchor_x: float,
    anchor_y: float,
    scale: float,
    cycles_per_second: float,
    trail_fraction: float,
    opacity: float = 0.8,
    line_width: float = 2.2,
    rotation_speed: float = 0,
    ghosts: int = 1,
    head_radius: float = 4,
    depth: str = "foreground",
    drivers: TraceAudioDriversConfig | None = None,
) -> VisualLayerConfig:
    return VisualLayerConfig(
        id=trace_id,
        role=role,
        geometry=LayerGeometryConfig(
            fixed_radius=fixed_radius,
            moving_radius=moving_radius,
            pen_offset=pen_offset,
            phase=phase,
            rotation=rotation,
            samples=samples,
        ),
        trace=LayerTraceConfig(
            cycles_per_second=cycles_per_second,
            trail_fraction=trail_fraction,
            ghost_count=ghosts,
            ghost_spacing=0.08,
            head_radius=head_radius,
        ),
        color=_ROLE_COLORS[role],
        depth=depth,
        anchor_x=anchor_x,
        anchor_y=anchor_y,
        base_scale=scale,
        opacity=opacity,
        line_width=line_width,
        rotation_degrees_per_second=rotation_speed,
        drivers=drivers or TraceAudioDriversConfig(),
    )


def _drivers(
    *,
    scale: str,
    opacity: str,
    color: str,
    pulse: str,
) -> TraceAudioDriversConfig:
    return TraceAudioDriversConfig(
        scale=scale,
        opacity=opacity,
        color=color,
        pulse=pulse,
    )


def _auto_traces(section_type: str, rng: random.Random) -> list[VisualLayerConfig]:
    kind = section_type.casefold()
    if kind == "intro":
        return [
            _trace(
                trace_id="intro-lantern",
                role="instruments",
                fixed_radius=_jitter(rng, 173, 5),
                moving_radius=_jitter(rng, 61, 3),
                pen_offset=_jitter(rng, 104, 5),
                anchor_x=0.48,
                anchor_y=0.35,
                scale=0.72,
                cycles_per_second=0.045,
                trail_fraction=0.38,
                opacity=0.58,
                line_width=1.8,
                rotation_speed=-0.45,
                ghosts=2,
                drivers=_drivers(
                    scale="instruments.energy",
                    opacity="master.energy",
                    color="vocals.energy",
                    pulse="drums.accent",
                ),
            )
        ]
    if kind == "verse":
        return [
            _trace(
                trace_id="verse-orbit",
                role="bass",
                fixed_radius=_jitter(rng, 227, 7),
                moving_radius=_jitter(rng, 83, 4),
                pen_offset=_jitter(rng, 142, 6),
                rotation="outside",
                samples=1400,
                anchor_x=0.2,
                anchor_y=0.37,
                scale=0.67,
                cycles_per_second=0.038,
                trail_fraction=0.2,
                opacity=0.66,
                line_width=2,
                rotation_speed=0.65,
                drivers=_drivers(
                    scale="bass.energy",
                    opacity="master.energy",
                    color="bass.energy",
                    pulse="drums.accent",
                ),
            ),
            _trace(
                trace_id="verse-bloom",
                role="vocals",
                fixed_radius=_jitter(rng, 156, 5),
                moving_radius=_jitter(rng, 52, 3),
                pen_offset=_jitter(rng, 116, 5),
                anchor_x=0.75,
                anchor_y=0.3,
                scale=0.48,
                cycles_per_second=0.064,
                trail_fraction=0.3,
                opacity=0.76,
                line_width=2.2,
                rotation_speed=-1.1,
                drivers=_drivers(
                    scale="vocals.energy",
                    opacity="vocals.energy",
                    color="vocals.energy",
                    pulse="drums.accent",
                ),
            ),
        ]
    if kind == "pre_chorus":
        return [
            _trace(
                trace_id="pre-chorus-knot-left",
                role="instruments",
                fixed_radius=_jitter(rng, 191, 5),
                moving_radius=_jitter(rng, 72, 3),
                pen_offset=_jitter(rng, 126, 5),
                anchor_x=0.34,
                anchor_y=0.3,
                scale=0.61,
                cycles_per_second=0.073,
                trail_fraction=0.34,
                opacity=0.72,
                line_width=2.2,
                rotation_speed=-1.4,
                drivers=_drivers(
                    scale="bass.energy",
                    opacity="master.energy",
                    color="instruments.energy",
                    pulse="drums.accent",
                ),
            ),
            _trace(
                trace_id="pre-chorus-knot-right",
                role="vocals",
                fixed_radius=_jitter(rng, 149, 5),
                moving_radius=_jitter(rng, 47, 3),
                pen_offset=_jitter(rng, 108, 5),
                rotation="outside",
                anchor_x=0.68,
                anchor_y=0.36,
                scale=0.56,
                cycles_per_second=0.086,
                trail_fraction=0.28,
                opacity=0.78,
                line_width=2.3,
                rotation_speed=1.65,
                drivers=_drivers(
                    scale="vocals.energy",
                    opacity="vocals.energy",
                    color="vocals.energy",
                    pulse="drums.accent",
                ),
            ),
        ]
    if kind == "chorus":
        return [
            _trace(
                trace_id="chorus-wheel",
                role="bass",
                fixed_radius=_jitter(rng, 238, 7),
                moving_radius=_jitter(rng, 91, 4),
                pen_offset=_jitter(rng, 151, 6),
                rotation="outside",
                samples=1500,
                anchor_x=0.13,
                anchor_y=0.39,
                scale=0.72,
                cycles_per_second=0.052,
                trail_fraction=0.24,
                opacity=0.78,
                line_width=2.5,
                rotation_speed=1.1,
                drivers=_drivers(
                    scale="bass.energy",
                    opacity="master.energy",
                    color="bass.energy",
                    pulse="drums.accent",
                ),
            ),
            _trace(
                trace_id="chorus-rosette",
                role="vocals",
                fixed_radius=_jitter(rng, 205, 6),
                moving_radius=_jitter(rng, 74, 3),
                pen_offset=_jitter(rng, 132, 5),
                anchor_x=0.5,
                anchor_y=0.29,
                scale=0.66,
                cycles_per_second=0.082,
                trail_fraction=0.38,
                opacity=0.86,
                line_width=2.7,
                rotation_speed=-1.5,
                ghosts=2,
                drivers=_drivers(
                    scale="vocals.energy",
                    opacity="vocals.energy",
                    color="vocals.energy",
                    pulse="drums.accent",
                ),
            ),
            _trace(
                trace_id="chorus-star",
                role="drums",
                fixed_radius=_jitter(rng, 167, 5),
                moving_radius=_jitter(rng, 49, 3),
                pen_offset=_jitter(rng, 119, 4),
                rotation="outside",
                anchor_x=0.87,
                anchor_y=0.38,
                scale=0.57,
                cycles_per_second=0.12,
                trail_fraction=0.22,
                opacity=0.8,
                line_width=2,
                rotation_speed=2.25,
                drivers=_drivers(
                    scale="drums.energy",
                    opacity="master.energy",
                    color="instruments.energy",
                    pulse="drums.accent",
                ),
            ),
        ]
    if kind == "build":
        traces: list[VisualLayerConfig] = []
        roles: tuple[VisualRole, ...] = (
            "bass",
            "instruments",
            "vocals",
            "drums",
        )
        for index, role in enumerate(roles):
            traces.append(
                _trace(
                    trace_id=f"build-seed-{index + 1}",
                    role=role,
                    fixed_radius=_jitter(rng, 137 + index * 19, 6),
                    moving_radius=_jitter(rng, 41 + index * 7, 3),
                    pen_offset=_jitter(rng, 94 + index * 8, 5),
                    rotation="outside" if index % 2 else "inside",
                    anchor_x=0.1 + index * 0.27,
                    anchor_y=0.39 - (index % 2) * 0.13,
                    scale=0.38 + index * 0.04,
                    cycles_per_second=0.065 + index * 0.018,
                    trail_fraction=0.22 + index * 0.035,
                    opacity=0.62 + index * 0.055,
                    line_width=1.7 + index * 0.18,
                    rotation_speed=(-1 if index % 2 else 1) * (1 + index * 0.4),
                    drivers=_drivers(
                        scale=f"{role}.energy",
                        opacity="master.energy",
                        color=f"{role}.energy",
                        pulse="drums.accent",
                    ),
                )
            )
        return traces
    if kind == "bridge":
        return [
            _trace(
                trace_id="bridge-hero-flower",
                role="vocals",
                fixed_radius=_jitter(rng, 252, 5),
                moving_radius=_jitter(rng, 84, 2),
                pen_offset=_jitter(rng, 194, 5),
                samples=1800,
                anchor_x=0.39,
                anchor_y=0.42,
                scale=1.62,
                cycles_per_second=0.036,
                trail_fraction=0.52,
                opacity=0.78,
                line_width=3.2,
                rotation_speed=-0.52,
                ghosts=2,
                head_radius=5,
                drivers=_drivers(
                    scale="bass.energy",
                    opacity="master.energy",
                    color="vocals.energy",
                    pulse="drums.accent",
                ),
            )
        ]
    if kind == "instrumental":
        return [
            _trace(
                trace_id="instrumental-arc-left",
                role="bass",
                fixed_radius=_jitter(rng, 244, 7),
                moving_radius=_jitter(rng, 67, 3),
                pen_offset=_jitter(rng, 174, 6),
                rotation="outside",
                samples=1600,
                anchor_x=-0.02,
                anchor_y=0.39,
                scale=0.96,
                cycles_per_second=0.058,
                trail_fraction=0.34,
                opacity=0.72,
                line_width=2.3,
                rotation_speed=1.1,
                drivers=_drivers(
                    scale="bass.energy",
                    opacity="master.energy",
                    color="bass.energy",
                    pulse="drums.accent",
                ),
            ),
            _trace(
                trace_id="instrumental-lace",
                role="instruments",
                fixed_radius=_jitter(rng, 213, 6),
                moving_radius=_jitter(rng, 58, 3),
                pen_offset=_jitter(rng, 151, 5),
                anchor_x=0.53,
                anchor_y=0.3,
                scale=0.73,
                cycles_per_second=0.09,
                trail_fraction=0.42,
                opacity=0.78,
                line_width=2.4,
                rotation_speed=-1.8,
                ghosts=2,
                drivers=_drivers(
                    scale="instruments.energy",
                    opacity="master.energy",
                    color="instruments.energy",
                    pulse="drums.accent",
                ),
            ),
            _trace(
                trace_id="instrumental-comet-right",
                role="drums",
                fixed_radius=_jitter(rng, 184, 5),
                moving_radius=_jitter(rng, 53, 3),
                pen_offset=_jitter(rng, 128, 5),
                rotation="outside",
                anchor_x=1.02,
                anchor_y=0.42,
                scale=0.82,
                cycles_per_second=0.14,
                trail_fraction=0.2,
                opacity=0.76,
                line_width=2,
                rotation_speed=2.6,
                drivers=_drivers(
                    scale="drums.energy",
                    opacity="master.energy",
                    color="vocals.energy",
                    pulse="drums.accent",
                ),
            ),
        ]
    if kind == "outro":
        return [
            _trace(
                trace_id="outro-eclipse",
                role="vocals",
                fixed_radius=_jitter(rng, 218, 6),
                moving_radius=_jitter(rng, 79, 3),
                pen_offset=_jitter(rng, 148, 5),
                anchor_x=0.62,
                anchor_y=0.37,
                scale=0.92,
                cycles_per_second=0.038,
                trail_fraction=0.48,
                opacity=0.64,
                line_width=2.1,
                rotation_speed=-0.42,
                ghosts=3,
                drivers=_drivers(
                    scale="vocals.energy",
                    opacity="master.energy",
                    color="vocals.energy",
                    pulse="drums.accent",
                ),
            )
        ]
    return [
        _trace(
            trace_id=f"{kind}-orbit",
            role="instruments",
            fixed_radius=_jitter(rng, 211, 9),
            moving_radius=_jitter(rng, 73, 5),
            pen_offset=_jitter(rng, 139, 7),
            rotation="outside",
            anchor_x=0.27,
            anchor_y=0.34,
            scale=0.7,
            cycles_per_second=0.064,
            trail_fraction=0.3,
            opacity=0.72,
            line_width=2.2,
            rotation_speed=0.9,
            drivers=_drivers(
                scale="instruments.energy",
                opacity="master.energy",
                color="instruments.energy",
                pulse="drums.accent",
            ),
        ),
        _trace(
            trace_id=f"{kind}-flower",
            role="vocals",
            fixed_radius=_jitter(rng, 163, 7),
            moving_radius=_jitter(rng, 51, 4),
            pen_offset=_jitter(rng, 112, 6),
            anchor_x=0.73,
            anchor_y=0.33,
            scale=0.56,
            cycles_per_second=0.078,
            trail_fraction=0.34,
            opacity=0.76,
            line_width=2.3,
            rotation_speed=-1.2,
            drivers=_drivers(
                scale="vocals.energy",
                opacity="master.energy",
                color="vocals.energy",
                pulse="drums.accent",
            ),
        ),
    ]


def generate_auto_composition(
    section_type: str,
    project_seed: int,
) -> SectionCompositionConfig:
    seed = _stable_seed(project_seed, section_type)
    rng = random.Random(seed)
    return SectionCompositionConfig(
        casting=CastingConfig(
            source="auto",
            seed=seed,
            generator_version=AUTO_CASTING_GENERATOR_VERSION,
        ),
        traces=_auto_traces(section_type, rng),
    )


def _type_composition(
    visuals: VisualConfig,
    section_type: str,
) -> tuple[str, SectionCompositionConfig] | None:
    folded = section_type.casefold()
    return next(
        (
            (name, composition)
            for name, composition in visuals.section_compositions.items()
            if name.casefold() == folded
        ),
        None,
    )


def _type_actor_cast(
    visuals: VisualConfig,
    section_type: str,
) -> tuple[str, ActorCastConfig] | None:
    folded = section_type.casefold()
    return next(
        (
            (name, cast)
            for name, cast in visuals.section_casts.items()
            if name.casefold() == folded
        ),
        None,
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def compile_actor_cast(
    visuals: VisualConfig,
    cast: ActorCastConfig,
) -> SectionCompositionConfig:
    """Compile actor identity plus scene direction to the stable trace contract."""
    traces: list[VisualLayerConfig] = []
    for assignment in cast.actors:
        actor = visuals.actors[assignment.actor]
        direction = assignment.direction
        for component in actor.components:
            drivers = component.drivers
            role = component.role
            if actor.character is not None:
                role = actor.character
                energy = f"{role}.energy"
                accent = f"{role}.accent"
                drivers = TraceAudioDriversConfig(
                    scale=energy,
                    opacity=energy,
                    color=energy,
                    pulse=accent,
                )
            anchor_x = component.anchor_x
            if direction.anchor_x is not None:
                anchor_x += direction.anchor_x - 0.5
            anchor_y = component.anchor_y
            if direction.anchor_y is not None:
                anchor_y += direction.anchor_y - 0.5
            traces.append(
                component.model_copy(
                    update={
                        "id": f"{assignment.id}--{component.id}",
                        "role": role,
                        "anchor_x": _clamp(anchor_x, -0.5, 1.5),
                        "anchor_y": _clamp(anchor_y, -0.5, 1.5),
                        "base_scale": _clamp(
                            component.base_scale * direction.scale,
                            0.000001,
                            2,
                        ),
                        "opacity": (
                            component.opacity * direction.opacity
                            if direction.visible
                            else 0
                        ),
                        "rotation_degrees_per_second": _clamp(
                            component.rotation_degrees_per_second
                            + direction.rotation_offset_degrees_per_second,
                            -180,
                            180,
                        ),
                        "hue_shift_degrees": _clamp(
                            component.hue_shift_degrees
                            + direction.hue_shift_degrees,
                            -360,
                            360,
                        ),
                        "depth": direction.depth or component.depth,
                        "drivers": drivers,
                    }
                )
            )
    return SectionCompositionConfig(casting=cast.casting, traces=traces)


def resolve_section_composition(
    visuals: VisualConfig,
    section_type: str,
    section_id: str,
    project_seed: int,
) -> ResolvedComposition:
    actor_override = visuals.cast_overrides.get(section_id)
    if actor_override is not None:
        return ResolvedComposition(
            f"actors:section:{section_id}",
            compile_actor_cast(visuals, actor_override),
        )
    actor_cast = _type_actor_cast(visuals, section_type)
    if actor_cast is not None:
        name, cast = actor_cast
        return ResolvedComposition(
            f"actors:type:{name.casefold()}",
            compile_actor_cast(visuals, cast),
        )
    override = visuals.composition_overrides.get(section_id)
    if override is not None:
        return ResolvedComposition(f"section:{section_id}", override)
    configured = _type_composition(visuals, section_type)
    if configured is not None:
        name, composition = configured
        return ResolvedComposition(f"type:{name.casefold()}", composition)
    if visuals.auto_casting:
        composition = generate_auto_composition(section_type, project_seed)
        return ResolvedComposition(f"auto:{section_type.casefold()}", composition)
    return ResolvedComposition(
        "legacy:global-layers",
        SectionCompositionConfig(
            casting=CastingConfig(source="manual", seed=project_seed),
            traces=visuals.layers,
        ),
    )
