import math
from dataclasses import dataclass

from mrp.video.analysis import AnalysisBundle
from mrp.video.choreography import ChoreographyState
from mrp.video.presets import MappingPreset, get_mapping_preset
from mrp.video.project import AudioSignal, VisualLayerConfig


@dataclass(frozen=True, slots=True)
class SemanticSample:
    energy: float
    accent: float


@dataclass(frozen=True, slots=True)
class AudioVisualState:
    master: SemanticSample
    drums: SemanticSample
    bass: SemanticSample
    vocals: SemanticSample
    instruments: SemanticSample
    spectral_centroid: float

    def for_role(self, role: str) -> SemanticSample:
        return getattr(self, role)


@dataclass(frozen=True, slots=True)
class LayerFrameState:
    scale: float
    rotation_radians: float
    trail_fraction: float
    opacity: float
    line_width: float
    hue_shift_degrees: float
    color_intensity: float
    beat_pulse: float


_ROLE_SCALE_RESPONSE = {
    "master": 0.1,
    "drums": 0.06,
    "bass": 0.2,
    "vocals": 0.1,
    "instruments": 0.13,
}
_ROLE_VISIBILITY_THRESHOLD = {
    "vocals": 0.2,
    "instruments": 0.38,
    "master": 0.48,
    "bass": 0.62,
    "drums": 0.82,
}


def _clamp(value: float, lower: float = 0, upper: float = 1) -> float:
    return min(upper, max(lower, value))


def _sample_semantic(
    analysis: AnalysisBundle,
    role: str,
    time_seconds: float,
) -> SemanticSample:
    control = analysis.semantic_controls[role]
    features = analysis.tracks[control.track].sample(time_seconds)
    return SemanticSample(
        energy=_clamp(features[control.energy_feature]),
        accent=_clamp(features[control.accent_feature]),
    )


def sample_audio_visual_state(
    analysis: AnalysisBundle,
    time_seconds: float,
) -> AudioVisualState:
    master_features = analysis.tracks["master"].sample(time_seconds)
    return AudioVisualState(
        master=_sample_semantic(analysis, "master", time_seconds),
        drums=_sample_semantic(analysis, "drums", time_seconds),
        bass=_sample_semantic(analysis, "bass", time_seconds),
        vocals=_sample_semantic(analysis, "vocals", time_seconds),
        instruments=_sample_semantic(analysis, "instruments", time_seconds),
        spectral_centroid=_clamp(master_features["spectral_centroid"]),
    )


def _driver_value(
    audio: AudioVisualState,
    signal: AudioSignal | None,
    *,
    fallback_role: str,
    fallback_feature: str,
) -> tuple[float, str]:
    if signal is None:
        role = fallback_role
        feature = fallback_feature
    else:
        role, feature = signal.split(".", maxsplit=1)
    return getattr(audio.for_role(role), feature), role


