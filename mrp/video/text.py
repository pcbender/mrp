from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

from mrp.video.project import (
    AlignedLyrics,
    LyricLine,
    StructuredLyrics,
    TextConfig,
)


@dataclass(frozen=True, slots=True)
class LyricCue:
    text: str
    alpha: float


class SpirophonicTextError(Exception):
    pass


def validate_lyric_font(font_path: Path, size: int) -> None:
    try:
        ImageFont.truetype(str(font_path), size=size)
    except OSError as exc:
        raise SpirophonicTextError(
            f"cannot load lyric font {font_path}: {exc}"
        ) from exc


def _clamp01(value: float) -> float:
    return min(1, max(0, value))


def _smoothstep(value: float) -> float:
    value = _clamp01(value)
    return value * value * (3 - 2 * value)


def lyric_cue_at(
    lyrics: AlignedLyrics,
    time_seconds: float,
    *,
    fade_seconds: float,
    choreography_opacity: float,
) -> LyricCue | None:
    for section in lyrics.sections:
        if not section.start <= time_seconds < section.end:
            continue
        for line in section.lines:
            if not line.start <= time_seconds < line.end:
                continue
            alpha = choreography_opacity
            if fade_seconds > 0:
                alpha *= _smoothstep((time_seconds - line.start) / fade_seconds)
                alpha *= _smoothstep((line.end - time_seconds) / fade_seconds)
            return LyricCue(
                text=line.text,
                alpha=_clamp01(alpha),
            )
    return None


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def _load_font(
    font_path: Path,
    size: int,
) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(font_path), size=size)
    except OSError as exc:
        raise SpirophonicTextError(
            f"cannot load lyric font {font_path}: {exc}"
        ) from exc


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> int:
    stroke_width = max(1, font.size // 30)
    bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return bounds[2] - bounds[0]


def _boundary_bonus(words: tuple[str, ...], end: int) -> float:
    if end >= len(words):
        return 0
    previous = words[end - 1]
    following = words[end].casefold().strip("\"'([{“‘")
    if previous.endswith((",", ";", ":", "—", "–")):
        return 2.0
    if previous.endswith((".", "!", "?")):
        return 1.8
    if following in {"and", "but", "or", "because", "if", "so", "when", "while"}:
        return 0.35
    return 0


def split_lyric_text(
    text: str,
    *,
    font_path: Path,
    size: int,
    maximum_width: int,
) -> tuple[str, ...]:
    """Split an oversized lyric into sequential single-line display cues."""
    if maximum_width <= 0:
        raise SpirophonicTextError("maximum lyric width must be positive")
    font = _load_font(font_path, size)
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    if _text_width(draw, text, font) <= maximum_width:
        return (text,)

    words = tuple(text.split())
    if not words:
        raise SpirophonicTextError("lyric text must not be blank")
    for word in words:
        if _text_width(draw, word, font) > maximum_width:
            raise SpirophonicTextError(
                f"lyric word does not fit at the configured size: {word}"
            )

    @cache
    def solve(start: int) -> tuple[int, float, tuple[str, ...]] | None:
        if start == len(words):
            return (0, 0, ())
        best: tuple[int, float, tuple[str, ...]] | None = None
        for end in range(start + 1, len(words) + 1):
            fragment = " ".join(words[start:end])
            width = _text_width(draw, fragment, font)
            if width > maximum_width:
                break
            remainder = solve(end)
            if remainder is None:
                continue
            raggedness = (1 - width / maximum_width) ** 2
            candidate = (
                remainder[0] + 1,
                remainder[1] + raggedness - _boundary_bonus(words, end),
                (fragment, *remainder[2]),
            )
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        return best

    result = solve(0)
    if result is None:
        raise SpirophonicTextError("lyric text cannot be split to fit")
    return result[2]


def segment_lyrics_for_display(
    lyrics: StructuredLyrics,
    *,
    font_path: Path,
    config: TextConfig,
    video_width: int,
) -> tuple[StructuredLyrics, tuple[str, ...]]:
    """Create aligned-input cues that fit without changing the canonical source."""
    maximum_width = round(video_width * config.maximum_width_fraction)
    warnings: list[str] = []
    sections = []
    for section in lyrics.sections:
        segmented_lines: list[LyricLine] = []
        for line_index, line in enumerate(section.lines):
            fragments = split_lyric_text(
                line.text,
                font_path=font_path,
                size=config.size,
                maximum_width=maximum_width,
            )
            segmented_lines.extend(LyricLine(text=fragment) for fragment in fragments)
            if len(fragments) > 1:
                warnings.append(
                    f"{section.id} line {line_index + 1} split into "
                    f"{len(fragments)} sequential display cues"
                )
        sections.append(section.model_copy(update={"lines": segmented_lines}))
    return lyrics.model_copy(update={"sections": sections}), tuple(warnings)


def draw_lyric_overlay(
    frame: NDArray[np.uint8],
    cue: LyricCue | None,
    *,
    config: TextConfig,
    font_path: Path,
    reference_height: int,
) -> NDArray[np.uint8]:
    """Draw one fixed-size single-line lyric cue with deterministic layout."""
    if cue is None or cue.alpha <= 0:
        return frame
    image = Image.fromarray(frame, mode="RGB")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    display_size = max(1, round(config.size * height / reference_height))
    font = _load_font(font_path, display_size)
    stroke_width = max(1, font.size // 30)
    bounds = draw.textbbox(
        (0, 0),
        cue.text,
        font=font,
        stroke_width=stroke_width,
    )
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    maximum_width = round(width * config.maximum_width_fraction)
    if text_width > maximum_width:
        raise SpirophonicTextError(
            "lyric cue exceeds the configured fixed-width safe region; "
            "run 'scripts/mrp video align --force' to split display cues"
        )
    x = (width - text_width) // 2 - bounds[0]
    if config.position == "top":
        y = round(height * 0.11) - bounds[1]
    elif config.position == "center":
        y = (height - text_height) // 2 - bounds[1]
    else:
        y = round(height * 0.82) - bounds[1]

    edge_margin = max(4, round(height * 0.04))
    minimum_y = edge_margin - bounds[1]
    maximum_y = height - edge_margin - bounds[3]
    y = min(maximum_y, max(minimum_y, y))
    color = (*_parse_hex_color(config.active_color), round(255 * cue.alpha))
    draw.text(
        (x, y),
        cue.text,
        font=font,
        fill=color,
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, round(210 * cue.alpha)),
    )

    composited = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    return np.asarray(composited, dtype=np.uint8)
