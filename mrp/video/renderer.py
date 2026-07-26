import colorsys
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from mrp.video.analysis import AnalysisBundle, analyze_project
from mrp.video.casting import resolve_section_composition
from mrp.video.choreography import ChoreographyState, choreography_at
from mrp.video.geometry import (
    SpiroGeometry,
    generate_spiro_points,
    generate_text_points,
    hue_flow_values,
)
from mrp.video.mappings import map_layer_state, sample_audio_visual_state
from mrp.video.presets import (
    MappingPreset,
    PalettePreset,
    get_mapping_preset,
    get_palette_preset,
)
from mrp.video.project import (
    AlignedLyrics,
    CastingConfig,
    ProjectManifest,
    VisualLayerConfig,
    load_aligned_lyrics,
    load_project_manifest,
)
from mrp.video.text import (
    SpirophonicTextError,
    draw_lyric_overlay,
    lyric_cue_at,
    validate_lyric_font,
)
from mrp.video.tracing import cyclic_trace_window, trace_progress

DRAFT_MAX_WIDTH = 960
DRAFT_MAX_HEIGHT = 540
DRAFT_MAX_FPS = 15.0
FRAME_SEQUENCE_FORMAT_VERSION = 1
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class LayerCurve:
    config: VisualLayerConfig
    points: NDArray[np.float32]
    phase_offset: float
    hue_values: NDArray[np.float32] | None = None
    """Static per-point color-flow values in [0, 1]; None for solid layers."""


@dataclass(frozen=True, slots=True)
class CurveComposition:
    key: str
    casting: CastingConfig
    layers: tuple[LayerCurve, ...]


@dataclass(frozen=True, slots=True)
class RenderContext:
    project: ProjectManifest
    analysis: AnalysisBundle
    lyrics: AlignedLyrics
    layers: tuple[LayerCurve, ...]
    section_compositions: dict[str, CurveComposition]
    font_path: Path
    root: Path
    mapping_preset: MappingPreset
    palette_preset: PalettePreset
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FramePlan:
    width: int
    height: int
    fps: float
    start_frame: int
    end_frame: int
    draft: bool

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame

    @property
    def start_time(self) -> float:
        return self.start_frame / self.fps

    @property
    def end_time(self) -> float:
        return self.end_frame / self.fps


@dataclass(frozen=True, slots=True)
class FrameOutput:
    output_path: Path
    frame_index: int
    time_seconds: float
    width: int
    height: int
    draft: bool

    def summary(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "frame_index": self.frame_index,
            "time_seconds": self.time_seconds,
            "width": self.width,
            "height": self.height,
            "draft": self.draft,
        }


@dataclass(frozen=True, slots=True)
class FrameSequenceOutput:
    output_path: Path
    plan: FramePlan

    def summary(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "frame_count": self.plan.frame_count,
            "start_time": self.plan.start_time,
            "end_time": self.plan.end_time,
            "width": self.plan.width,
            "height": self.plan.height,
            "fps": self.plan.fps,
            "draft": self.plan.draft,
        }


class SpirophonicRendererError(Exception):
    pass


def _phase_offset(seed: int, layer_id: str) -> float:
    digest = hashlib.sha256(f"{seed}:{layer_id}".encode()).digest()
    fraction = int.from_bytes(digest[:8], "big") / (2**64 - 1)
    return fraction * math.tau


def _spiro_geometry(config: Any) -> SpiroGeometry:
    """Map a LayerGeometryConfig onto the engine dataclass.

    None values (fields belonging to other families) fall back to the
    dataclass defaults; the config validator guarantees the active family's
    fields are populated.
    """
    fields = config.model_dump(exclude_none=True)
    return SpiroGeometry(**fields)


def _curve_from_points(
    layer: VisualLayerConfig,
    generated: list,
    *,
    key: str,
    seed: int,
    normalize: bool,
) -> LayerCurve | None:
    points = np.asarray([(point.x, point.y) for point in generated], dtype=np.float32)
    extent = float(np.max(np.linalg.norm(points, axis=1), initial=0))
    if not math.isfinite(extent) or extent <= 0:
        return None
    if normalize:
        points /= extent
    points.setflags(write=False)
    hue_values = None
    if layer.color_flow is not None:
        hue_values = np.asarray(
            hue_flow_values(generated, layer.color_flow.source),
            dtype=np.float32,
        )
        hue_values.setflags(write=False)
    return LayerCurve(
        config=layer,
        points=points,
        phase_offset=_phase_offset(seed, key),
        hue_values=hue_values,
    )


