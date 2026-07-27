from dataclasses import dataclass, field, fields, replace
from typing import Any

from mrp.video.project import (
    GAP_EPSILON_SECONDS,
    AlignedLyrics,
    SceneTransitionConfig,
    SectionVisualStyleConfig,
    TransitionCurve,
    TransitionGap,
    VisualConfig,
    VisualRole,
)

_VISUAL_ROLES: tuple[VisualRole, ...] = (
    "master",
    "drums",
    "bass",
    "vocals",
    "instruments",
)


@dataclass(frozen=True, slots=True)
class SectionStyle:
    layer_fraction: float
    scale: float
    motion: float
    color_intensity: float
    onset_response: float
    rotation_direction: float = 1
    palette_shift: float = 0
    lyrics_opacity: float = 1
    spatial_spread: float = 1
    anchor_drift: float = 0.008
    trace_speed: float = 1
    trail_length: float = 1
    beat_gain: float = 1
    intensity_gain: float = 1
    visible_roles: tuple[VisualRole, ...] = _VISUAL_ROLES


@dataclass(frozen=True, slots=True)
class ChoreographyState:
    section_id: str
    section_type: str
    section_label: str | None
    section_progress: float
    transition_progress: float
    layer_fraction: float
    scale: float
    motion: float
    color_intensity: float
    onset_response: float
    rotation_direction: float
    palette_shift: float
    lyrics_opacity: float
    spatial_spread: float = 1
    anchor_drift: float = 0.008
    trace_speed: float = 1
    trail_length: float = 1
    beat_gain: float = 1
    intensity_gain: float = 1
    trace_time: float = 0
    rotation_time: float = 0
    role_visibility: dict[str, float] = field(default_factory=dict)
    previous_section_id: str | None = None


_DEFAULT_STYLE = SectionStyle(
    layer_fraction=0.74,
    scale=0.96,
    motion=0.9,
    color_intensity=0.9,
    onset_response=0.9,
)
_SECTION_STYLES = {
    "verse": SectionStyle(
        layer_fraction=0.58,
        scale=0.9,
        motion=0.72,
        color_intensity=0.78,
        onset_response=0.72,
        spatial_spread=0.92,
        anchor_drift=0.006,
        trace_speed=0.82,
        trail_length=0.78,
        beat_gain=0.55,
        intensity_gain=0.82,
        visible_roles=("vocals", "instruments"),
    ),
    "chorus": SectionStyle(
        layer_fraction=1,
        scale=1.08,
        motion=1.18,
        color_intensity=1.16,
        onset_response=1.35,
        spatial_spread=1.08,
        anchor_drift=0.014,
        trace_speed=1.15,
        trail_length=1.18,
        beat_gain=1.4,
        intensity_gain=1.2,
        visible_roles=("bass", "vocals", "drums", "instruments"),
    ),
    "pre_chorus": SectionStyle(
        layer_fraction=0.78,
        scale=0.98,
        motion=0.94,
        color_intensity=0.96,
        onset_response=0.92,
        spatial_spread=1,
        anchor_drift=0.01,
        trace_speed=0.96,
        trail_length=0.94,
        beat_gain=0.82,
        intensity_gain=1,
        visible_roles=("bass", "vocals", "instruments"),
    ),
    "build": SectionStyle(
        layer_fraction=0.9,
        scale=1.02,
        motion=1.08,
        color_intensity=1.06,
        onset_response=1.12,
        spatial_spread=1.03,
        anchor_drift=0.014,
        trace_speed=1.06,
        trail_length=1.04,
        beat_gain=1.12,
        intensity_gain=1.1,
    ),
    "bridge": SectionStyle(
        layer_fraction=0.82,
        scale=0.98,
        motion=0.92,
        color_intensity=1.12,
        onset_response=1,
        rotation_direction=-1,
        palette_shift=0.16,
        spatial_spread=0.8,
        anchor_drift=0.022,
        trace_speed=0.9,
        trail_length=0.92,
        beat_gain=0.85,
        intensity_gain=1.05,
        visible_roles=("bass", "vocals", "instruments"),
    ),
    "instrumental": SectionStyle(
        layer_fraction=1,
        scale=1.04,
        motion=1.12,
        color_intensity=1.05,
        onset_response=1.18,
        palette_shift=0.06,
        lyrics_opacity=0,
        spatial_spread=1.12,
        anchor_drift=0.018,
        trace_speed=1.12,
        trail_length=1.08,
        beat_gain=1.2,
        intensity_gain=1.15,
    ),
    "intro": SectionStyle(
        layer_fraction=0.48,
        scale=0.86,
        motion=0.62,
        color_intensity=0.72,
        onset_response=0.62,
        spatial_spread=0.76,
        anchor_drift=0.004,
        trace_speed=0.68,
        trail_length=0.68,
        beat_gain=0.35,
        intensity_gain=0.65,
        visible_roles=("vocals", "instruments"),
    ),
    "outro": SectionStyle(
        layer_fraction=0.68,
        scale=0.92,
        motion=0.7,
        color_intensity=0.82,
        onset_response=0.7,
        spatial_spread=0.88,
        anchor_drift=0.005,
        trace_speed=0.72,
        trail_length=0.62,
        beat_gain=0.45,
        intensity_gain=0.72,
        visible_roles=("bass", "vocals", "instruments"),
    ),
}


