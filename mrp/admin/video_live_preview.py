"""Private, bounded browser document for music-video Live Preview."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from pydantic import ValidationError

from mrp.admin.video_casting import aligned_path, project_path
from mrp.admin.video_workspace import (
    preflight_input_drift,
    resolve_asset,
    track_key,
)
from mrp.video.casting import resolve_section_composition
from mrp.video.choreography import choreography_at
from mrp.video.presets import get_mapping_preset, get_palette_preset
from mrp.video.project import (
    SpirophonicValidationError,
    load_aligned_lyrics,
    load_project_manifest,
)
from mrp.video.track_project import TrackProjectDocument

PREVIEW_FORMAT = "mrp-music-video-live-preview"
PREVIEW_VERSION = 3
STATE_RATE_HZ = 20
STATE_ENCODING = "base64-float32-le"
# Only the columns the browser engine actually reads. Sampled state is the
# bulk of the response body, so a column nobody consumes is pure payload:
# `section_progress`, `rotation_direction`, and `trace_speed` are never read,
# and `visibility_*` is unreachable because every caller supplies an explicit
# visibility override, exactly as render_frame passes composition_weight.
# Keep this tuple identical to STATE_SCHEMA in static/video-live-preview.js.
STATE_SCHEMA = (
    "section_index",
    "previous_section_index",
    "master_energy",
    "master_accent",
    "drums_energy",
    "drums_accent",
    "bass_energy",
    "bass_accent",
    "vocals_energy",
    "vocals_accent",
    "instruments_energy",
    "instruments_accent",
    "spectral_centroid",
    "transition_progress",
    "layer_fraction",
    "scale",
    "motion",
    "color_intensity",
    "onset_response",
    "palette_shift",
    "lyrics_opacity",
    "spatial_spread",
    "anchor_drift",
    "trail_length",
    "beat_gain",
    "intensity_gain",
    "trace_time",
    "rotation_time",
)
STATE_WIDTH = len(STATE_SCHEMA)
SEMANTIC_ROLES = ("master", "drums", "bass", "vocals", "instruments")

MAX_DURATION_SECONDS = 360
MAX_STATE_SAMPLES = MAX_DURATION_SECONDS * STATE_RATE_HZ + 1
MAX_SECTIONS = 128
MAX_LYRIC_LINES = 2_000
MAX_COMPOSITIONS = 128
MAX_TOTAL_TRACES = 1_024
MAX_GEOMETRY_SAMPLES = 1_200
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
# The isolated interpreter pays for process start and a librosa/numpy import
# before it samples the whole timeline, so it needs far more headroom than the
# in-process path the performance budgets were measured on.
WORKER_TIMEOUT_SECONDS = 90


class LivePreviewError(Exception):
    """A safe structured error suitable for the private JSON route."""

    def __init__(self, code: str, message: str, *, status_code: int = 422):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


@dataclass(frozen=True, slots=True)
class LivePreviewDocument:
    payload: dict[str, Any]
    body: bytes
    etag: str


@dataclass(frozen=True, slots=True)
class _AnalysisAvailability:
    bundle: Any | None
    reason: dict[str, str] | None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_yaml_bytes(path: Path, *, kind: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        raise LivePreviewError(
            f"{kind}_invalid",
            f"The saved video {kind} cannot be read or validated.",
        ) from exc
    if not isinstance(value, dict):
        raise LivePreviewError(
            f"{kind}_invalid",
            f"The saved video {kind} must contain a mapping.",
        )
    return raw, value


def _load_source_documents(
    root: Path,
    release_slug: str,
    release: dict[str, Any],
    track_slug: str,
    track: dict[str, Any],
) -> tuple[Path, bytes, TrackProjectDocument, Path, bytes, Any]:
    source_project = project_path(root, release, track)
    source_lyrics = aligned_path(root, release, track)
    if not source_project.is_file():
        raise LivePreviewError(
            "project_missing",
            "Prepare this track before opening Live Preview.",
            status_code=409,
        )
    if not source_lyrics.is_file():
        raise LivePreviewError(
            "timing_missing",
            "Finish aligned scene timing before opening Live Preview.",
            status_code=409,
        )

    project_raw, project_value = _read_yaml_bytes(source_project, kind="project")
    try:
        document = TrackProjectDocument.model_validate(project_value)
    except ValidationError as exc:
        raise LivePreviewError(
            "project_invalid",
            "The saved video project is invalid; correct it before previewing.",
        ) from exc

    expected_key = track_key(release, track)
    expected_release = Path("content") / "releases" / f"{release_slug}.yaml"
    if (
        document.source.track_key != expected_key
        or document.source.track_slug != track_slug
        or document.source.release != expected_release
    ):
        raise LivePreviewError(
            "project_mismatch",
            "The saved video project does not belong to this release track.",
            status_code=409,
        )

    try:
        lyrics_raw = source_lyrics.read_bytes()
        lyrics = load_aligned_lyrics(source_lyrics)
    except (OSError, SpirophonicValidationError) as exc:
        raise LivePreviewError(
            "timing_invalid",
            "The aligned scene timing is invalid; correct it before previewing.",
        ) from exc
    return (
        source_project,
        project_raw,
        document,
        source_lyrics,
        lyrics_raw,
        lyrics,
    )


def _preflight_path(root: Path, key: str) -> Path:
    return (
        root
        / "assets"
        / "processed"
        / "video"
        / key
        / "logs"
        / "preflight.json"
    )


def _runtime_manifest_path(root: Path, key: str) -> Path:
    return (
        root
        / "assets"
        / "processed"
        / "video"
        / key
        / "analysis"
        / "project.runtime.yaml"
    )


def _read_preflight(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _duration_from_track(track: dict[str, Any]) -> float | None:
    value = str(track.get("duration") or "").strip()
    if not value:
        return None
    try:
        minutes, seconds = value.split(":", maxsplit=1)
        duration = int(minutes) * 60 + float(seconds)
    except (TypeError, ValueError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def _master_duration(
    root: Path,
    release: dict[str, Any],
    key: str,
    track: dict[str, Any],
    lyrics: Any,
    tolerance: float,
) -> float:
    """Resolve the master duration, refusing timing only against a measured one.

    Preflight records the decoded master duration and is the only trustworthy
    source. The release YAML's ``duration`` is whole seconds (``'3:45'``), so it
    routinely sits below the real master; letting it veto aligned timing would
    refuse tracks the renderer accepts. Without a measured duration we take the
    longest available candidate and skip the timing check entirely, and the
    check itself uses the project's own tolerance like the renderer does.
    """
    preflight_path = _preflight_path(root, key)
    preflight = _read_preflight(preflight_path)
    preflight_current_for_release = bool(preflight) and (
        preflight_input_drift(root, release, track, preflight, audio_only=True)
        is None
    )

    measured = None
    if preflight_current_for_release:
        try:
            candidate = float(preflight.get("master_duration"))
        except (TypeError, ValueError):
            candidate = 0
        if math.isfinite(candidate) and candidate > 0:
            measured = candidate

    timing_end = float(lyrics.sections[-1].end)
    duration = (
        measured
        if measured is not None
        else max(_duration_from_track(track) or 0.0, timing_end)
    )
    if not math.isfinite(duration) or duration <= 0:
        raise LivePreviewError(
            "duration_invalid",
            "The track has no usable positive master duration.",
        )
    if duration > MAX_DURATION_SECONDS:
        raise LivePreviewError(
            "duration_limit",
            f"Live Preview supports tracks up to {MAX_DURATION_SECONDS} seconds.",
            status_code=413,
        )
    if measured is not None and timing_end > measured + tolerance:
        raise LivePreviewError(
            "timing_exceeds_duration",
            "Aligned scene timing extends beyond the current master duration.",
        )
    return duration


def _duration_tolerance(project: Any) -> float:
    """The project's own master-duration tolerance, matching the renderer."""
    return max(0.05, float(project.audio.duration_tolerance))


