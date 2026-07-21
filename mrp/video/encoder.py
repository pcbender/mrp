import math
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from mrp.video.cards import PreparedCards, blend_frames, prepare_cards
from mrp.video.renderer import RenderContext, render_dimensions, render_frame

ProgressCallback = Callable[[str], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class OutputTimeline:
    width: int
    height: int
    fps: float
    draft: bool
    include_cards: bool
    source_start_frame: int
    source_end_frame: int
    source_audio_start: float
    source_audio_end: float
    opening_frames: int
    closing_frames: int
    opening_fade_frames: int
    closing_fade_frames: int

    @property
    def song_frames(self) -> int:
        return self.source_end_frame - self.source_start_frame

    @property
    def total_frames(self) -> int:
        return self.opening_frames + self.song_frames + self.closing_frames

    @property
    def output_duration(self) -> float:
        return self.total_frames / self.fps

    @property
    def opening_duration(self) -> float:
        return self.opening_frames / self.fps

    @property
    def closing_duration(self) -> float:
        return self.closing_frames / self.fps

    @property
    def source_audio_duration(self) -> float:
        return self.source_audio_end - self.source_audio_start

    @property
    def audio_post_padding(self) -> float:
        return max(
            0,
            self.output_duration
            - self.opening_duration
            - self.source_audio_duration,
        )


class SpirophonicEncodingError(Exception):
    pass


class SpirophonicCancelledError(SpirophonicEncodingError):
    pass


@dataclass(frozen=True, slots=True)
class EncodingResult:
    command: tuple[str, ...]
    elapsed_seconds: float
    frames_per_second: float


def validate_encoding_environment(context: RenderContext) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SpirophonicEncodingError("required executable is not on PATH: ffmpeg")
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SpirophonicEncodingError(
            f"could not inspect FFmpeg encoders: {exc}"
        ) from exc
    required = (
        context.project.encoding.video_codec,
        context.project.encoding.audio_codec,
    )
    missing = [encoder for encoder in required if encoder not in result.stdout]
    if missing:
        raise SpirophonicEncodingError(
            f"FFmpeg is missing required encoders: {', '.join(missing)}"
        )


def _frames_for_duration(duration: float, fps: float) -> int:
    return max(0, math.floor(duration * fps + 0.5))


def plan_output_timeline(
    context: RenderContext,
    *,
    draft: bool = False,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> OutputTimeline:
    """Plan either the complete card/song/card output or a song-time excerpt."""
    duration = context.analysis.duration
    range_requested = start_seconds is not None or end_seconds is not None
    start = 0.0 if start_seconds is None else start_seconds
    end = duration if end_seconds is None else end_seconds
    if not math.isfinite(start) or not math.isfinite(end):
        raise SpirophonicEncodingError("render range must contain finite times")
    if start < 0 or end <= start:
        raise SpirophonicEncodingError("render range must have a positive duration")
    if end > duration + context.project.audio.duration_tolerance:
        raise SpirophonicEncodingError(
            "render range extends beyond the master duration"
        )

    width, height, fps = render_dimensions(context.project, draft=draft)
    source_start_frame = math.ceil(start * fps - 1e-9)
    source_end_frame = math.ceil(min(end, duration) * fps - 1e-9)
    if source_end_frame <= source_start_frame:
        raise SpirophonicEncodingError("render range contains no frames")
    source_audio_start = source_start_frame / fps
    source_audio_end = min(end, duration)
    if source_audio_end <= source_audio_start:
        raise SpirophonicEncodingError("render range contains no master audio")

    include_cards = not range_requested
    opening_frames = 0
    closing_frames = 0
    opening_fade_frames = 0
    closing_fade_frames = 0
    if include_cards:
        opening = context.project.cards.opening
        closing = context.project.cards.closing
        opening_frames = _frames_for_duration(opening.duration, fps)
        closing_frames = _frames_for_duration(closing.duration, fps)
        opening_fade_frames = min(
            opening_frames,
            _frames_for_duration(opening.fade, fps),
        )
        closing_fade_frames = min(
            closing_frames,
            _frames_for_duration(closing.fade, fps),
        )
    return OutputTimeline(
        width=width,
        height=height,
        fps=fps,
        draft=draft,
        include_cards=include_cards,
        source_start_frame=source_start_frame,
        source_end_frame=source_end_frame,
        source_audio_start=source_audio_start,
        source_audio_end=source_audio_end,
        opening_frames=opening_frames,
        closing_frames=closing_frames,
        opening_fade_frames=opening_fade_frames,
        closing_fade_frames=closing_fade_frames,
    )


def _prepared_cards(
    context: RenderContext,
    timeline: OutputTimeline,
) -> PreparedCards:
    return prepare_cards(
        context.project.cards.opening,
        context.project.cards.closing,
        opening_path=(context.root / context.project.cards.opening.file).resolve(),
        closing_path=(context.root / context.project.cards.closing.file).resolve(),
        width=timeline.width,
        height=timeline.height,
    )


def _opening_card_frame(
    card: NDArray[np.uint8],
    first_song_frame: NDArray[np.uint8],
    index: int,
    timeline: OutputTimeline,
) -> NDArray[np.uint8]:
    fade = timeline.opening_fade_frames
    fade_start = timeline.opening_frames - fade
    if fade <= 0 or index < fade_start:
        return card
    if fade == 1:
        return blend_frames(first_song_frame, card, 0.5)
    card_amount = (timeline.opening_frames - 1 - index) / (fade - 1)
    return blend_frames(first_song_frame, card, card_amount)


def _closing_card_frame(
    card: NDArray[np.uint8],
    last_song_frame: NDArray[np.uint8],
    index: int,
    timeline: OutputTimeline,
) -> NDArray[np.uint8]:
    fade = timeline.closing_fade_frames
    if fade <= 0 or index >= fade:
        return card
    if fade == 1:
        return blend_frames(last_song_frame, card, 0.5)
    card_amount = (index + 1) / fade
    return blend_frames(last_song_frame, card, card_amount)


def iter_output_frames(
    context: RenderContext,
    timeline: OutputTimeline,
) -> Iterator[NDArray[np.uint8]]:
    """Yield the complete output timeline without writing intermediate images."""
    first_index = timeline.source_start_frame
    last_index = timeline.source_end_frame - 1
    first_song_frame = render_frame(
        context,
        first_index / timeline.fps,
        first_index,
        width=timeline.width,
        height=timeline.height,
    )
    last_song_frame = (
        first_song_frame
        if last_index == first_index
        else render_frame(
            context,
            last_index / timeline.fps,
            last_index,
            width=timeline.width,
            height=timeline.height,
        )
    )

    cards = _prepared_cards(context, timeline) if timeline.include_cards else None
    if cards is not None:
        for index in range(timeline.opening_frames):
            yield _opening_card_frame(
                cards.opening,
                first_song_frame,
                index,
                timeline,
            )

    for frame_index in range(first_index, timeline.source_end_frame):
        if frame_index == first_index:
            yield first_song_frame
        elif frame_index == last_index:
            yield last_song_frame
        else:
            yield render_frame(
                context,
                frame_index / timeline.fps,
                frame_index,
                width=timeline.width,
                height=timeline.height,
            )

    if cards is not None:
        for index in range(timeline.closing_frames):
            yield _closing_card_frame(
                cards.closing,
                last_song_frame,
                index,
                timeline,
            )


def build_ffmpeg_command(
    context: RenderContext,
    timeline: OutputTimeline,
    *,
    master_path: Path,
    output_path: Path,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    encoding = context.project.encoding
    delay_milliseconds = round(timeline.opening_duration * 1000)
    audio_filter = (
        f"[1:a:0]atrim=start={timeline.source_audio_start:.9f}:"
        f"end={timeline.source_audio_end:.9f},"
        "asetpts=PTS-STARTPTS,"
        f"aresample={encoding.audio_sample_rate},"
        "aformat=channel_layouts=stereo,"
        f"adelay={delay_milliseconds}:all=1,"
        f"apad=pad_dur={timeline.audio_post_padding:.9f}[aout]"
    )
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        f"{timeline.width}x{timeline.height}",
        "-framerate",
        f"{timeline.fps:.12g}",
        "-i",
        "pipe:0",
        "-i",
        str(master_path),
        "-filter_complex",
        audio_filter,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-frames:v",
        str(timeline.total_frames),
        "-fps_mode",
        "cfr",
        "-c:v",
        encoding.video_codec,
        "-preset",
        encoding.preset,
        "-crf",
        str(encoding.crf),
        "-threads",
        str(encoding.threads),
        "-pix_fmt",
        encoding.pixel_format,
        "-c:a",
        encoding.audio_codec,
        "-b:a",
        f"{encoding.audio_bitrate_kbps}k",
        "-ar",
        str(encoding.audio_sample_rate),
        "-ac",
        str(encoding.audio_channels),
        "-t",
        f"{timeline.output_duration:.9f}",
        "-map_metadata",
        "-1",
        "-metadata",
        "creation_time=1970-01-01T00:00:00Z",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(output_path),
    ]
    return command


def encode_output(
    context: RenderContext,
    timeline: OutputTimeline,
    *,
    master_path: Path,
    output_path: Path,
    progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> EncodingResult:
    """Stream RGB frames to FFmpeg and return the exact command arguments."""
    notify = progress or (lambda _message: None)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SpirophonicEncodingError("required executable is not on PATH: ffmpeg")
    command = build_ffmpeg_command(
        context,
        timeline,
        master_path=master_path,
        output_path=output_path,
        ffmpeg=ffmpeg,
    )
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    stderr = b""
    started = time.perf_counter()
    try:
        if process.stdin is None:
            raise SpirophonicEncodingError("FFmpeg raw-video input is unavailable")
        progress_interval = max(1, round(timeline.fps * 5))
        frames = iter_output_frames(context, timeline)
        for count in range(1, timeline.total_frames + 1):
            if cancel_check is not None and cancel_check():
                raise SpirophonicCancelledError(
                    f"render cancelled before frame {count} of {timeline.total_frames}"
                )
            try:
                frame = next(frames)
            except StopIteration as exc:
                raise SpirophonicEncodingError(
                    f"renderer stopped after {count - 1} of "
                    f"{timeline.total_frames} planned frames"
                ) from exc
            if frame.shape != (timeline.height, timeline.width, 3):
                raise SpirophonicEncodingError(
                    f"renderer returned an invalid frame shape: {frame.shape}"
                )
            process.stdin.write(np.ascontiguousarray(frame).tobytes())
            if (
                count == 1
                or count == timeline.total_frames
                or count % progress_interval == 0
            ):
                elapsed = max(time.perf_counter() - started, 1e-9)
                rate = count / elapsed
                remaining = (timeline.total_frames - count) / rate
                percent = count / timeline.total_frames * 100
                notify(
                    f"Encoded frame {count} of {timeline.total_frames} "
                    f"({percent:.1f}%, {rate:.1f} fps, ETA {remaining:.1f}s)"
                )
        try:
            next(frames)
        except StopIteration:
            pass
        else:
            raise SpirophonicEncodingError(
                f"renderer produced more than {timeline.total_frames} planned frames"
            )
        process.stdin.close()
        return_code = process.wait()
        if process.stderr is not None:
            stderr = process.stderr.read()
    except (BrokenPipeError, OSError) as exc:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        process.wait()
        if process.stderr is not None:
            stderr = process.stderr.read()
        detail = stderr.decode(errors="replace").strip()
        raise SpirophonicEncodingError(
            f"FFmpeg encoding failed: {detail or exc}"
        ) from exc
    except BaseException:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        process.terminate()
        process.wait()
        raise
    finally:
        if process.stderr is not None:
            process.stderr.close()
    if return_code != 0:
        detail = stderr.decode(errors="replace").strip()
        raise SpirophonicEncodingError(
            f"FFmpeg exited with code {return_code}: {detail or 'no diagnostic'}"
        )
    elapsed = time.perf_counter() - started
    return EncodingResult(
        command=tuple(command),
        elapsed_seconds=elapsed,
        frames_per_second=timeline.total_frames / max(elapsed, 1e-9),
    )