def _build_curves(
    layer: VisualLayerConfig,
    seed: int,
    *,
    namespace: str | None = None,
) -> tuple[LayerCurve, ...]:
    """Build one or more curves for a layer.

    Every family yields a single curve except ``text``, which expands into one
    curve per letter-contour (all sharing the layer's config) so the whole
    word draws with per-letter spiro trails while counting as a single trace
    in the scene budget. Contours are group-normalized in generate_text_points,
    so they are not re-normalized here.
    """
    prefix = f"{namespace}:{layer.id}" if namespace else layer.id
    if layer.geometry.family == "text":
        contours = generate_text_points(_spiro_geometry(layer.geometry))
        curves = [
            curve
            for index, contour in enumerate(contours)
            if (
                curve := _curve_from_points(
                    layer, contour, key=f"{prefix}:{index}", seed=seed, normalize=False
                )
            )
            is not None
        ]
        if not curves:
            raise SpirophonicRendererError(
                f"text layer '{layer.id}' has no drawable contours"
            )
        return tuple(curves)
    generated = generate_spiro_points(_spiro_geometry(layer.geometry))
    curve = _curve_from_points(
        layer, generated, key=prefix, seed=seed, normalize=True
    )
    if curve is None:
        raise SpirophonicRendererError(f"visual layer '{layer.id}' has no extent")
    return (curve,)


def _build_curve(
    layer: VisualLayerConfig,
    seed: int,
    *,
    namespace: str | None = None,
) -> LayerCurve:
    """Single-curve build for non-text families (text expands to many)."""
    curves = _build_curves(layer, seed, namespace=namespace)
    if len(curves) != 1:
        raise SpirophonicRendererError(
            f"layer '{layer.id}' expands to {len(curves)} curves; use _build_curves"
        )
    return curves[0]


def build_render_context(
    project: ProjectManifest,
    analysis: AnalysisBundle,
    lyrics: AlignedLyrics,
    *,
    root: Path,
    warnings: tuple[str, ...] = (),
) -> RenderContext:
    if lyrics.sections[-1].end > analysis.duration + project.audio.duration_tolerance:
        raise SpirophonicRendererError(
            "aligned lyric timing extends beyond the master audio duration"
        )
    layers = tuple(
        curve
        for layer in project.visuals.layers
        for curve in _build_curves(layer, project.video.seed)
    )
    composition_cache: dict[str, CurveComposition] = {}
    section_compositions: dict[str, CurveComposition] = {}
    for section in lyrics.sections:
        resolved = resolve_section_composition(
            project.visuals,
            section.type,
            section.id,
            project.video.seed,
        )
        composition = composition_cache.get(resolved.key)
        if composition is None:
            seed = resolved.composition.casting.seed
            if seed is None:
                seed = project.video.seed
            composition = CurveComposition(
                key=resolved.key,
                casting=resolved.composition.casting.model_copy(
                    update={"seed": seed}
                ),
                layers=tuple(
                    curve
                    for trace in resolved.composition.traces
                    for curve in _build_curves(
                        trace,
                        seed,
                        namespace=(
                            None
                            if resolved.key == "legacy:global-layers"
                            else resolved.key
                        ),
                    )
                ),
            )
            composition_cache[resolved.key] = composition
        section_compositions[section.id] = composition
    font_path = (root / project.text.font).resolve()
    try:
        validate_lyric_font(font_path, project.text.size)
    except SpirophonicTextError as exc:
        raise SpirophonicRendererError(str(exc)) from exc
    return RenderContext(
        project=project,
        analysis=analysis,
        lyrics=lyrics,
        layers=layers,
        section_compositions=section_compositions,
        font_path=font_path,
        root=root.resolve(),
        mapping_preset=get_mapping_preset(project.visuals.mapping_preset),
        palette_preset=get_palette_preset(project.visuals.palette_preset),
        warnings=warnings,
    )