def _analysis_unavailable(code: str, message: str) -> _AnalysisAvailability:
    return _AnalysisAvailability(
        None,
        {
            "code": code,
            "message": message,
            "action_url": "track",
        },
    )


def _existing_analysis(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    source_project: Any,
    duration: float,
) -> _AnalysisAvailability:
    try:
        from mrp.video.analysis import (
            SpirophonicAnalysisError,
            load_existing_analysis,
        )
    except ModuleNotFoundError:
        return _analysis_unavailable(
            "analysis_environment_missing",
            "The video analysis environment is unavailable. Check Video setup.",
        )

    key = track_key(release, track)
    runtime_path = _runtime_manifest_path(root, key)
    preflight_path = _preflight_path(root, key)
    if not runtime_path.is_file() or not preflight_path.is_file():
        return _analysis_unavailable(
            "analysis_missing",
            "No cached audio analysis is available. Run Prepare and Analyze.",
        )
    preflight = _read_preflight(preflight_path)
    if not isinstance(preflight.get("input_hashes"), dict):
        return _analysis_unavailable(
            "analysis_stale",
            "Cached audio analysis cannot be verified. Run Prepare and Analyze.",
        )
    drift = preflight_input_drift(root, release, track, preflight, audio_only=True)
    if drift is not None:
        return _analysis_unavailable(
            "analysis_stale",
            f"{drift[0].upper()}{drift[1:]}. Run Prepare and Analyze.",
        )
    try:
        runtime = load_project_manifest(runtime_path)
    except (OSError, SpirophonicValidationError):
        return _analysis_unavailable(
            "prepared_runtime_stale",
            "Prepared video data uses an older renderer contract. Run Prepare; "
            "current audio analysis will be reused when its inputs still match.",
        )

    source_settings = source_project.analysis.model_dump(
        mode="json", exclude={"cache_dir"}
    )
    runtime_settings = runtime.analysis.model_dump(mode="json", exclude={"cache_dir"})
    if source_settings != runtime_settings:
        return _analysis_unavailable(
            "analysis_stale",
            "Audio-analysis settings changed. Run Prepare and Analyze.",
        )

    current_master = resolve_asset(root, track.get("master_path"))
    runtime_master = (runtime_path.parent / runtime.audio.master).resolve()
    if (
        current_master is None
        or not current_master.is_file()
        or current_master.resolve() != runtime_master
    ):
        return _analysis_unavailable(
            "analysis_stale",
            "The prepared master no longer matches this track. Run Prepare and Analyze.",
        )

    try:
        run = load_existing_analysis(runtime_path)
    except (OSError, SpirophonicAnalysisError, SpirophonicValidationError):
        run = None
    if run is None:
        return _analysis_unavailable(
            "analysis_stale",
            "No current cached audio analysis is available. Run Analyze.",
        )
    if abs(run.bundle.duration - duration) > _duration_tolerance(source_project):
        return _analysis_unavailable(
            "analysis_stale",
            "Cached audio analysis has a different master duration. Run Analyze.",
        )
    return _AnalysisAvailability(run.bundle, None)