def _clamp01(value: float) -> float:
    return min(1, max(0, value))


def _ease(curve: TransitionCurve, value: float) -> float:
    """Map raw transition progress onto the curve the scene asked for."""
    value = _clamp01(value)
    if curve == "cut":
        return 1
    if curve == "linear":
        return value
    if curve == "ease_in":
        return value * value
    if curve == "ease_out":
        return value * (2 - value)
    return value * value * (3 - 2 * value)


def _ease_integral(curve: TransitionCurve, value: float) -> float:
    """Return the definite integral of ``_ease`` from 0 to ``value``.

    trace_time and rotation_time accumulate a *rate* over the whole song, so a
    transition has to contribute the area under its curve, not the curve's
    value. Getting this wrong shifts the phase of every trace after the first
    scene change, which reads as the animation jumping rather than easing.
    """
    value = _clamp01(value)
    if curve == "cut":
        return value
    if curve == "linear":
        return value**2 / 2
    if curve == "ease_in":
        return value**3 / 3
    if curve == "ease_out":
        return value**2 - value**3 / 3
    return value**3 - 0.5 * value**4


def _transition_for(
    section_type: str,
    section_id: str,
    visuals: VisualConfig | None,
    default_seconds: float,
) -> tuple[float, TransitionCurve, TransitionGap]:
    """Resolve one scene's transition, exact scene beating type beating track."""
    configured = None
    if visuals is not None:
        configured = visuals.transition_overrides.get(section_id)
        if configured is None:
            folded = section_type.casefold()
            configured = next(
                (
                    candidate
                    for name, candidate in visuals.section_transitions.items()
                    if name.casefold() == folded
                ),
                None,
            )
    if configured is None:
        return default_seconds, "smooth", SceneTransitionConfig().gap
    seconds = (
        default_seconds if configured.seconds is None else configured.seconds
    )
    return seconds, configured.curve, configured.gap


def _transition_plan(
    sections: list[Any],
    index: int,
    visuals: VisualConfig | None,
    default_seconds: float,
) -> tuple[float, float, TransitionCurve]:
    """Return when a scene's transition begins, how long it runs, and its curve.

    Alignment leaves uncovered time between scenes, which the renderer fills by
    holding the preceding scene. A gap-covering transition starts early — in
    the hole rather than inside the new scene — so the change happens over the
    dead air instead of after it.
    """
    section = sections[index]
    seconds, curve, gap_mode = _transition_for(
        section.type,
        section.id,
        visuals,
        default_seconds,
    )
    if index == 0:
        return section.start, seconds, curve
    gap_start = sections[index - 1].end
    gap = section.start - gap_start
    if gap_mode == "hold" or gap <= GAP_EPSILON_SECONDS:
        return section.start, seconds, curve
    if gap_mode == "span":
        # Arrive exactly as the scene starts, however wide the hole is.
        return gap_start, max(seconds, gap), curve
    return gap_start, seconds, curve


def _configured_style(
    style: SectionStyle,
    configured: SectionVisualStyleConfig | None,
) -> SectionStyle:
    if configured is None:
        return style
    updates = {
        item.name: value
        for item in fields(SectionStyle)
        if (value := getattr(configured, item.name, None)) is not None
    }
    if configured.visible_roles is not None:
        updates["visible_roles"] = tuple(configured.visible_roles)
    return replace(style, **updates)


def _type_configuration(
    visuals: VisualConfig | None,
    section_type: str,
) -> SectionVisualStyleConfig | None:
    if visuals is None:
        return None
    folded = section_type.casefold()
    return next(
        (
            configured
            for name, configured in visuals.section_styles.items()
            if name.casefold() == folded
        ),
        None,
    )


def _style_for(
    section_type: str,
    section_id: str,
    visuals: VisualConfig | None,
) -> SectionStyle:
    style = _SECTION_STYLES.get(section_type.casefold(), _DEFAULT_STYLE)
    style = _configured_style(style, _type_configuration(visuals, section_type))
    override = visuals.section_overrides.get(section_id) if visuals else None
    return _configured_style(style, override)


def _interpolate_style(
    previous: SectionStyle,
    current: SectionStyle,
    amount: float,
) -> SectionStyle:
    def blend(start: float, end: float) -> float:
        return start + (end - start) * amount

    numeric = {
        item.name: blend(getattr(previous, item.name), getattr(current, item.name))
        for item in fields(SectionStyle)
        if item.name != "visible_roles"
    }
    return SectionStyle(**numeric, visible_roles=current.visible_roles)


def _role_visibility(
    previous: SectionStyle,
    current: SectionStyle,
    amount: float,
) -> dict[str, float]:
    return {
        role: (1 if role in previous.visible_roles else 0) * (1 - amount)
        + (1 if role in current.visible_roles else 0) * amount
        for role in _VISUAL_ROLES
    }


