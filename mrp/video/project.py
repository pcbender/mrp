import json
import math
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

NonBlankText = Annotated[str, Field(min_length=1)]
ActorId = Annotated[
    str,
    Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
HexColor = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
VisualRole = Literal["master", "drums", "bass", "vocals", "instruments"]
AudioSignal = Literal[
    "master.energy",
    "master.accent",
    "drums.energy",
    "drums.accent",
    "bass.energy",
    "bass.accent",
    "vocals.energy",
    "vocals.accent",
    "instruments.energy",
    "instruments.accent",
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AudioConfig(ContractModel):
    master: Path
    stems: dict[NonBlankText, Path] = Field(default_factory=dict)
    duration_tolerance: float = Field(default=0.05, ge=0, le=5)

    @model_validator(mode="after")
    def master_is_not_a_stem_name(self) -> "AudioConfig":
        if "master" in self.stems:
            raise ValueError("'master' is reserved and cannot be used as a stem name")
        return self


class LyricsConfig(ContractModel):
    source: Path
    aligned: Path | None = None
    language: NonBlankText


class CardConfig(ContractModel):
    file: Path
    duration: float = Field(gt=0)
    fit: Literal["contain", "cover"] = "contain"
    fade: float = Field(default=0, ge=0)
    background: HexColor = "#101014"

    @model_validator(mode="after")
    def fade_fits_duration(self) -> "CardConfig":
        if self.fade > self.duration:
            raise ValueError("fade must not exceed card duration")
        return self


class CardsConfig(ContractModel):
    opening: CardConfig
    closing: CardConfig


class VideoConfig(ContractModel):
    width: int = Field(default=1920, gt=0)
    height: int = Field(default=1080, gt=0)
    fps: float = Field(default=30, gt=0, le=240)
    background: HexColor = "#101014"
    seed: int = 4821

    @model_validator(mode="after")
    def dimensions_support_yuv420p(self) -> "VideoConfig":
        if self.width % 2 or self.height % 2:
            raise ValueError("video width and height must be even for yuv420p output")
        return self


class EncodingConfig(ContractModel):
    video_codec: Literal["libx264"] = "libx264"
    pixel_format: Literal["yuv420p"] = "yuv420p"
    crf: int = Field(default=18, ge=0, le=51)
    preset: Literal[
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ] = "medium"
    threads: int = Field(default=1, ge=1, le=32)
    audio_codec: Literal["aac"] = "aac"
    audio_bitrate_kbps: int = Field(default=192, ge=64, le=512)
    audio_sample_rate: Literal[48000] = 48000
    audio_channels: Literal[2] = 2
    faststart: Literal[True] = True
    duration_tolerance: float = Field(default=0.15, gt=0, le=2)


class TextConfig(ContractModel):
    font: Path
    size: int = Field(default=60, gt=0)
    maximum_width_fraction: float = Field(default=0.82, ge=0.2, le=0.95)
    position: Literal["top", "center", "bottom"] = "bottom"
    active_color: HexColor = "#ffffff"


class AnalysisConfig(ContractModel):
    sample_rate: int = Field(default=22050, ge=8000, le=192000)
    frame_length: int = Field(default=2048, ge=256, le=16384)
    hop_length: int = Field(default=512, ge=1)
    low_cutoff_hz: float = Field(default=250, gt=0)
    high_cutoff_hz: float = Field(default=2000, gt=0)
    percentile_low: float = Field(default=5, ge=0, le=100)
    percentile_high: float = Field(default=95, ge=0, le=100)
    attack_seconds: float = Field(default=0.05, gt=0, le=10)
    release_seconds: float = Field(default=0.25, gt=0, le=30)
    vocal_activity_threshold: float = Field(default=0.15, ge=0, le=1)
    cache_dir: Path = Path("build/cache/analysis")

    @model_validator(mode="after")
    def settings_are_consistent(self) -> "AnalysisConfig":
        if self.frame_length & (self.frame_length - 1):
            raise ValueError("frame_length must be a power of two")
        if self.hop_length > self.frame_length:
            raise ValueError("hop_length must not exceed frame_length")
        if self.low_cutoff_hz >= self.high_cutoff_hz:
            raise ValueError("low_cutoff_hz must be below high_cutoff_hz")
        if self.high_cutoff_hz >= self.sample_rate / 2:
            raise ValueError("high_cutoff_hz must be below the Nyquist frequency")
        if self.percentile_low >= self.percentile_high:
            raise ValueError("percentile_low must be below percentile_high")
        if self.cache_dir.is_absolute():
            raise ValueError("cache_dir must be relative to the project manifest")
        return self


class AlignmentConfig(ContractModel):
    model: Literal["whisper-1"] = "whisper-1"
    cache_dir: Path = Path("build/cache/alignment")
    min_token_similarity: float = Field(default=0.72, ge=0, le=1)
    matched_confidence: float = Field(default=0.75, ge=0, le=1)
    max_tail_seconds: float = Field(default=0.75, ge=0, le=5)
    activity_threshold: float = Field(default=0.2, ge=0, le=1)
    upload_bitrate_kbps: int = Field(default=128, ge=64, le=320)

    @model_validator(mode="after")
    def settings_are_consistent(self) -> "AlignmentConfig":
        if self.cache_dir.is_absolute():
            raise ValueError("cache_dir must be relative to the project manifest")
        return self


GeometryFamily = Literal[
    "spirogram", "lissajous", "rose", "superformula", "path", "harmonograph", "text"
]

_FAMILY_FIELDS: dict[str, dict[str, Any]] = {
    "spirogram": {},  # trochoid fields are required, not defaulted
    "lissajous": {"liss_freq_x": 3, "liss_freq_y": 2, "liss_delta": math.pi / 2},
    "rose": {"rose_n": 5, "rose_d": 1},
    "superformula": {"sf_m": 6, "sf_n1": 0.3, "sf_n2": 0.3, "sf_n3": 0.3},
    "path": {},  # path_data is required, not defaulted
    "harmonograph": {
        "harm_freq_x": 3.01,
        "harm_freq_y": 2.0,
        "harm_delta": math.pi / 2,
        "harm_damping": 0.02,
        "harm_turns": 12,
    },
    "text": {},  # path_data is required, not defaulted
}
# Families whose geometry is one or more SVG subpaths in ``path_data``.
_PATH_FAMILIES = ("path", "text")
_TROCHOID_FIELDS = ("fixed_radius", "moving_radius", "pen_offset")

_PATH_DATA_CHARS = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE\s,.+-]+$")


def _validate_path_data(value: str) -> None:
    """Syntactic screen for one SVG subpath; geometric parsing waits for trace time."""
    data = value.strip()
    if data[0] not in "Mm":
        raise ValueError("path_data must start with an M or m command")
    if not _PATH_DATA_CHARS.match(data):
        raise ValueError("path_data contains characters outside the SVG path grammar")
    if sum(1 for char in data if char in "Mm") != 1:
        raise ValueError(
            "path_data must hold exactly one subpath (a single M command); "
            "split multi-subpath files with the SVG import"
        )


def _validate_text_data(value: str) -> None:
    """Syntactic screen for a text mark: one or more SVG subpaths."""
    data = value.strip()
    if data[0] not in "Mm":
        raise ValueError("path_data must start with an M or m command")
    if not _PATH_DATA_CHARS.match(data):
        raise ValueError("path_data contains characters outside the SVG path grammar")
    if not any(char in "Mm" for char in data):
        raise ValueError("text path_data must hold at least one subpath (an M command)")


class LayerGeometryConfig(ContractModel):
    """One curve family per layer; family-specific fields stay None elsewhere.

    A single widened model (not a discriminated union) so legacy geometry
    dicts without a ``family`` key remain valid spirograms.
    """

    family: GeometryFamily = "spirogram"
    # spirogram (trochoid) — required when family == "spirogram"
    fixed_radius: float | None = Field(default=None, gt=0)
    moving_radius: float | None = Field(default=None, gt=0)
    pen_offset: float | None = Field(default=None, ge=0)
    rotation: Literal["inside", "outside"] = "inside"
    # shared by every family: parameter start offset + sample count
    phase: float = 0.0
    samples: int = Field(default=900, ge=64, le=8192)
    # lissajous: x = sin(a*theta + delta), y = sin(b*theta)
    liss_freq_x: int | None = Field(default=None, ge=1, le=12)
    liss_freq_y: int | None = Field(default=None, ge=1, le=12)
    liss_delta: float | None = Field(default=None, ge=0, le=6.2832)
    # rose: r = cos((n/d) * theta)
    rose_n: int | None = Field(default=None, ge=1, le=12)
    rose_d: int | None = Field(default=None, ge=1, le=9)
    # superformula (Gielis, a = b = 1)
    sf_m: int | None = Field(default=None, ge=0, le=24)
    sf_n1: float | None = Field(default=None, ge=0.1, le=40)
    sf_n2: float | None = Field(default=None, ge=0.1, le=40)
    sf_n3: float | None = Field(default=None, ge=0.1, le=40)
    # path / text: SVG d attribute(s), resampled by arc length. path holds one
    # subpath; text holds a whole word (one subpath per letter-contour).
    path_data: str | None = Field(default=None, max_length=200000)
    # harmonograph: damped lissajous, ping-ponged closed (fractional
    # frequencies detune the pendulums, which is what makes the figure precess)
    harm_freq_x: float | None = Field(default=None, ge=1, le=12)
    harm_freq_y: float | None = Field(default=None, ge=1, le=12)
    harm_delta: float | None = Field(default=None, ge=0, le=6.2832)
    harm_damping: float | None = Field(default=None, ge=0, le=0.2)
    harm_turns: int | None = Field(default=None, ge=1, le=30)

    @model_validator(mode="after")
    def family_fields_are_consistent(self) -> "LayerGeometryConfig":
        if self.family == "spirogram":
            for name in _TROCHOID_FIELDS:
                if getattr(self, name) is None:
                    raise ValueError(f"spirogram geometry requires {name}")
        else:
            for name in _TROCHOID_FIELDS:
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"{self.family} geometry does not accept {name}"
                    )
        if self.family in _PATH_FAMILIES:
            if self.path_data is None or not self.path_data.strip():
                raise ValueError(f"{self.family} geometry requires path_data")
            if self.family == "text":
                _validate_text_data(self.path_data)
            else:
                _validate_path_data(self.path_data)
        elif self.path_data is not None:
            raise ValueError(f"{self.family} geometry does not accept path_data")
        for family, defaults in _FAMILY_FIELDS.items():
            for name, default in defaults.items():
                value = getattr(self, name)
                if family == self.family:
                    if value is None:
                        setattr(self, name, default)
                elif value is not None:
                    raise ValueError(
                        f"{self.family} geometry does not accept {name}"
                    )
        return self