def _phase_fraction(seed: int, key: str) -> float:
    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / (2**64 - 1)


def _safe_layer(
    layer: Any,
    *,
    phase_fraction: float | None = None,
    phase_fractions: list[float] | None = None,
) -> dict[str, Any]:
    geometry = layer.geometry.model_dump(mode="json", exclude_none=True)
    geometry["samples"] = min(int(geometry["samples"]), MAX_GEOMETRY_SAMPLES)
    payload = {
        "id": layer.id,
        "role": layer.role,
        "geometry": geometry,
        "trace": layer.trace.model_dump(mode="json", exclude_none=True),
        "color": layer.color,
        "color_locked": layer.color_locked,
        "color_flow": (
            layer.color_flow.model_dump(mode="json")
            if layer.color_flow is not None
            else None
        ),
        "spatial": (
            layer.spatial.model_dump(mode="json")
            if layer.spatial is not None
            else None
        ),
        "z_index": layer.z_index,
        "anchor_x": layer.anchor_x,
        "anchor_y": layer.anchor_y,
        "base_scale": layer.base_scale,
        "opacity": layer.opacity,
        "line_width": layer.line_width,
        "presentation": layer.presentation,
        "rotation_degrees_per_second": layer.rotation_degrees_per_second,
        "rotation_wobble_degrees": layer.rotation_wobble_degrees,
        "hue_shift_degrees": layer.hue_shift_degrees,
        "blend_mode": layer.blend_mode,
        "drivers": layer.drivers.model_dump(mode="json", exclude_none=True),
    }
    if phase_fraction is not None:
        payload["phase_fraction"] = phase_fraction
    if phase_fractions is not None:
        payload["phase_fractions"] = phase_fractions
    return payload


