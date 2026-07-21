import math
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from mrp.video.cards import validate_card_image
from mrp.video.encoder import (
    CancelCheck,
    OutputTimeline,
    encode_output,
    plan_output_timeline,
    validate_encoding_environment,
)
from mrp.video.render_manifest import build_render_manifest, write_render_manifest
from mrp.video.renderer import RenderContext, load_render_context
from mrp.video.verification import (
    VerificationReport,
    default_render_manifest_path,
    expectation_for,
    verify_media,
)

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class RenderRun:
    output_path: Path
    manifest_path: Path
    timeline: OutputTimeline
    verification: VerificationReport
    warnings: tuple[str, ...]
    profile: "RenderProfile"

    def summary(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "manifest_path": str(self.manifest_path),
            "draft": self.timeline.draft,
            "cards_included": self.timeline.include_cards,
            "frame_count": self.timeline.total_frames,
            "width": self.timeline.width,
            "height": self.timeline.height,
            "fps": self.timeline.fps,
            "duration": self.verification.metadata.duration,
            "video_codec": self.verification.metadata.video_codec,
            "pixel_format": self.verification.metadata.pixel_format,
            "audio_codec": self.verification.metadata.audio_codec,
            "audio_sample_rate": self.verification.metadata.audio_sample_rate,
            "audio_channels": self.verification.metadata.audio_channels,
            "warnings": list(self.warnings),
            "performance": self.profile.summary(),
            "verified": True,
        }