class LayerTraceConfig(ContractModel):
    cycles_per_second: float = Field(default=0.08, gt=0, le=2)
    trail_fraction: float = Field(default=0.24, gt=0, le=1)
    ghost_count: int = Field(default=1, ge=0, le=6)
    ghost_spacing: float = Field(default=0.08, ge=0, le=1)
    head_radius: float = Field(default=3, ge=0, le=24)


class SectionVisualStyleConfig(ContractModel):
    visible_roles: list[VisualRole] | None = Field(default=None, max_length=5)
    layer_fraction: float | None = Field(default=None, ge=0, le=1)
    scale: float | None = Field(default=None, ge=0.2, le=2)
    motion: float | None = Field(default=None, ge=0, le=3)
    color_intensity: float | None = Field(default=None, ge=0.2, le=2)
    onset_response: float | None = Field(default=None, ge=0, le=3)
    rotation_direction: float | None = Field(default=None, ge=-1, le=1)
    palette_shift: float | None = Field(default=None, ge=-1, le=1)
    lyrics_opacity: float | None = Field(default=None, ge=0, le=1)
    spatial_spread: float | None = Field(default=None, ge=0.2, le=2)
    anchor_drift: float | None = Field(default=None, ge=0, le=0.2)
    trace_speed: float | None = Field(default=None, ge=0.1, le=3)
    trail_length: float | None = Field(default=None, ge=0.1, le=3)
    beat_gain: float | None = Field(default=None, ge=0, le=3)
    intensity_gain: float | None = Field(default=None, ge=0, le=3)

    @model_validator(mode="after")
    def visible_roles_are_unique(self) -> "SectionVisualStyleConfig":
        if self.visible_roles is not None:
            duplicates = sorted(
                {
                    role
                    for role in self.visible_roles
                    if self.visible_roles.count(role) > 1
                }
            )
            if duplicates:
                joined = ", ".join(duplicates)
                raise ValueError(f"visible_roles must be unique: {joined}")
        return self