def _text_contour_count(geometry: Any) -> int:
    """Count the contours the renderer will actually build for a text layer.

    ``_build_curves`` expands a text layer into one curve per drawable contour
    and keys each curve by its index, so the phase list has to use the
    renderer's own expansion. Counting ``M``/``m`` commands instead would keep
    degenerate or zero-extent subpaths that ``generate_text_points`` drops,
    shifting every later contour onto the wrong phase. The command count stays
    only as a fallback for geometry this process cannot expand.
    """
    from mrp.video.geometry import SpiroGeometry, generate_text_points

    try:
        expanded = generate_text_points(
            SpiroGeometry(**geometry.model_dump(exclude_none=True))
        )
        return len(expanded)
    except (ImportError, IndexError, KeyError, TypeError, ValueError):
        return sum(1 for character in (geometry.path_data or "") if character in "Mm")


def _phase_key(composition_key: str, trace_id: str, contour_index: int | None) -> str:
    """The renderer's curve key for one trace, mirroring ``_build_curves``.

    Legacy global layers are built without a namespace; every other
    composition namespaces its traces by composition key. Text appends the
    contour index because it expands into one curve per contour.
    """
    prefix = (
        trace_id
        if composition_key == "legacy:global-layers"
        else f"{composition_key}:{trace_id}"
    )
    return prefix if contour_index is None else f"{prefix}:{contour_index}"


def _safe_trace(trace: Any, composition_key: str, seed: int) -> dict[str, Any]:
    """One composition trace plus the deterministic phase(s) the renderer uses."""
    if trace.geometry.family != "text":
        return _safe_layer(
            trace,
            phase_fraction=_phase_fraction(
                seed, _phase_key(composition_key, trace.id, None)
            ),
        )
    fractions = [
        _phase_fraction(seed, _phase_key(composition_key, trace.id, index))
        for index in range(_text_contour_count(trace.geometry))
    ]
    return _safe_layer(
        trace,
        phase_fraction=fractions[0] if fractions else 0.0,
        phase_fractions=fractions or None,
    )


def _safe_actor(actor: Any) -> dict[str, Any]:
    return {
        "id": actor.id,
        "name": actor.name,
        "description": actor.description,
        "kind": actor.kind,
        "character": actor.character,
        "components": [_safe_layer(component) for component in actor.components],
        "library_source": (
            actor.library_source.model_dump(mode="json")
            if actor.library_source is not None
            else None
        ),
    }


def _safe_background(
    background: Any,
    *,
    release_slug: str,
    track_slug: str,
    scene_id: str | None,
) -> dict[str, Any]:
    payload = background.model_dump(mode="json", exclude_none=True)
    payload.pop("image", None)
    if background.image is not None:
        url = f"/releases/{release_slug}/tracks/{track_slug}/video/background"
        if scene_id is not None:
            url += f"?scene={quote(scene_id, safe='')}"
        payload["image_url"] = url
    return payload


def background_image_path(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    *,
    scene_id: str | None = None,
) -> Path | None:
    """Resolve only an image declared by this track's current background model."""
    path = project_path(root, release, track)
    try:
        document = TrackProjectDocument.model_validate(
            _read_yaml_bytes(path, kind="project")[1]
        )
    except (OSError, ValidationError, LivePreviewError) as exc:
        raise LivePreviewError(
            "background_invalid",
            "The saved background image configuration is invalid.",
        ) from exc
    background = document.project.video.background
    if scene_id is not None:
        background = document.project.visuals.background_overrides.get(
            scene_id,
            background,
        )
    if background.image is None:
        return None
    if background.image.as_posix() == "@mrp/cover":
        resolved = resolve_asset(root, release.get("cover_image"))
    else:
        project_root = path.parent.resolve()
        resolved = (project_root / background.image).resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError as exc:
            raise LivePreviewError(
                "background_invalid",
                "Background images must stay inside the track project.",
            ) from exc
    if resolved is None or not resolved.is_file():
        raise LivePreviewError(
            "background_missing",
            "The selected background image is missing.",
            status_code=404,
        )
    return resolved