def load_render_context(
    manifest_path: Path,
    *,
    progress: ProgressCallback | None = None,
) -> RenderContext:
    notify = progress or (lambda _message: None)
    manifest = manifest_path.expanduser().resolve()
    project = load_project_manifest(manifest)
    if project.lyrics.aligned is None:
        raise SpirophonicRendererError(
            "visual rendering requires lyrics.aligned in the project manifest"
        )
    aligned_path = (manifest.parent / project.lyrics.aligned).resolve()
    if not aligned_path.is_file():
        raise SpirophonicRendererError(
            f"aligned lyrics do not exist: {aligned_path}; "
            "run 'scripts/mrp video align'"
        )
    notify("Loading aligned lyrics")
    lyrics = load_aligned_lyrics(aligned_path)
    notify("Loading or computing shared audio analysis")
    analysis_run = analyze_project(manifest, progress=progress)
    notify("Preparing stable spirograph curves")
    alignment_warnings = (
        tuple(lyrics.alignment.warnings) if lyrics.alignment is not None else ()
    )
    warnings = tuple(dict.fromkeys((*analysis_run.warnings, *alignment_warnings)))
    return build_render_context(
        project,
        analysis_run.bundle,
        lyrics,
        root=manifest.parent,
        warnings=warnings,
    )


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def _layer_color(
    base_color: str,
    hue_shift_degrees: float,
    intensity: float,
    flash: float = 0,
) -> tuple[int, int, int]:
    red, green, blue = (component / 255 for component in _parse_hex_color(base_color))
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    hue = (hue + hue_shift_degrees / 360) % 1
    saturation = min(1, saturation * intensity)
    value = min(1, value * (0.78 + 0.22 * intensity))
    mapped = colorsys.hsv_to_rgb(hue, saturation, value)
    flash_mix = min(0.72, max(0, flash) ** 1.4 * 0.72)
    mapped = tuple(component * (1 - flash_mix) + flash_mix for component in mapped)
    return tuple(round(component * 255) for component in mapped)


def _base_layer_color(
    context: RenderContext,
    layer: VisualLayerConfig,
    layer_index: int,
) -> str:
    if layer.color_locked:
        return layer.color
    custom = context.project.visuals.palette
    if custom:
        return custom[layer_index % len(custom)]
    return context.palette_preset.colors.get(layer.role, layer.color)


def _background_frame(
    context: RenderContext,
    width: int,
    height: int,
    master_energy: float,
) -> NDArray[np.uint8]:
    background = _parse_hex_color(context.project.video.background)
    base = np.asarray(background, dtype=np.float64)
    response = (
        context.project.visuals.background_response
        * context.mapping_preset.background_response
        * master_energy
    )
    color = np.rint(base + (255 - base) * response).astype(np.uint8)
    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :] = color
    return frame


def _transform_points(
    points: NDArray[np.float32],
    *,
    width: int,
    height: int,
    scale: float,
    rotation: float,
    margin: float,
    anchor_x: float,
    anchor_y: float,
) -> NDArray[np.int32]:
    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    rotation_matrix = np.asarray(((cosine, -sine), (sine, cosine)), dtype=np.float32)
    radius = min(width, height) * (0.5 - margin) * scale
    transformed = points @ rotation_matrix.T
    transformed *= radius
    transformed[:, 0] += width * anchor_x
    transformed[:, 1] += height * anchor_y
    return np.rint(transformed).astype(np.int32).reshape((-1, 1, 2))


def _layer_anchor(
    curve: LayerCurve,
    *,
    time_seconds: float,
    spatial_spread: float,
    anchor_drift: float,
) -> tuple[float, float]:
    config = curve.config
    depth_response = 0.45 if config.depth == "background" else 1
    phase = curve.phase_offset
    anchor_x = 0.5 + (config.anchor_x - 0.5) * spatial_spread
    anchor_x += math.sin(time_seconds * 0.11 + phase) * anchor_drift * depth_response
    anchor_y = config.anchor_y
    anchor_y += (
        math.cos(time_seconds * 0.09 + phase) * anchor_drift * 0.7 * depth_response
    )
    return anchor_x, anchor_y