class TraceAudioDriversConfig(ContractModel):
    scale: AudioSignal | None = None
    opacity: AudioSignal | None = None
    color: AudioSignal | None = None
    pulse: AudioSignal | None = None


class LayerColorFlowConfig(ContractModel):
    """Per-point hue motion along the trace, centered on the layer's base color.

    The base hue always comes from the resolved layer color (a scene's palette
    preset by role, or the layer's own hex outside a production), so an actor
    keeps its color character while adopting each production's palette.
    """

    source: Literal["angle", "radius", "velocity", "curvature"]
    swing_degrees: float = Field(default=90, gt=0, le=360)


class VisualLayerConfig(ContractModel):
    id: NonBlankText
    role: VisualRole
    geometry: LayerGeometryConfig
    trace: LayerTraceConfig = Field(default_factory=LayerTraceConfig)
    color: HexColor
    color_flow: LayerColorFlowConfig | None = None
    depth: Literal["background", "foreground"] = "foreground"
    anchor_x: float = Field(default=0.5, ge=-0.5, le=1.5)
    anchor_y: float = Field(default=0.5, ge=-0.5, le=1.5)
    base_scale: float = Field(default=1, gt=0, le=2)
    opacity: float = Field(default=0.8, ge=0, le=1)
    line_width: float = Field(default=2, gt=0, le=20)
    rotation_degrees_per_second: float = Field(default=0, ge=-180, le=180)
    hue_shift_degrees: float = Field(default=0, ge=-360, le=360)
    blend_mode: Literal["normal", "screen"] = "screen"
    drivers: TraceAudioDriversConfig = Field(default_factory=TraceAudioDriversConfig)