def _safe_base(
    *,
    release_slug: str,
    track_slug: str,
    project: Any,
    lyrics: Any,
    duration: float,
    source_revision: dict[str, Any],
    analysis_key: str | None,
    reason: dict[str, str] | None,
) -> dict[str, Any]:
    if len(lyrics.sections) > MAX_SECTIONS:
        raise LivePreviewError(
            "section_limit",
            f"Live Preview supports at most {MAX_SECTIONS} scenes.",
            status_code=413,
        )
    lyric_count = sum(len(section.lines) for section in lyrics.sections)
    if lyric_count > MAX_LYRIC_LINES:
        raise LivePreviewError(
            "lyric_limit",
            f"Live Preview supports at most {MAX_LYRIC_LINES} aligned lyric lines.",
            status_code=413,
        )

    sections: list[dict[str, Any]] = []
    compositions: dict[str, Any] = {}
    total_traces = 0
    for index, section in enumerate(lyrics.sections):
        resolved = resolve_section_composition(
            project.visuals,
            section.type,
            section.id,
            project.video.seed,
        )
        if resolved.key not in compositions:
            if len(compositions) >= MAX_COMPOSITIONS:
                raise LivePreviewError(
                    "composition_limit",
                    f"Live Preview supports at most {MAX_COMPOSITIONS} compositions.",
                    status_code=413,
                )
            total_traces += len(resolved.composition.traces)
            if total_traces > MAX_TOTAL_TRACES:
                raise LivePreviewError(
                    "trace_limit",
                    f"Live Preview supports at most {MAX_TOTAL_TRACES} unique traces.",
                    status_code=413,
                )
            seed = resolved.composition.casting.seed
            if seed is None:
                seed = project.video.seed
            casting = resolved.composition.casting.model_copy(update={"seed": seed})
            compositions[resolved.key] = {
                "casting": casting.model_dump(mode="json", exclude_none=True),
                "traces": [
                    _safe_trace(trace, resolved.key, seed)
                    for trace in resolved.composition.traces
                ],
            }
        sections.append(
            {
                "id": section.id,
                "type": section.type,
                "label": section.label,
                "start": section.start,
                "end": section.end,
                "composition_key": resolved.key,
                "background": _safe_background(
                    project.visuals.background_overrides.get(
                        section.id,
                        project.video.background,
                    ),
                    release_slug=release_slug,
                    track_slug=track_slug,
                    scene_id=(
                        section.id
                        if section.id in project.visuals.background_overrides
                        else None
                    ),
                ),
                "previous_section_id": (
                    lyrics.sections[index - 1].id if index > 0 else None
                ),
            }
        )

    mapping = get_mapping_preset(project.visuals.mapping_preset)
    palette = get_palette_preset(project.visuals.palette_preset)
    payload: dict[str, Any] = {
        "format": PREVIEW_FORMAT,
        "version": PREVIEW_VERSION,
        "release_slug": release_slug,
        "track_slug": track_slug,
        "source_revision": source_revision,
        "mode": "audio-reactive" if analysis_key else "geometry-only",
        "duration_seconds": duration,
        "video": {
            "width": project.video.width,
            "height": project.video.height,
            "background": _safe_background(
                project.video.background,
                release_slug=release_slug,
                track_slug=track_slug,
                scene_id=None,
            ),
            "seed": project.video.seed,
            "canvas_margin": project.visuals.canvas_margin,
            "perspective_strength": project.visuals.perspective_strength,
            "lyric_fade_seconds": project.visuals.lyric_fade_seconds,
        },
        "text": {
            "size": project.text.size,
            "maximum_width_fraction": project.text.maximum_width_fraction,
            "position": project.text.position,
            "active_color": project.text.active_color,
        },
        "mapping_preset": asdict(mapping),
        "palette_preset": asdict(palette),
        "custom_palette": list(project.visuals.palette),
        "actors": {
            actor_id: _safe_actor(actor)
            for actor_id, actor in sorted(project.visuals.actors.items())
        },
        "sections": sections,
        "compositions": compositions,
        "lyrics": [
            {"text": line.text, "start": line.start, "end": line.end}
            for section in lyrics.sections
            for line in section.lines
        ],
    }
    if reason is not None:
        payload["mode_reason"] = {
            **reason,
            "action_url": (
                f"/releases/{release_slug}/tracks/{track_slug}/video"
                if reason.get("action_url") == "track"
                else reason.get("action_url")
            ),
        }
    return payload


