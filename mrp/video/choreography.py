from dataclasses import dataclass, field, fields, replace

from mrp.video.project import (
    AlignedLyrics,
    SectionVisualStyleConfig,
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


def _smoothstep(value: float) -> float:
    value = _clamp01(value)
    return value * value * (3 - 2 * value)


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
) -> float:
    if elapsed <= 0:
        return 0
    if transition_seconds <= 0:
        return current * elapsed
    transition_elapsed = min(elapsed, transition_seconds)
    progress = transition_elapsed / transition_seconds
    smoothstep_integral = progress**3 - 0.5 * progress**4
    total = previous * transition_elapsed
    total += (
        (current - previous) * transition_seconds * smoothstep_integral
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
        interval_start = 0.0 if index == 0 else section.start
        interval_end = (
            sections[index + 1].start
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
        total += _transition_integral(
            previous_value,
            current_value,
            elapsed,
            transition_seconds,
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

    section = sections[index]
    duration = section.end - section.start
    section_progress = _clamp01((time_seconds - section.start) / duration)
    current = _style_for(section.type, section.id, visuals)
    previous = (
        _style_for(sections[index - 1].type, sections[index - 1].id, visuals)
        if index > 0
        else current
    )
    transition_progress = 1.0
    if index > 0 and transition_seconds > 0:
        raw_transition = (time_seconds - section.start) / transition_seconds
        transition_progress = _smoothstep(raw_transition)
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