class CastingConfig(ContractModel):
    source: Literal["auto", "ai", "manual"] = "manual"
    seed: int | None = None
    generator_version: int = Field(default=1, ge=1)


class SectionCompositionConfig(ContractModel):
    casting: CastingConfig = Field(default_factory=CastingConfig)
    traces: list[VisualLayerConfig] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def trace_ids_are_unique(self) -> "SectionCompositionConfig":
        ids = [trace.id for trace in self.traces]
        duplicates = sorted({trace_id for trace_id in ids if ids.count(trace_id) > 1})
        if duplicates:
            joined = ", ".join(duplicates)
            raise ValueError(f"composition trace ids must be unique: {joined}")
        return self


class ActorLibrarySourceConfig(ContractModel):
    """Provenance for a project-pinned copy of a reusable library actor."""

    actor_id: ActorId
    revision: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ActorConfig(ContractModel):
    """A track actor: pinned visual identity plus its musical character."""

    id: ActorId
    name: NonBlankText
    description: str = ""
    kind: Literal["spirogram"] = "spirogram"
    character: VisualRole | None = None
    components: list[VisualLayerConfig] = Field(min_length=1, max_length=9)
    library_source: ActorLibrarySourceConfig | None = None

    @model_validator(mode="after")
    def component_ids_are_unique(self) -> "ActorConfig":
        ids = [component.id for component in self.components]
        duplicates = sorted(
            {component_id for component_id in ids if ids.count(component_id) > 1}
        )
        if duplicates:
            joined = ", ".join(duplicates)
            raise ValueError(f"actor component ids must be unique: {joined}")
        return self


class ActorDirectionConfig(ContractModel):
    """Scene-specific direction that leaves the actor's identity intact."""

    anchor_x: float | None = Field(default=None, ge=-0.5, le=1.5)
    anchor_y: float | None = Field(default=None, ge=-0.5, le=1.5)
    scale: float = Field(default=1, gt=0, le=3)
    opacity: float = Field(default=1, ge=0, le=1)
    rotation_offset_degrees_per_second: float = Field(
        default=0,
        ge=-180,
        le=180,
    )
    hue_shift_degrees: float = Field(default=0, ge=-360, le=360)
    depth: Literal["background", "foreground"] | None = None
    visible: bool = True


class ActorAssignmentConfig(ContractModel):
    id: ActorId
    actor: ActorId
    direction: ActorDirectionConfig = Field(default_factory=ActorDirectionConfig)