def _sample_state(
    project: Any,
    lyrics: Any,
    duration: float,
    analysis: Any,
) -> Any:
    import numpy as np

    from mrp.video.mappings import sample_audio_visual_state

    sample_count = math.ceil(duration * STATE_RATE_HZ) + 1
    if sample_count > MAX_STATE_SAMPLES:
        raise LivePreviewError(
            "sample_limit",
            f"Live Preview supports at most {MAX_STATE_SAMPLES} state samples.",
            status_code=413,
        )
    rows = np.empty((sample_count, STATE_WIDTH), dtype="<f4")
    section_indices = {
        section.id: index for index, section in enumerate(lyrics.sections)
    }
    for index in range(sample_count):
        at = min(duration, index / STATE_RATE_HZ)
        choreography = choreography_at(
            lyrics,
            at,
            transition_seconds=project.visuals.transition_seconds,
            visuals=project.visuals,
        )
        audio = sample_audio_visual_state(analysis, at)
        previous_index = (
            section_indices[choreography.previous_section_id]
            if choreography.previous_section_id is not None
            else -1
        )
        rows[index] = [
            section_indices[choreography.section_id],
            previous_index,
            *[
                value
                for role in SEMANTIC_ROLES
                for value in (
                    audio.for_role(role).energy,
                    audio.for_role(role).accent,
                )
            ],
            audio.spectral_centroid,
            choreography.transition_progress,
            choreography.layer_fraction,
            choreography.scale,
            choreography.motion,
            choreography.color_intensity,
            choreography.onset_response,
            choreography.palette_shift,
            choreography.lyrics_opacity,
            choreography.spatial_spread,
            choreography.anchor_drift,
            choreography.trail_length,
            choreography.beat_gain,
            choreography.intensity_gain,
            choreography.trace_time,
            choreography.rotation_time,
        ]
    return rows