def _draw_fading_path(
    mask: NDArray[np.uint8],
    points: NDArray[np.int32],
    *,
    peak: float,
    line_width: float,
) -> None:
    if len(points) < 2 or peak <= 0:
        return
    step_count = min(14, len(points) - 1)
    boundaries = np.linspace(0, len(points) - 1, step_count + 1, dtype=np.int32)
    for step in range(step_count):
        start = max(0, int(boundaries[step]) - (1 if step else 0))
        end = int(boundaries[step + 1]) + 1
        amount = (step + 1) / step_count
        intensity = round(255 * peak * (0.12 + 0.88 * amount * amount))
        cv2.polylines(
            mask,
            [points[start:end]],
            isClosed=False,
            color=max(1, min(255, intensity)),
            thickness=max(1, round(line_width)),
            lineType=cv2.LINE_AA,
        )


FLOW_HUE_LEVELS = 24


def _paint_flow_colors(
    color_buffer: NDArray[np.uint8],
    paths: tuple[tuple[NDArray[np.int32], float, NDArray[np.float32] | None], ...],
    color_for_value: Callable[[float], tuple[int, int, int]],
    *,
    line_width: float,
    head_radius: float,
) -> None:
    """Stroke hue-leveled runs into the layer's per-pixel color source.

    Flow values oscillate once per winding on a spirogram, so positional
    binning would average them away. Instead each point's value in [0, 1] is
    quantized onto FLOW_HUE_LEVELS fixed levels and the path is split into
    constant-level runs — per-petal color detail at segment resolution, with
    at most one cv2 call per level per path. The alpha mask keeps the fade/AA
    look; these strokes only decide which color each masked pixel takes, so
    they draw slightly wider with no AA of their own.
    """
    thickness = max(1, round(line_width)) + 3
    for points, _peak, values in paths:
        if values is None or len(points) < 2:
            continue
        levels = np.minimum(
            FLOW_HUE_LEVELS - 1,
            (np.clip(values, 0, 1) * FLOW_HUE_LEVELS).astype(np.int32),
        )
        changes = np.flatnonzero(np.diff(levels) != 0) + 1
        boundaries = [0, *changes.tolist(), len(points)]
        runs: dict[int, list[NDArray[np.int32]]] = {}
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            # Extend one point past each side so boundary segments are covered;
            # neighboring runs overlap by a segment, which is harmless here.
            runs.setdefault(int(levels[start]), []).append(
                points[max(0, start - 1) : min(len(points), end + 1)]
            )
        for level, segments in runs.items():
            cv2.polylines(
                color_buffer,
                segments,
                isClosed=False,
                color=color_for_value((level + 0.5) / FLOW_HUE_LEVELS),
                thickness=thickness,
                lineType=cv2.LINE_8,
            )
    if paths and head_radius > 0 and paths[-1][2] is not None:
        head = paths[-1][0][-1, 0]
        cv2.circle(
            color_buffer,
            (int(head[0]), int(head[1])),
            max(1, round(head_radius)) + 2,
            color_for_value(float(paths[-1][2][-1])),
            thickness=-1,
            lineType=cv2.LINE_8,
        )


def _composite_trace(
    frame: NDArray[np.uint8],
    paths: tuple[tuple[NDArray[np.int32], float, NDArray[np.float32] | None], ...],
    *,
    color: tuple[int, int, int],
    opacity: float,
    line_width: float,
    blend_mode: str,
    head_radius: float,
    color_for_value: Callable[[float], tuple[int, int, int]] | None = None,
) -> NDArray[np.uint8]:
    if opacity <= 0:
        return frame
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    for points, peak, _values in paths:
        _draw_fading_path(mask, points, peak=peak, line_width=line_width)
    if paths and head_radius > 0:
        head = paths[-1][0][-1, 0]
        cv2.circle(
            mask,
            (int(head[0]), int(head[1])),
            max(1, round(head_radius)),
            255,
            thickness=-1,
            lineType=cv2.LINE_AA,
        )
    alpha = mask.astype(np.float32)[:, :, np.newaxis] / 255
    alpha *= opacity
    base = frame.astype(np.float32) / 255
    flow = color_for_value is not None and any(
        values is not None for _points, _peak, values in paths
    )
    if flow:
        color_buffer = np.empty_like(frame)
        color_buffer[:, :] = color
        _paint_flow_colors(
            color_buffer,
            paths,
            color_for_value,
            line_width=line_width,
            head_radius=head_radius,
        )
        source = color_buffer.astype(np.float32) / 255
    else:
        source = np.asarray(color, dtype=np.float32)[np.newaxis, np.newaxis, :] / 255
    if blend_mode == "screen":
        output = 1 - (1 - base) * (1 - source * alpha)
    else:
        output = base * (1 - alpha) + source * alpha
    return np.rint(np.clip(output, 0, 1) * 255).astype(np.uint8)