def map_layer_state(
    layer: VisualLayerConfig,
    audio: AudioVisualState,
    choreography: ChoreographyState,
    time_seconds: float,
    preset: MappingPreset | None = None,
    visibility_override: float | None = None,
) -> LayerFrameState:
    """Map smoothed semantic audio controls to stable curve transforms/styles."""
    preset = preset or get_mapping_preset("balanced")
    role = audio.for_role(layer.role)
    scale_energy, scale_role = _driver_value(
        audio,
        layer.drivers.scale,
        fallback_role=layer.role,
        fallback_feature="energy",
    )
    scale_gain = preset.role_gains[scale_role]
    scale_response = _ROLE_SCALE_RESPONSE[scale_role] * preset.scale_response
    scale = (
        layer.base_scale
        * choreography.scale
        * (1 + scale_response * scale_energy * scale_gain)
    )

    if visibility_override is not None:
        visibility = _clamp(visibility_override)
    elif choreography.role_visibility:
        visibility_threshold = _ROLE_VISIBILITY_THRESHOLD[layer.role]
        visibility_threshold -= preset.visibility_bias
        layer_visibility = _clamp(
            (choreography.layer_fraction - visibility_threshold) / 0.18
        )
        visibility = choreography.role_visibility.get(layer.role, 0) * layer_visibility
    else:
        visibility_threshold = _ROLE_VISIBILITY_THRESHOLD[layer.role]
        visibility_threshold -= preset.visibility_bias
        visibility = _clamp((choreography.layer_fraction - visibility_threshold) / 0.18)
    opacity_energy, opacity_role = _driver_value(
        audio,
        layer.drivers.opacity,
        fallback_role=layer.role,
        fallback_feature="energy",
    )
    opacity_gain = preset.role_gains[opacity_role]
    pulse_value, pulse_role = _driver_value(
        audio,
        layer.drivers.pulse,
        fallback_role=layer.role,
        fallback_feature="accent",
    )
    pulse_gain = preset.role_gains[pulse_role]
    energy_opacity = 0.58 + 0.42 * max(
        opacity_energy * (opacity_gain if layer.drivers.opacity else 1),
        pulse_value * (pulse_gain if layer.drivers.pulse else 1) * 0.75,
    )
    opacity = layer.opacity * visibility * energy_opacity * preset.opacity_response
    if layer.drivers.opacity is None and layer.depth == "background":
        intensity_energy = audio.master.energy
        opacity *= 0.35 + 1.1 * _clamp(intensity_energy * choreography.intensity_gain)

    accent = (
        pulse_value
        if layer.drivers.pulse is not None
        else max(role.accent, audio.drums.accent * 0.35)
    )
    line_width = layer.line_width * (
        1
        + choreography.onset_response
        * preset.onset_response
        * accent
        * pulse_gain
        * 1.4
    )
    rotation = math.radians(layer.rotation_degrees_per_second)
    rotation *= choreography.rotation_time * preset.motion_response * scale_gain
    rotation += math.sin(
        time_seconds * 0.37 + scale_energy * math.pi
    ) * math.radians(layer.rotation_wobble_degrees)

    trail_fraction = (
        layer.trace.trail_fraction
        * (0.82 + 0.18 * choreography.motion)
        * (0.9 + 0.1 * scale_energy * scale_gain)
        * choreography.trail_length
    )

    if layer.drivers.color is None:
        color_energy = audio.vocals.energy
        intensity_energy = (
            audio.master.energy if layer.depth == "background" else role.energy
        )
        color_gain = preset.role_gains[layer.role]
    else:
        color_energy, color_role = _driver_value(
            audio,
            layer.drivers.color,
            fallback_role="vocals",
            fallback_feature="energy",
        )
        intensity_energy = color_energy
        color_gain = preset.role_gains[color_role]
    hue_shift = (
        layer.hue_shift_degrees
        + choreography.palette_shift * 360
        + color_energy * 18 * preset.hue_response
        + audio.spectral_centroid * 12 * preset.hue_response
    )
    beat_pulse = 0.0
    if layer.drivers.pulse is not None or layer.role == "drums":
        beat_pulse = _clamp(
            pulse_value**1.35
            * choreography.onset_response
            * preset.onset_response
            * choreography.beat_gain
        )
        opacity *= 1 + beat_pulse * 0.35
    energy_color_response = (
        0.55
        + 0.75 * _clamp(intensity_energy * choreography.intensity_gain) * color_gain
    )
    return LayerFrameState(
        scale=scale,
        rotation_radians=rotation,
        trail_fraction=_clamp(trail_fraction, 0.02, 1),
        opacity=_clamp(opacity),
        line_width=max(0.25, line_width),
        hue_shift_degrees=hue_shift,
        color_intensity=_clamp(
            choreography.color_intensity * energy_color_response,
            0.2,
            1.4,
        ),
        beat_pulse=beat_pulse,
    )