def _encode(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except ValueError as exc:
        # allow_nan=False refuses NaN/Infinity rather than emitting JSON the
        # browser cannot parse. Surface it as a structured refusal, not a 500.
        raise LivePreviewError(
            "project_invalid",
            "The saved video project contains a value that cannot be previewed.",
        ) from exc


def _build_live_preview_document_local(
    root: Path,
    release_slug: str,
    release: dict[str, Any],
    track_slug: str,
    track: dict[str, Any],
) -> LivePreviewDocument:
    """Build one deterministic document without creating analysis or artifacts."""
    root = root.resolve()
    (
        source_project_path,
        project_raw,
        document,
        _source_lyrics_path,
        lyrics_raw,
        lyrics,
    ) = _load_source_documents(root, release_slug, release, track_slug, track)
    del source_project_path
    project = document.project
    key = track_key(release, track)
    duration = _master_duration(
        root,
        release,
        key,
        track,
        lyrics,
        _duration_tolerance(project),
    )
    availability = _existing_analysis(
        root,
        release,
        track,
        project,
        duration,
    )
    analysis_key = (
        availability.bundle.cache_key if availability.bundle is not None else None
    )
    source_revision = {
        "project_sha256": _sha256_bytes(project_raw),
        "lyrics_sha256": _sha256_bytes(lyrics_raw),
        "analysis_key": analysis_key,
        "renderer_contract": document.renderer_contract_version,
    }
    payload = _safe_base(
        release_slug=release_slug,
        track_slug=track_slug,
        project=project,
        lyrics=lyrics,
        duration=duration,
        source_revision=source_revision,
        analysis_key=analysis_key,
        reason=availability.reason,
    )

    if availability.bundle is not None:
        state = _sample_state(project, lyrics, duration, availability.bundle)
        payload.update(
            {
                "state_rate_hz": STATE_RATE_HZ,
                "state_encoding": STATE_ENCODING,
                "state_width": STATE_WIDTH,
                "state_sample_count": len(state),
                "state_schema": list(STATE_SCHEMA),
                "state_samples_base64": base64.b64encode(
                    state.tobytes(order="C")
                ).decode("ascii"),
            }
        )
        body = _encode(payload)
        if len(body) > MAX_RESPONSE_BYTES:
            for field in (
                "state_rate_hz",
                "state_encoding",
                "state_width",
                "state_sample_count",
                "state_schema",
                "state_samples_base64",
            ):
                payload.pop(field, None)
            payload["mode"] = "geometry-only"
            payload["mode_reason"] = {
                "code": "state_payload_too_large",
                "message": "Audio-reactive state exceeds the Live Preview size limit.",
                "action_url": (
                    f"/releases/{release_slug}/tracks/{track_slug}/video"
                ),
            }
            body = _encode(payload)
    else:
        body = _encode(payload)

    if len(body) > MAX_RESPONSE_BYTES:
        raise LivePreviewError(
            "response_limit",
            "Saved scene geometry exceeds the Live Preview response-size limit.",
            status_code=413,
        )
    etag = _sha256_bytes(body)
    return LivePreviewDocument(payload, body, etag)


def _video_dependencies_available() -> bool:
    return all(
        importlib.util.find_spec(name) is not None for name in ("librosa", "numpy")
    )


def _build_in_video_environment(
    root: Path,
    release_slug: str,
    track_slug: str,
) -> LivePreviewDocument:
    from mrp.admin.video_jobs import worker_python

    python = worker_python(root)
    environment = os.environ.copy()
    environment["MRP_LIVE_PREVIEW_WORKER"] = "1"
    command = [
        str(python),
        "-m",
        "mrp.admin.video_live_preview",
        "--repo",
        str(root),
        "--release",
        release_slug,
        "--track",
        track_slug,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            env=environment,
            capture_output=True,
            timeout=WORKER_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LivePreviewError(
            "analysis_environment_failed",
            "The isolated video environment could not build Live Preview data.",
            status_code=503,
        ) from exc
    header, separator, body = completed.stdout.partition(b"\n")
    try:
        marker, status_text, etag = header.decode("ascii").split(" ", maxsplit=2)
        status = int(status_text)
    except (UnicodeDecodeError, ValueError):
        marker, status, etag = "", 0, ""
    if marker != "MRP-LIVE-PREVIEW" or not separator:
        raise LivePreviewError(
            "analysis_environment_failed",
            "The isolated video environment returned an invalid preview response.",
            status_code=503,
        )
    if status != 200 or completed.returncode != 0:
        try:
            error = json.loads(body)
            value = error["error"]
            code = str(value["code"])
            message = str(value["message"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            code = "analysis_environment_failed"
            message = "The isolated video environment could not build Live Preview data."
            status = 503
        raise LivePreviewError(code, message, status_code=status)
    if len(body) > MAX_RESPONSE_BYTES:
        raise LivePreviewError(
            "response_limit",
            "Saved scene geometry exceeds the Live Preview response-size limit.",
            status_code=413,
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LivePreviewError(
            "analysis_environment_failed",
            "The isolated video environment returned invalid preview data.",
            status_code=503,
        ) from exc
    if not isinstance(payload, dict) or _sha256_bytes(body) != etag:
        raise LivePreviewError(
            "analysis_environment_failed",
            "The isolated video environment returned inconsistent preview data.",
            status_code=503,
        )
    return LivePreviewDocument(payload, body, etag)


def _path_signature(path: Path) -> tuple[int, int]:
    try:
        status = path.stat()
    except OSError:
        return (0, 0)
    return (status.st_mtime_ns, status.st_size)


def _tree_signature(path: Path) -> tuple[tuple[str, int, int], ...]:
    try:
        entries = sorted(path.rglob("*"))
    except OSError:
        return ()
    return tuple(
        (str(entry.relative_to(path)), *_path_signature(entry)) for entry in entries
    )


def _content_signature(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def _build_fingerprint(
    root: Path,
    release_slug: str,
    release: dict[str, Any],
    track_slug: str,
    track: dict[str, Any],
) -> tuple[Any, ...]:
    """Cheap inputs that fully determine one built document.

    Every source the builder reads is covered: the saved project and aligned
    timing by content, the release record and the track unit passed in, and the
    prepared analysis tier by modification signature. Anything unrecognized
    simply misses the memo and rebuilds.
    """
    key = track_key(release, track)
    return (
        PREVIEW_VERSION,
        STATE_SCHEMA,
        # Contract tunables are build inputs too: changing one changes the
        # document even when nothing on disk moved.
        (STATE_RATE_HZ, MAX_DURATION_SECONDS, MAX_RESPONSE_BYTES),
        str(root),
        release_slug,
        track_slug,
        key,
        _sha256_bytes(
            json.dumps(track, sort_keys=True, default=str).encode("utf-8")
        ),
        _content_signature(project_path(root, release, track)),
        _content_signature(aligned_path(root, release, track)),
        _path_signature(root / "content" / "releases" / f"{release_slug}.yaml"),
        _path_signature(_preflight_path(root, key)),
        _tree_signature(
            root / "assets" / "processed" / "video" / key / "analysis"
        ),
    )


_DOCUMENT_MEMO: dict[str, tuple[tuple[Any, ...], LivePreviewDocument]] = {}
_DOCUMENT_MEMO_LIMIT = 4


def _build_document(
    root: Path,
    release_slug: str,
    release: dict[str, Any],
    track_slug: str,
    track: dict[str, Any],
) -> LivePreviewDocument:
    """Build locally or through the existing isolated video interpreter."""
    if _video_dependencies_available():
        return _build_live_preview_document_local(
            root,
            release_slug,
            release,
            track_slug,
            track,
        )
    if os.environ.get("MRP_LIVE_PREVIEW_WORKER") == "1":
        raise LivePreviewError(
            "analysis_environment_missing",
            "The isolated video environment lacks required analysis dependencies.",
            status_code=503,
        )
    return _build_in_video_environment(root, release_slug, track_slug)


def build_live_preview_document(
    root: Path,
    release_slug: str,
    release: dict[str, Any],
    track_slug: str,
    track: dict[str, Any],
) -> LivePreviewDocument:
    """Return the document for the current saved state, rebuilding on change.

    Returning to the Live Preview tab re-checks the loaded revision, and a
    rebuild re-samples the whole choreography and audio timeline. Memoizing on
    a stat-and-hash fingerprint keeps those checks nearly free while any real
    edit to the project, timing, release, or analysis tier still rebuilds.
    Failures are never memoized.
    """
    root = root.resolve()
    fingerprint = _build_fingerprint(root, release_slug, release, track_slug, track)
    memo_key = f"{root}\0{release_slug}\0{track_slug}"
    cached = _DOCUMENT_MEMO.get(memo_key)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    document = _build_document(root, release_slug, release, track_slug, track)
    _DOCUMENT_MEMO.pop(memo_key, None)
    _DOCUMENT_MEMO[memo_key] = (fingerprint, document)
    while len(_DOCUMENT_MEMO) > _DOCUMENT_MEMO_LIMIT:
        _DOCUMENT_MEMO.pop(next(iter(_DOCUMENT_MEMO)))
    return document


def _main() -> int:
    import argparse

    from mrp.admin.workspace import track_units
    from mrp.core.migrate_site import load_structured_record

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--track", required=True)
    args = parser.parse_args()
    root = Path(args.repo).resolve()
    release_path = root / "content" / "releases" / f"{args.release}.yaml"
    try:
        release = load_structured_record(release_path).get("release") or {}
        unit = next(
            item for item in track_units(release) if item["slug"] == args.track
        )
        document = _build_live_preview_document_local(
            root,
            args.release,
            release,
            args.track,
            unit["track"],
        )
    except (OSError, StopIteration):
        error = LivePreviewError(
            "track_not_found",
            "The requested release track does not exist.",
            status_code=404,
        )
        body = _encode(error.payload())
        sys.stdout.buffer.write(
            f"MRP-LIVE-PREVIEW {error.status_code} -\n".encode("ascii") + body
        )
        return 1
    except LivePreviewError as error:
        body = _encode(error.payload())
        sys.stdout.buffer.write(
            f"MRP-LIVE-PREVIEW {error.status_code} -\n".encode("ascii") + body
        )
        return 1
    sys.stdout.buffer.write(
        f"MRP-LIVE-PREVIEW 200 {document.etag}\n".encode("ascii")
        + document.body
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