class ActorCastConfig(ContractModel):
    casting: CastingConfig = Field(default_factory=CastingConfig)
    actors: list[ActorAssignmentConfig] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def assignment_ids_are_unique(self) -> "ActorCastConfig":
        ids = [assignment.id for assignment in self.actors]
        duplicates = sorted(
            {assignment_id for assignment_id in ids if ids.count(assignment_id) > 1}
        )
        if duplicates:
            joined = ", ".join(duplicates)
            raise ValueError(f"actor assignment ids must be unique: {joined}")
        return self


class ActorLibraryDocument(ContractModel):
    version: Literal[1] = 1
    actor: ActorConfig


def _default_visual_layers() -> list[VisualLayerConfig]:
    return [
        VisualLayerConfig(
            id="instrument-haze",
            role="instruments",
            geometry=LayerGeometryConfig(
                fixed_radius=192,
                moving_radius=48,
                pen_offset=112,
                samples=1800,
            ),
            trace=LayerTraceConfig(
                cycles_per_second=0.018,
                trail_fraction=0.54,
                ghost_count=3,
                ghost_spacing=0.07,
                head_radius=0,
            ),
            color="#8c5cff",
            depth="background",
            anchor_x=0.52,
            anchor_y=0.38,
            base_scale=1.82,
            opacity=0.16,
            line_width=1.2,
            rotation_degrees_per_second=-0.35,
            hue_shift_degrees=18,
        ),
        VisualLayerConfig(
            id="bass-orbit",
            role="bass",
            geometry=LayerGeometryConfig(
                fixed_radius=233,
                moving_radius=89,
                pen_offset=144,
                rotation="outside",
                samples=1400,
            ),
            trace=LayerTraceConfig(
                cycles_per_second=0.045,
                trail_fraction=0.18,
                ghost_count=1,
                ghost_spacing=0.1,
                head_radius=3.5,
            ),
            color="#4c78ff",
            anchor_x=0.14,
            anchor_y=0.44,
            base_scale=0.6,
            opacity=0.74,
            line_width=2.2,
            rotation_degrees_per_second=0.8,
        ),
        VisualLayerConfig(
            id="vocal-flower",
            role="vocals",
            geometry=LayerGeometryConfig(
                fixed_radius=180,
                moving_radius=65,
                pen_offset=95,
                samples=900,
            ),
            trace=LayerTraceConfig(
                cycles_per_second=0.068,
                trail_fraction=0.28,
                ghost_count=1,
                ghost_spacing=0.09,
                head_radius=4,
            ),
            color="#ff5fd2",
            anchor_x=0.52,
            anchor_y=0.34,
            base_scale=0.48,
            opacity=0.82,
            line_width=2.4,
            rotation_degrees_per_second=-1.25,
            hue_shift_degrees=-12,
        ),
        VisualLayerConfig(
            id="drum-spark",
            role="drums",
            geometry=LayerGeometryConfig(
                fixed_radius=96,
                moving_radius=32,
                pen_offset=50,
                rotation="outside",
                samples=720,
            ),
            trace=LayerTraceConfig(
                cycles_per_second=0.12,
                trail_fraction=0.3,
                ghost_count=1,
                ghost_spacing=0.07,
                head_radius=4,
            ),
            color="#ffd166",
            anchor_x=0.89,
            anchor_y=0.46,
            base_scale=0.54,
            opacity=0.72,
            line_width=1.6,
            rotation_degrees_per_second=2.4,
            hue_shift_degrees=10,
        ),
    ]