@dataclass(frozen=True, slots=True)
class RenderDiagnostics:
    raw_stream_bytes: int
    warnings: tuple[str, ...]

    @property
    def raw_stream_gib(self) -> float:
        return self.raw_stream_bytes / 1024**3

    def summary(self) -> dict[str, Any]:
        return {
            "raw_stream_bytes": self.raw_stream_bytes,
            "raw_stream_gib": self.raw_stream_gib,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class RenderProfile:
    preparation_seconds: float
    encoding_seconds: float
    verification_seconds: float
    pipeline_seconds: float
    frames_per_second: float
    realtime_factor: float
    raw_stream_bytes: int

    def summary(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RenderPlan:
    context: RenderContext
    timeline: OutputTimeline
    diagnostics: RenderDiagnostics

    def summary(self) -> dict[str, Any]:
        return {
            "draft": self.timeline.draft,
            "cards_included": self.timeline.include_cards,
            "frame_count": self.timeline.total_frames,
            "width": self.timeline.width,
            "height": self.timeline.height,
            "fps": self.timeline.fps,
            "duration": self.timeline.output_duration,
            "source_start": self.timeline.source_audio_start,
            "source_end": self.timeline.source_audio_end,
            "mapping_preset": self.context.project.visuals.mapping_preset,
            "palette_preset": self.context.project.visuals.palette_preset,
            "diagnostics": self.diagnostics.summary(),
        }


class SpirophonicPipelineError(Exception):
    pass


def _validate_output_targets(output: Path, manifest: Path, force: bool) -> None:
    invalid = [
        path
        for path in (output, manifest)
        if path.exists() and not path.is_file()
    ]
    if invalid:
        joined = ", ".join(str(path) for path in invalid)
        raise SpirophonicPipelineError(
            f"render output target is not a regular file: {joined}"
        )
    existing = [path for path in (output, manifest) if path.exists()]
    if existing and not force:
        joined = ", ".join(str(path) for path in existing)
        raise SpirophonicPipelineError(
            f"render output already exists: {joined}; use --force to overwrite"
        )
    if output.suffix.casefold() != ".mp4":
        raise SpirophonicPipelineError("render output must use a .mp4 extension")


def diagnose_render(
    context: RenderContext,
    timeline: OutputTimeline,
) -> RenderDiagnostics:
    warnings = list(context.warnings)
    aspect_ratio = timeline.width / timeline.height
    if not math.isclose(aspect_ratio, 16 / 9, rel_tol=1e-3, abs_tol=1e-3):
        warnings.append(
            f"output aspect ratio is {timeline.width}:{timeline.height}, not 16:9"
        )
    if timeline.fps > 60:
        warnings.append(f"high frame rate may render slowly: {timeline.fps:g} fps")
    if timeline.output_duration >= 3600:
        warnings.append(
            f"long render planned: {timeline.output_duration / 3600:.2f} hours"
        )
    raw_stream_bytes = (
        timeline.total_frames * timeline.width * timeline.height * 3
    )
    if raw_stream_bytes >= 500 * 1024**3:
        warnings.append(
            f"large raw RGB stream: {raw_stream_bytes / 1024**3:.1f} GiB "
            "will be piped, not stored"
        )
    return RenderDiagnostics(
        raw_stream_bytes=raw_stream_bytes,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def plan_project_video(
    manifest_path: Path,
    *,
    draft: bool = False,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    progress: ProgressCallback | None = None,
) -> RenderPlan:
    context = load_render_context(manifest_path, progress=progress)
    validate_encoding_environment(context)
    timeline = plan_output_timeline(
        context,
        draft=draft,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )
    if timeline.include_cards:
        validate_card_image(
            (context.root / context.project.cards.opening.file).resolve()
        )
        validate_card_image(
            (context.root / context.project.cards.closing.file).resolve()
        )
    return RenderPlan(context, timeline, diagnose_render(context, timeline))


def render_project_video(
    manifest_path: Path,
    output_path: Path,
    *,
    draft: bool = False,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    force: bool = False,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> RenderRun:
    """Render, encode, verify, and atomically publish one MP4 plus manifest."""
    notify = progress or (lambda _message: None)
    manifest = manifest_path.expanduser().resolve()
    output = output_path.expanduser().resolve()
    render_manifest = default_render_manifest_path(output)
    _validate_output_targets(output, render_manifest, force)
    output.parent.mkdir(parents=True, exist_ok=True)

    pipeline_started = time.perf_counter()
    preparation_started = time.perf_counter()
    plan = plan_project_video(
        manifest,
        draft=draft,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        progress=progress,
    )
    preparation_seconds = time.perf_counter() - preparation_started
    context = plan.context
    timeline = plan.timeline
    raw_gib = plan.diagnostics.raw_stream_gib
    notify(
        f"Render plan: {timeline.total_frames} frames, "
        f"{timeline.width}x{timeline.height} at {timeline.fps:g} fps, "
        f"{raw_gib:.2f} GiB raw RGB streamed"
    )
    temporary_video = output.with_name(f".{output.name}.{os.getpid()}.tmp.mp4")
    temporary_manifest = render_manifest.with_name(
        f".{render_manifest.name}.{os.getpid()}.tmp"
    )
    temporary_video.unlink(missing_ok=True)
    temporary_manifest.unlink(missing_ok=True)
    try:
        notify("Streaming deterministic RGB frames to FFmpeg")
        encoding_result = encode_output(
            context,
            timeline,
            master_path=(context.root / context.project.audio.master).resolve(),
            output_path=temporary_video,
            progress=progress,
            cancel_check=cancel_check,
        )
        expectation = expectation_for(context, timeline)
        notify("Verifying encoded media with ffprobe")
        verification_started = time.perf_counter()
        verification = verify_media(temporary_video, expectation)
        verification_seconds = time.perf_counter() - verification_started
        profile = RenderProfile(
            preparation_seconds=preparation_seconds,
            encoding_seconds=encoding_result.elapsed_seconds,
            verification_seconds=verification_seconds,
            pipeline_seconds=time.perf_counter() - pipeline_started,
            frames_per_second=encoding_result.frames_per_second,
            realtime_factor=(
                timeline.output_duration
                / max(encoding_result.elapsed_seconds, 1e-9)
            ),
            raw_stream_bytes=plan.diagnostics.raw_stream_bytes,
        )
        payload = build_render_manifest(
            context,
            timeline,
            expectation,
            verification,
            project_manifest_path=manifest,
            output_path=output,
            encoded_path=temporary_video,
            command=encoding_result.command,
            performance=profile.summary(),
            warnings=plan.diagnostics.warnings,
        )
        write_render_manifest(temporary_manifest, payload)
        notify("Publishing verified output")
        os.replace(temporary_video, output)
        os.replace(temporary_manifest, render_manifest)
    finally:
        temporary_video.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)

    final_verification = replace(verification, path=output)
    return RenderRun(
        output_path=output,
        manifest_path=render_manifest,
        timeline=timeline,
        verification=final_verification,
        warnings=plan.diagnostics.warnings,
        profile=profile,
    )