def _transition_integral(
    previous: float,
    current: float,
    elapsed: float,
    transition_seconds: float,
    curve: TransitionCurve = "smooth",
) -> float:
    if elapsed <= 0:
        return 0
    if transition_seconds <= 0 or curve == "cut":
        return current * elapsed
    transition_elapsed = min(elapsed, transition_seconds)
    progress = transition_elapsed / transition_seconds
    total = previous * transition_elapsed
    total += (
        (current - previous) * transition_seconds * _ease_integral(curve, progress)
    )
    if elapsed > transition_seconds:
        total += current * (elapsed - transition_seconds)
    return total


def _integrated_style_value(
    lyrics: AlignedLyrics,
    time_seconds: float,
    *,
    transition_seconds: float,
    visuals: VisualConfig | None,
    value: str,
) -> float:
    if time_seconds <= 0:
        return 0
    total = 0.0
    sections = lyrics.sections
    for index, section in enumerate(sections):
        # Intervals are bounded by where each transition *begins*, not by the
        # scene starts, so a gap-covering transition integrates over the same
        # span it animates over. Anything else shifts the trace phase.
        interval_start = (
            0.0
            if index == 0
            else _transition_plan(sections, index, visuals, transition_seconds)[0]
        )
        interval_end = (
            _transition_plan(sections, index + 1, visuals, transition_seconds)[0]
            if index + 1 < len(sections)
            else time_seconds
        )
        elapsed = min(
            max(0.0, time_seconds - interval_start),
            max(0.0, interval_end - interval_start),
        )
        if elapsed <= 0:
            if time_seconds < interval_start:
                break
            continue
        current = _style_for(section.type, section.id, visuals)
        previous = (
            _style_for(sections[index - 1].type, sections[index - 1].id, visuals)
            if index > 0
            else current
        )
        if value == "rotation":
            previous_value = previous.motion * previous.rotation_direction
            current_value = current.motion * current.rotation_direction
        else:
            previous_value = getattr(previous, value)
            current_value = getattr(current, value)
        _begin, seconds, curve = _transition_plan(
            sections,
            index,
            visuals,
            transition_seconds,
        )
        total += _transition_integral(
            previous_value,
            current_value,
            elapsed,
            seconds,
            curve,
        )
        if time_seconds < interval_end:
            break
    return total


def choreography_at(
    lyrics: AlignedLyrics,
    time_seconds: float,
    *,
    transition_seconds: float,
    visuals: VisualConfig | None = None,
) -> ChoreographyState:
    """Return an interpolated, manifest-configurable visual preset."""
    sections = lyrics.sections
    index = 0
    for candidate, section in enumerate(sections):
        if time_seconds >= section.start:
            index = candidate
        if section.start <= time_seconds < section.end:
            index = candidate
            break
        if time_seconds < section.start:
            break

    # A scene whose transition covers the gap before it takes that gap over:
    # the plain scan above hands uncovered time to the scene that just ended.
    if index + 1 < len(sections):
        begin = _transition_plan(sections, index + 1, visuals, transition_seconds)[0]
        if begin <= time_seconds < sections[index + 1].start:
            index += 1

    section = sections[index]
    duration = section.end - section.start
    section_progress = _clamp01((time_seconds - section.start) / duration)
    current = _style_for(section.type, section.id, visuals)
    previous = (
        _style_for(sections[index - 1].type, sections[index - 1].id, visuals)
        if index > 0
        else current
    )
    begin, seconds, curve = _transition_plan(
        sections,
        index,
        visuals,
        transition_seconds,
    )
    transition_progress = 1.0
    if index > 0 and seconds > 0 and curve != "cut":
        transition_progress = _ease(curve, (time_seconds - begin) / seconds)
    interpolated = _interpolate_style(previous, current, transition_progress)

    return ChoreographyState(
        section_id=section.id,
        section_type=section.type,
        section_label=section.label,
        section_progress=section_progress,
        transition_progress=transition_progress,
        layer_fraction=interpolated.layer_fraction,
        scale=interpolated.scale,
        motion=interpolated.motion,
        color_intensity=interpolated.color_intensity,
        onset_response=interpolated.onset_response,
        rotation_direction=interpolated.rotation_direction,
        palette_shift=interpolated.palette_shift,
        lyrics_opacity=interpolated.lyrics_opacity,
        spatial_spread=interpolated.spatial_spread,
        anchor_drift=interpolated.anchor_drift,
        trace_speed=interpolated.trace_speed,
        trail_length=interpolated.trail_length,
        beat_gain=interpolated.beat_gain,
        intensity_gain=interpolated.intensity_gain,
        trace_time=_integrated_style_value(
            lyrics,
            time_seconds,
            transition_seconds=transition_seconds,
            visuals=visuals,
            value="trace_speed",
        ),
        rotation_time=_integrated_style_value(
            lyrics,
            time_seconds,
            transition_seconds=transition_seconds,
            visuals=visuals,
            value="rotation",
        ),
        role_visibility=_role_visibility(previous, current, transition_progress),
        previous_section_id=sections[index - 1].id if index > 0 else None,
    )