def _weighted_compositions(
    context: RenderContext,
    choreography: ChoreographyState,
) -> tuple[tuple[CurveComposition, float], ...]:
    current = context.section_compositions[choreography.section_id]
    if (
        choreography.previous_section_id is None
        or choreography.transition_progress >= 1
    ):
        return ((current, 1.0),)
    previous = context.section_compositions[choreography.previous_section_id]
    if previous.key == current.key:
        return ((current, 1.0),)
    return (
        (previous, 1 - choreography.transition_progress),
        (current, choreography.transition_progress),
    )


def render_frame(
    context: RenderContext,
    time_seconds: float,
    frame_index: int,
    *,
    width: int | None = None,
    height: int | None = None,
) -> NDArray[np.uint8]:
    """Render one deterministic RGB song frame from musical time and frame index."""
    if frame_index < 0 or time_seconds < 0:
        raise SpirophonicRendererError("frame index and time must be non-negative")
    if time_seconds > context.analysis.duration:
        raise SpirophonicRendererError("frame time exceeds the master duration")
    width = width or context.project.video.width
    height = height or context.project.video.height
    if width <= 0 or height <= 0:
        raise SpirophonicRendererError("frame dimensions must be positive")

    audio = sample_audio_visual_state(context.analysis, time_seconds)
    choreography = choreography_at(
        context.lyrics,
        time_seconds,
        transition_seconds=context.project.visuals.transition_seconds,
        visuals=context.project.visuals,
    )
    frame = _background_frame(context, width, height, audio.master.energy)
    weighted_compositions = _weighted_compositions(context, choreography)
    indexed_layers = [
        (composition_index, layer_index, curve, weight)
        for composition_index, (composition, weight) in enumerate(weighted_compositions)
        for layer_index, curve in enumerate(composition.layers)
        if weight > 0
    ]
    indexed_layers.sort(
        key=lambda item: (
            item[2].config.depth == "foreground",
            item[0],
            item[1],
        )
    )
    for _, layer_index, curve, composition_weight in indexed_layers:
        state = map_layer_state(
            curve.config,
            audio,
            choreography,
            time_seconds,
            context.mapping_preset,
            visibility_override=composition_weight,
        )
        trace = curve.config.trace
        anchor_x, anchor_y = _layer_anchor(
            curve,
            time_seconds=time_seconds,
            spatial_spread=choreography.spatial_spread,
            anchor_drift=choreography.anchor_drift,
        )
        progress = trace_progress(
            choreography.trace_time,
            trace.cycles_per_second,
            phase=curve.phase_offset / math.tau,
        )
        flow = curve.config.color_flow
        flow_active = flow is not None and curve.hue_values is not None

        def _window_flow_values(window) -> NDArray[np.float32] | None:
            if not flow_active or window.indices is None:
                return None
            return curve.hue_values[window.indices]

        trace_paths: list[
            tuple[NDArray[np.int32], float, NDArray[np.float32] | None]
        ] = []
        for ghost_index in range(trace.ghost_count, 0, -1):
            ghost_progress = progress - ghost_index * (
                state.trail_fraction + trace.ghost_spacing
            )
            ghost = cyclic_trace_window(
                curve.points,
                ghost_progress,
                state.trail_fraction,
            )
            trace_paths.append(
                (
                    _transform_points(
                        ghost.points,
                        width=width,
                        height=height,
                        scale=state.scale,
                        rotation=state.rotation_radians,
                        margin=context.project.visuals.canvas_margin,
                        anchor_x=anchor_x,
                        anchor_y=anchor_y,
                    ),
                    0.3 / ghost_index,
                    _window_flow_values(ghost),
                )
            )
        active = cyclic_trace_window(
            curve.points,
            progress,
            state.trail_fraction,
        )
        trace_paths.append(
            (
                _transform_points(
                    active.points,
                    width=width,
                    height=height,
                    scale=state.scale,
                    rotation=state.rotation_radians,
                    margin=context.project.visuals.canvas_margin,
                    anchor_x=anchor_x,
                    anchor_y=anchor_y,
                ),
                1.0,
                _window_flow_values(active),
            )
        )
        base_color = _base_layer_color(context, curve.config, layer_index)
        color_for_value = None
        if flow_active:

            def color_for_value(
                value: float,
                _base: str = base_color,
                _swing: float = flow.swing_degrees,
                _hue_shift: float = state.hue_shift_degrees,
                _intensity: float = state.color_intensity,
                _flash: float = state.beat_pulse,
            ) -> tuple[int, int, int]:
                return _layer_color(
                    _base,
                    _hue_shift + (value - 0.5) * _swing,
                    _intensity,
                    _flash,
                )

        frame = _composite_trace(
            frame,
            tuple(trace_paths),
            color=_layer_color(
                base_color,
                state.hue_shift_degrees,
                state.color_intensity,
                state.beat_pulse,
            ),
            opacity=state.opacity,
            line_width=state.line_width,
            blend_mode=curve.config.blend_mode,
            head_radius=trace.head_radius * (1 + state.beat_pulse * 2.2),
            color_for_value=color_for_value,
        )

    cue = lyric_cue_at(
        context.lyrics,
        time_seconds,
        fade_seconds=context.project.visuals.lyric_fade_seconds,
        choreography_opacity=choreography.lyrics_opacity,
    )
    try:
        return draw_lyric_overlay(
            frame,
            cue,
            config=context.project.text,
            font_path=context.font_path,
            reference_height=context.project.video.height,
        )
    except SpirophonicTextError as exc:
        raise SpirophonicRendererError(str(exc)) from exc


