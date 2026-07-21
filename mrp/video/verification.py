import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from mrp.video.encoder import OutputTimeline
from mrp.video.renderer import RenderContext


@dataclass(frozen=True, slots=True)
class VerificationExpectation:
    width: int
    height: int
    fps: float
    duration: float
    duration_tolerance: float
    video_codec: str = "h264"
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_profile: str = "LC"
    audio_sample_rate: int = 48000
    audio_channels: int = 2

    def summary(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    format_name: str
    duration: float
    width: int
    height: int
    fps: float
    sample_aspect_ratio: str
    display_aspect_ratio: str
    video_codec: str
    pixel_format: str
    field_order: str
    audio_codec: str
    audio_profile: str
    audio_sample_rate: int
    audio_channels: int
    stream_count: int
    faststart: bool

    def summary(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VerificationReport:
    path: Path
    expectation: VerificationExpectation
    metadata: MediaMetadata
    checks: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "valid": True,
            "expectation": self.expectation.summary(),
            "metadata": self.metadata.summary(),
            "checks": list(self.checks),
        }


class SpirophonicVerificationError(Exception):
    def __init__(self, *problems: str):
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expectation_for(
    context: RenderContext,
    timeline: OutputTimeline,
) -> VerificationExpectation:
    encoding = context.project.encoding
    return VerificationExpectation(
        width=timeline.width,
        height=timeline.height,
        fps=timeline.fps,
        duration=timeline.output_duration,
        duration_tolerance=max(
            encoding.duration_tolerance,
            1 / timeline.fps + 0.02,
        ),
        pixel_format=encoding.pixel_format,
        audio_sample_rate=encoding.audio_sample_rate,
        audio_channels=encoding.audio_channels,
    )


def _fraction(value: str) -> float:
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise SpirophonicVerificationError(
            f"ffprobe returned an invalid frame rate: {value}"
        ) from exc


def _probe(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise SpirophonicVerificationError(
            "required executable is not on PATH: ffprobe"
        )
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
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
        raise SpirophonicVerificationError(
            f"ffprobe could not inspect {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SpirophonicVerificationError("ffprobe response must be a JSON object")
    return payload


def _has_faststart(path: Path) -> bool:
    positions: dict[bytes, int] = {}
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        position = 0
        while position + 8 <= file_size:
            stream.seek(position)
            header = stream.read(8)
            if len(header) != 8:
                break
            atom_size = int.from_bytes(header[:4], "big")
            atom_type = header[4:]
            header_size = 8
            if atom_size == 1:
                extended = stream.read(8)
                if len(extended) != 8:
                    break
                atom_size = int.from_bytes(extended, "big")
                header_size = 16
            elif atom_size == 0:
                atom_size = file_size - position
            if atom_size < header_size:
                break
            if atom_type in {b"moov", b"mdat"}:
                positions.setdefault(atom_type, position)
            position += atom_size
    return b"moov" in positions and b"mdat" in positions and (
        positions[b"moov"] < positions[b"mdat"]
    )


def _metadata(payload: dict[str, Any], path: Path) -> MediaMetadata:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise SpirophonicVerificationError("ffprobe returned no stream list")
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise SpirophonicVerificationError(
            f"expected one video and one audio stream; found {len(videos)} and "
            f"{len(audios)}"
        )
    video = videos[0]
    audio = audios[0]
    format_data = payload.get("format") or {}
    try:
        return MediaMetadata(
            format_name=str(format_data["format_name"]),
            duration=float(format_data["duration"]),
            width=int(video["width"]),
            height=int(video["height"]),
            fps=_fraction(str(video["avg_frame_rate"])),
            sample_aspect_ratio=str(video.get("sample_aspect_ratio", "")),
            display_aspect_ratio=str(video.get("display_aspect_ratio", "")),
            video_codec=str(video["codec_name"]),
            pixel_format=str(video["pix_fmt"]),
            field_order=str(video.get("field_order", "unknown")),
            audio_codec=str(audio["codec_name"]),
            audio_profile=str(audio.get("profile", "")),
            audio_sample_rate=int(audio["sample_rate"]),
            audio_channels=int(audio["channels"]),
            stream_count=len(streams),
            faststart=_has_faststart(path),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SpirophonicVerificationError(
            "ffprobe response is missing required output metadata"
        ) from exc


def _aspect_ratio_matches(metadata: MediaMetadata) -> bool:
    value = metadata.display_aspect_ratio
    if not value or value == "N/A":
        return True
    try:
        numerator, denominator = value.split(":", maxsplit=1)
        reported = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return False
    expected = metadata.width / metadata.height
    return math.isclose(reported, expected, rel_tol=1e-3, abs_tol=1e-3)


def verify_media(
    path: Path,
    expectation: VerificationExpectation,
) -> VerificationReport:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise SpirophonicVerificationError(f"rendered video does not exist: {resolved}")
    metadata = _metadata(_probe(resolved), resolved)
    problems: list[str] = []
    if "mp4" not in metadata.format_name.split(","):
        problems.append(f"container is not MP4: {metadata.format_name}")
    if (metadata.width, metadata.height) != (expectation.width, expectation.height):
        problems.append(
            f"resolution is {metadata.width}x{metadata.height}; expected "
            f"{expectation.width}x{expectation.height}"
        )
    if not math.isclose(metadata.fps, expectation.fps, rel_tol=1e-6, abs_tol=1e-6):
        problems.append(f"frame rate is {metadata.fps:g}; expected {expectation.fps:g}")
    if metadata.video_codec != expectation.video_codec:
        problems.append(
            f"video codec is {metadata.video_codec}; expected {expectation.video_codec}"
        )
    if metadata.pixel_format != expectation.pixel_format:
        problems.append(
            f"pixel format is {metadata.pixel_format}; expected "
            f"{expectation.pixel_format}"
        )
    if metadata.field_order not in {"progressive", "unknown"}:
        problems.append(f"video is not progressive: {metadata.field_order}")
    if metadata.sample_aspect_ratio not in {"", "N/A", "1:1"}:
        problems.append(
            f"sample aspect ratio is not square: {metadata.sample_aspect_ratio}"
        )
    if not _aspect_ratio_matches(metadata):
        problems.append(
            f"display aspect ratio is inconsistent: {metadata.display_aspect_ratio}"
        )
    if metadata.audio_codec != expectation.audio_codec:
        problems.append(
            f"audio codec is {metadata.audio_codec}; expected {expectation.audio_codec}"
        )
    if metadata.audio_profile != expectation.audio_profile:
        problems.append(
            f"audio profile is {metadata.audio_profile}; expected "
            f"{expectation.audio_profile}"
        )
    if metadata.audio_sample_rate != expectation.audio_sample_rate:
        problems.append(
            f"audio sample rate is {metadata.audio_sample_rate}; expected "
            f"{expectation.audio_sample_rate}"
        )
    if metadata.audio_channels != expectation.audio_channels:
        problems.append(
            f"audio channel count is {metadata.audio_channels}; expected "
            f"{expectation.audio_channels}"
        )
    if metadata.stream_count != 2:
        problems.append(f"output contains {metadata.stream_count} streams; expected 2")
    if not metadata.faststart:
        problems.append("MP4 metadata is not placed before media data for faststart")
    difference = abs(metadata.duration - expectation.duration)
    if difference > expectation.duration_tolerance:
        problems.append(
            f"duration is {metadata.duration:.3f}s; expected "
            f"{expectation.duration:.3f}s (+/- {expectation.duration_tolerance:.3f}s)"
        )
    if problems:
        raise SpirophonicVerificationError(*problems)
    checks = (
        "MP4 container opens",
        "one H.264 progressive yuv420p video stream",
        "configured resolution and frame rate",
        "square pixels and faststart metadata placement",
        "one AAC-LC stereo 48 kHz audio stream",
        "duration within configured tolerance",
        "no unexpected streams",
    )
    return VerificationReport(resolved, expectation, metadata, checks)


def default_render_manifest_path(video_path: Path) -> Path:
    return video_path.with_suffix(".render.json")


def expectation_from_render_manifest(path: Path) -> VerificationExpectation:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload["output"]["expectation"]
        return VerificationExpectation(**value)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SpirophonicVerificationError(
            f"cannot load verification expectation from {path}: {exc}"
        ) from exc


def _output_hash_from_render_manifest(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload["output"]["sha256"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SpirophonicVerificationError(
            f"cannot load output hash from {path}: {exc}"
        ) from exc
    if not isinstance(value, str) or len(value) != 64:
        raise SpirophonicVerificationError(
            f"render manifest contains an invalid output hash: {path}"
        )
    return value


def verify_with_render_manifest(
    video_path: Path,
    manifest_path: Path | None = None,
) -> VerificationReport:
    resolved_video = video_path.expanduser().resolve()
    resolved_manifest = (
        manifest_path.expanduser().resolve()
        if manifest_path is not None
        else default_render_manifest_path(resolved_video)
    )
    expectation = expectation_from_render_manifest(resolved_manifest)
    expected_hash = _output_hash_from_render_manifest(resolved_manifest)
    try:
        actual_hash = _hash_file(resolved_video)
    except OSError as exc:
        raise SpirophonicVerificationError(
            f"cannot hash rendered video {resolved_video}: {exc}"
        ) from exc
    if actual_hash != expected_hash:
        raise SpirophonicVerificationError(
            "rendered video hash does not match its render manifest"
        )
    return verify_media(resolved_video, expectation)
