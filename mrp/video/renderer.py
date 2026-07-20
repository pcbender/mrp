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
from mrp.video.geometry import SpiroGeometry, generate_spiro_points
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


def _build_curve(
    layer: VisualLayerConfig,
    seed: int,
    *,
    namespace: str | None = None,
) -> LayerCurve:
    geometry = layer.geometry
    generated = generate_spiro_points(
        SpiroGeometry(
            fixed_radius=geometry.fixed_radius,
            moving_radius=geometry.moving_radius,
            pen_offset=geometry.pen_offset,
            rotation=geometry.rotation,
            samples=geometry.samples,
        )
    )
    points = np.asarray([(point.x, point.y) for point in generated], dtype=np.float32)
    extent = float(np.max(np.linalg.norm(points, axis=1), initial=0))
    if not math.isfinite(extent) or extent <= 0:
        raise SpirophonicRendererError(f"visual layer '{layer.id}' has no extent")
    points /= extent
    points.setflags(write=False)
    return LayerCurve(
        config=layer,
        points=points,
        phase_offset=_phase_offset(
            seed,
            f"{namespace}:{layer.id}" if namespace else layer.id,
        ),
    )


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
        _build_curve(layer, project.video.seed) for layer in project.visuals.layers
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
                    _build_curve(
                        trace,
                        seed,
                        namespace=(
                            None
                            if resolved.key == "legacy:global-layers"
                            else resolved.key
                        ),
                    )
                    for trace in resolved.composition.traces
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


def _composite_trace(
    frame: NDArray[np.uint8],
    paths: tuple[tuple[NDArray[np.int32], float], ...],
    *,
    color: tuple[int, int, int],
    opacity: float,
    line_width: float,
    blend_mode: str,
    head_radius: float,
) -> NDArray[np.uint8]:
    if opacity <= 0:
        return frame
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    for points, peak in paths:
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
        trace_paths: list[tuple[NDArray[np.int32], float]] = []
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
            )
        )
        frame = _composite_trace(
            frame,
            tuple(trace_paths),
            color=_layer_color(
                _base_layer_color(context, curve.config, layer_index),
                state.hue_shift_degrees,
                state.color_intensity,
                state.beat_pulse,
            ),
            opacity=state.opacity,
            line_width=state.line_width,
            blend_mode=curve.config.blend_mode,
            head_radius=trace.head_radius * (1 + state.beat_pulse * 2.2),
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