def render_dimensions(
    project: ProjectManifest,
    *,
    draft: bool,
) -> tuple[int, int, float]:
    if not draft:
        return project.video.width, project.video.height, project.video.fps
    scale = min(
        1.0,
        DRAFT_MAX_WIDTH / project.video.width,
        DRAFT_MAX_HEIGHT / project.video.height,
    )
    width = max(1, round(project.video.width * scale))
    height = max(1, round(project.video.height * scale))
    return width, height, min(project.video.fps, DRAFT_MAX_FPS)


def plan_frame_range(
    project: ProjectManifest,
    duration: float,
    *,
    start_seconds: float = 0,
    end_seconds: float | None = None,
    draft: bool = False,
) -> FramePlan:
    end_seconds = duration if end_seconds is None else end_seconds
    if start_seconds < 0 or end_seconds <= start_seconds:
        raise SpirophonicRendererError("render range must have a positive duration")
    if end_seconds > duration + project.audio.duration_tolerance:
        raise SpirophonicRendererError(
            "render range extends beyond the master duration"
        )
    width, height, fps = render_dimensions(project, draft=draft)
    start_frame = math.ceil(start_seconds * fps - 1e-9)
    end_frame = math.ceil(min(end_seconds, duration) * fps - 1e-9)
    if end_frame <= start_frame:
        raise SpirophonicRendererError("render range contains no frames")
    return FramePlan(width, height, fps, start_frame, end_frame, draft)


def iter_rendered_frames(
    context: RenderContext,
    plan: FramePlan,
) -> Iterator[tuple[int, float, NDArray[np.uint8]]]:
    for frame_index in range(plan.start_frame, plan.end_frame):
        time_seconds = frame_index / plan.fps
        yield (
            frame_index,
            time_seconds,
            render_frame(
                context,
                time_seconds,
                frame_index,
                width=plan.width,
                height=plan.height,
            ),
        )