class VisualConfig(ContractModel):
    mapping_preset: Literal[
        "balanced",
        "restrained",
        "kinetic",
        "vocal-focus",
    ] = "balanced"
    palette_preset: Literal[
        "layer",
        "aurora",
        "ember",
        "ocean",
        "monochrome",
    ] = "layer"
    palette: list[HexColor] = Field(default_factory=list, max_length=16)
    layers: list[VisualLayerConfig] = Field(default_factory=_default_visual_layers)
    canvas_margin: float = Field(default=0.08, ge=0, le=0.4)
    transition_seconds: float = Field(default=0.65, ge=0, le=10)
    background_response: float = Field(default=0.16, ge=0, le=1)
    lyric_fade_seconds: float = Field(default=0.25, ge=0, le=5)
    section_styles: dict[NonBlankText, SectionVisualStyleConfig] = Field(
        default_factory=dict
    )
    section_overrides: dict[NonBlankText, SectionVisualStyleConfig] = Field(
        default_factory=dict
    )
    auto_casting: bool = True
    section_compositions: dict[NonBlankText, SectionCompositionConfig] = Field(
        default_factory=dict
    )
    composition_overrides: dict[NonBlankText, SectionCompositionConfig] = Field(
        default_factory=dict
    )
    actors: dict[ActorId, ActorConfig] = Field(default_factory=dict)
    section_casts: dict[NonBlankText, ActorCastConfig] = Field(default_factory=dict)
    cast_overrides: dict[NonBlankText, ActorCastConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def layer_ids_are_unique(self) -> "VisualConfig":
        ids = [layer.id for layer in self.layers]
        duplicates = sorted({layer_id for layer_id in ids if ids.count(layer_id) > 1})
        if duplicates:
            joined = ", ".join(duplicates)
            raise ValueError(f"visual layer ids must be unique: {joined}")
        if not self.layers:
            raise ValueError("at least one visual layer is required")
        normalized_types = [key.casefold() for key in self.section_styles]
        type_duplicates = sorted(
            {key for key in normalized_types if normalized_types.count(key) > 1}
        )
        if type_duplicates:
            joined = ", ".join(type_duplicates)
            raise ValueError(f"section style names must be unique: {joined}")
        normalized_compositions = [key.casefold() for key in self.section_compositions]
        composition_duplicates = sorted(
            {
                key
                for key in normalized_compositions
                if normalized_compositions.count(key) > 1
            }
        )
        if composition_duplicates:
            joined = ", ".join(composition_duplicates)
            raise ValueError(f"section composition names must be unique: {joined}")
        actor_mismatches = sorted(
            key for key, actor in self.actors.items() if key != actor.id
        )
        if actor_mismatches:
            joined = ", ".join(actor_mismatches)
            raise ValueError(f"actor mapping keys must match actor ids: {joined}")
        normalized_casts = [key.casefold() for key in self.section_casts]
        cast_duplicates = sorted(
            {key for key in normalized_casts if normalized_casts.count(key) > 1}
        )
        if cast_duplicates:
            joined = ", ".join(cast_duplicates)
            raise ValueError(f"section cast names must be unique: {joined}")
        assignments = [
            assignment
            for cast in (*self.section_casts.values(), *self.cast_overrides.values())
            for assignment in cast.actors
        ]
        missing_actors = sorted(
            {assignment.actor for assignment in assignments if assignment.actor not in self.actors}
        )
        if missing_actors:
            joined = ", ".join(missing_actors)
            raise ValueError(f"actor casts reference unknown actors: {joined}")
        uncastable_actors = sorted(
            {
                assignment.actor
                for assignment in assignments
                if assignment.actor in self.actors
                and self.actors[assignment.actor].character is None
            }
        )
        if uncastable_actors:
            joined = ", ".join(uncastable_actors)
            raise ValueError(f"cast actors require a track-level character: {joined}")
        return self


class ProjectManifest(ContractModel):
    version: Literal[1]
    title: NonBlankText
    audio: AudioConfig
    lyrics: LyricsConfig
    cards: CardsConfig
    video: VideoConfig = Field(default_factory=VideoConfig)
    encoding: EncodingConfig = Field(default_factory=EncodingConfig)
    text: TextConfig
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    alignment: AlignmentConfig = Field(default_factory=AlignmentConfig)
    visuals: VisualConfig = Field(default_factory=VisualConfig)

    @model_validator(mode="after")
    def paths_are_relative(self) -> "ProjectManifest":
        absolute = [
            label for label, path in _declared_paths(self) if path.is_absolute()
        ]
        if absolute:
            joined = ", ".join(absolute)
            message = f"project paths must be relative to the manifest: {joined}"
            raise ValueError(message)
        return self


class LyricLine(ContractModel):
    text: NonBlankText

    @model_validator(mode="after")
    def structure_tags_are_not_cues(self) -> "LyricLine":
        stripped = self.text.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            raise ValueError(
                "structure tags must be section labels, not displayed lyric cues"
            )
        return self


class LyricSection(ContractModel):
    id: NonBlankText
    type: NonBlankText
    label: NonBlankText | None = None
    lines: list[LyricLine] = Field(default_factory=list)

    @model_validator(mode="after")
    def vocal_sections_have_lines(self) -> "LyricSection":
        if self.type != "instrumental" and not self.lines:
            raise ValueError("non-instrumental sections must contain at least one line")
        return self


class StructuredLyrics(ContractModel):
    version: Literal[1]
    sections: list[LyricSection] = Field(min_length=1)

    @model_validator(mode="after")
    def section_ids_are_unique(self) -> "StructuredLyrics":
        _require_unique_section_ids(self.sections)
        return self


class AlignedLyricLine(LyricLine):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["matched", "uncertain", "unmatched"] | None = None
    reviewed: bool | None = None

    @model_validator(mode="after")
    def end_follows_start(self) -> "AlignedLyricLine":
        if self.end <= self.start:
            raise ValueError("line end must be greater than line start")
        return self


class AlignedLyricSection(ContractModel):
    id: NonBlankText
    type: NonBlankText
    label: NonBlankText | None = None
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    reviewed: bool | None = None
    lines: list[AlignedLyricLine] = Field(default_factory=list)

    @model_validator(mode="after")
    def timing_is_consistent(self) -> "AlignedLyricSection":
        if self.end <= self.start:
            raise ValueError("section end must be greater than section start")
        previous_end = self.start
        for line in self.lines:
            if line.start < self.start or line.end > self.end:
                raise ValueError("line timing must fall within its section")
            if line.start < previous_end:
                raise ValueError("line timing must be ordered and non-overlapping")
            previous_end = line.end
        return self


class AlignmentMetadata(ContractModel):
    algorithm_version: Literal[1] = 1
    model: Literal["whisper-1"] = "whisper-1"
    transcription_cache_key: NonBlankText
    source_hash: NonBlankText
    vocals_hash: NonBlankText
    warnings: list[str] = Field(default_factory=list)


class AlignedLyrics(ContractModel):
    version: Literal[1]
    source: Path
    alignment: AlignmentMetadata | None = None
    sections: list[AlignedLyricSection] = Field(min_length=1)

    @model_validator(mode="after")
    def timeline_is_consistent(self) -> "AlignedLyrics":
        _require_unique_section_ids(self.sections)
        previous_end = 0.0
        for section in self.sections:
            if section.start < previous_end:
                raise ValueError("section timing must be ordered and non-overlapping")
            previous_end = section.end
        return self


@dataclass(frozen=True, slots=True)
class ValidationReport:
    manifest_path: Path
    project: ProjectManifest
    lyrics: StructuredLyrics
    master_duration: float
    stem_durations: dict[str, float]


class SpirophonicValidationError(Exception):
    def __init__(self, *problems: str):
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


def _require_unique_section_ids(sections: list[Any]) -> None:
    ids = [section.id for section in sections]
    duplicates = sorted({section_id for section_id in ids if ids.count(section_id) > 1})
    if duplicates:
        joined = ", ".join(duplicates)
        raise ValueError(f"section ids must be unique; duplicates: {joined}")


def _declared_paths(project: ProjectManifest) -> Iterator[tuple[str, Path]]:
    yield "audio.master", project.audio.master
    for name, path in project.audio.stems.items():
        yield f"audio.stems.{name}", path
    yield "lyrics.source", project.lyrics.source
    if project.lyrics.aligned is not None:
        yield "lyrics.aligned", project.lyrics.aligned
    yield "cards.opening.file", project.cards.opening.file
    yield "cards.closing.file", project.cards.closing.file
    yield "text.font", project.text.font


def _required_paths(project: ProjectManifest) -> Iterator[tuple[str, Path]]:
    for label, path in _declared_paths(project):
        if label != "lyrics.aligned":
            yield label, path


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpirophonicValidationError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SpirophonicValidationError(f"malformed YAML in {path}: {exc}") from exc

    if not isinstance(value, dict):
        raise SpirophonicValidationError(f"{path} must contain a YAML mapping")
    return value


def _format_model_errors(path: Path, exc: ValidationError) -> tuple[str, ...]:
    problems: list[str] = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "document"
        problems.append(f"{path}: {location}: {error['msg']}")
    return tuple(problems)


def _load_model[T: BaseModel](path: Path, model_type: type[T]) -> T:
    value = _read_yaml(path)
    try:
        return model_type.model_validate(value)
    except ValidationError as exc:
        raise SpirophonicValidationError(*_format_model_errors(path, exc)) from exc


def load_project_manifest(path: Path) -> ProjectManifest:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SpirophonicValidationError(f"project manifest does not exist: {resolved}")
    return _load_model(resolved, ProjectManifest)


def load_structured_lyrics(path: Path) -> StructuredLyrics:
    return _load_model(path, StructuredLyrics)


def load_aligned_lyrics(path: Path) -> AlignedLyrics:
    return _load_model(path, AlignedLyrics)


def _probe_audio_duration(path: Path, ffprobe: str) -> float:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=duration:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        message = f"ffprobe could not inspect {path}: {exc}"
        raise SpirophonicValidationError(message) from exc

    streams = payload.get("streams", [])
    if not streams:
        raise SpirophonicValidationError(f"no audio stream found in {path}")

    candidates = [streams[0].get("duration"), payload.get("format", {}).get("duration")]
    for candidate in candidates:
        try:
            duration = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(duration) and duration > 0:
            return duration

    raise SpirophonicValidationError(f"no positive audio duration found in {path}")


def validate_project(
    manifest_path: Path,
    *,
    require_tools: bool = True,
    probe_media: bool = True,
    validate_aligned: bool = True,
    duration_probe: Callable[[Path, str], float] | None = None,
) -> ValidationReport:
    resolved_manifest = manifest_path.expanduser().resolve()
    project = load_project_manifest(resolved_manifest)
    root = resolved_manifest.parent
    problems: list[str] = []

    resolved_inputs = {
        label: (root / relative_path).resolve()
        for label, relative_path in _required_paths(project)
    }
    for label, path in resolved_inputs.items():
        if not path.is_file():
            problems.append(f"{label} does not exist or is not a file: {path}")

    ffprobe = shutil.which("ffprobe")
    if require_tools:
        if shutil.which("ffmpeg") is None:
            problems.append("required executable is not on PATH: ffmpeg")
        if ffprobe is None:
            problems.append("required executable is not on PATH: ffprobe")

    lyrics: StructuredLyrics | None = None
    lyrics_path = resolved_inputs["lyrics.source"]
    if lyrics_path.is_file():
        try:
            lyrics = load_structured_lyrics(lyrics_path)
        except SpirophonicValidationError as exc:
            problems.extend(exc.problems)

    if validate_aligned and project.lyrics.aligned is not None:
        aligned_path = (root / project.lyrics.aligned).resolve()
        if aligned_path.exists():
            try:
                load_aligned_lyrics(aligned_path)
            except SpirophonicValidationError as exc:
                problems.extend(exc.problems)

    if problems:
        raise SpirophonicValidationError(*problems)
    if lyrics is None:
        raise SpirophonicValidationError("structured lyrics could not be loaded")

    master_duration = 0.0
    stem_durations: dict[str, float] = {}
    if probe_media:
        if duration_probe is None and ffprobe is None:
            raise SpirophonicValidationError("cannot inspect audio without ffprobe")
        probe = duration_probe or _probe_audio_duration
        probe_executable = ffprobe or "ffprobe"
        master_path = resolved_inputs["audio.master"]
        master_duration = probe(master_path, probe_executable)
        for name in project.audio.stems:
            stem_path = resolved_inputs[f"audio.stems.{name}"]
            duration = probe(stem_path, probe_executable)
            stem_durations[name] = duration
            difference = abs(duration - master_duration)
            if difference > project.audio.duration_tolerance:
                tolerance = project.audio.duration_tolerance
                problems.append(
                    f"audio.stems.{name} duration differs from the master by "
                    f"{difference:.3f}s (tolerance {tolerance:.3f}s)"
                )

    if problems:
        raise SpirophonicValidationError(*problems)

    return ValidationReport(
        manifest_path=resolved_manifest,
        project=project,
        lyrics=lyrics,
        master_duration=master_duration,
        stem_durations=stem_durations,
    )