def _encode_png(frame: NDArray[np.uint8]) -> bytes:
    success, encoded = cv2.imencode(
        ".png",
        cv2.cvtColor(frame, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_PNG_COMPRESSION, 6],
    )
    if not success:
        raise SpirophonicRendererError("OpenCV could not encode a preview frame")
    return encoded.tobytes()


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def render_frame_file(
    context: RenderContext,
    output_path: Path,
    *,
    time_seconds: float,
    draft: bool = False,
    force: bool = False,
) -> FrameOutput:
    output = output_path.expanduser().resolve()
    if output.suffix.casefold() != ".png":
        raise SpirophonicRendererError("frame output must use a .png extension")
    if output.exists() and not force:
        raise SpirophonicRendererError(
            f"preview frame already exists: {output}; use --force to overwrite"
        )
    width, height, fps = render_dimensions(context.project, draft=draft)
    frame_index = round(time_seconds * fps)
    actual_time = frame_index / fps
    if actual_time > context.analysis.duration:
        raise SpirophonicRendererError("frame time exceeds the master duration")
    frame = render_frame(
        context,
        actual_time,
        frame_index,
        width=width,
        height=height,
    )
    _write_bytes_atomic(output, _encode_png(frame))
    return FrameOutput(output, frame_index, actual_time, width, height, draft)


def _sequence_metadata(plan: FramePlan) -> dict[str, Any]:
    return {
        "format": "spirophonic-frame-sequence",
        "version": FRAME_SEQUENCE_FORMAT_VERSION,
        "frame_count": plan.frame_count,
        "start_frame": plan.start_frame,
        "end_frame": plan.end_frame,
        "start_time": plan.start_time,
        "end_time": plan.end_time,
        "width": plan.width,
        "height": plan.height,
        "fps": plan.fps,
        "draft": plan.draft,
        "pixel_format": "rgb24",
    }


def _replace_sequence_directory(staging: Path, output: Path, force: bool) -> None:
    if not output.exists():
        os.replace(staging, output)
        return
    marker = output / "frames.json"
    try:
        existing = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpirophonicRendererError(
            f"refusing to replace non-Spirophonic directory: {output}"
        ) from exc
    if existing.get("format") != "spirophonic-frame-sequence":
        raise SpirophonicRendererError(
            f"refusing to replace non-Spirophonic directory: {output}"
        )
    if not force:
        raise SpirophonicRendererError(
            f"frame sequence already exists: {output}; use --force to overwrite"
        )
    backup = output.with_name(f".{output.name}.{os.getpid()}.backup")
    os.replace(output, backup)
    try:
        os.replace(staging, output)
    except OSError:
        os.replace(backup, output)
        raise
    shutil.rmtree(backup)


def _validate_sequence_target(output: Path, force: bool) -> None:
    if not output.exists():
        return
    if not force:
        raise SpirophonicRendererError(
            f"frame sequence already exists: {output}; use --force to overwrite"
        )
    marker = output / "frames.json"
    try:
        existing = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpirophonicRendererError(
            f"refusing to replace non-Spirophonic directory: {output}"
        ) from exc
    if existing.get("format") != "spirophonic-frame-sequence":
        raise SpirophonicRendererError(
            f"refusing to replace non-Spirophonic directory: {output}"
        )


def render_frame_sequence(
    context: RenderContext,
    output_path: Path,
    plan: FramePlan,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> FrameSequenceOutput:
    """Write a bounded development frame sequence, atomically as one directory."""
    notify = progress or (lambda _message: None)
    output = output_path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _validate_sequence_target(output, force)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        for offset, (frame_index, _time, frame) in enumerate(
            iter_rendered_frames(context, plan),
            start=1,
        ):
            name = f"frame-{frame_index:08d}.png"
            (staging / name).write_bytes(_encode_png(frame))
            if offset == 1 or offset == plan.frame_count or offset % 30 == 0:
                notify(f"Rendered frame {offset} of {plan.frame_count}")
        (staging / "frames.json").write_text(
            json.dumps(_sequence_metadata(plan), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _replace_sequence_directory(staging, output, force)
    except OSError as exc:
        raise SpirophonicRendererError(
            f"could not write frame sequence: {exc}"
        ) from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return FrameSequenceOutput(output, plan)
