"""Deterministic text -> SVG outline for the ``text`` actor geometry.

Turns a string into a single multi-subpath ``d`` (one subpath per glyph
contour) using a real font, so artist-name and song-title actors are always
legible — unlike AI-drawn letterforms. The result is stored as a ``text``
geometry layer; the renderer draws each contour with the actor's spiro trace.
"""

from __future__ import annotations

import os
from pathlib import Path

from mrp.admin.video_casting import CastingEditorError

# Reuse the fonts the renderer already resolves (video_workspace._default_font).
_FONT_FALLBACKS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def resolve_font(root: Path, font: str | None = None) -> Path:
    """Pick a usable font file: explicit arg, MRP_VIDEO_FONT, then fallbacks."""
    candidates: list[Path] = []
    if font:
        candidates.append(Path(font).expanduser())
    configured = os.environ.get("MRP_VIDEO_FONT")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(Path(path) for path in _FONT_FALLBACKS)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise CastingEditorError(
        "text outline requires a font; set MRP_VIDEO_FONT or install DejaVu"
    )


def text_to_path_data(
    text: str,
    font_path: Path,
    *,
    tracking: float = 0.0,
) -> str:
    """Lay out ``text`` in the font as one multi-subpath SVG ``d`` string.

    Glyphs are positioned by their advance widths (``tracking`` adds fractional
    letter-spacing, in em units) and y-flipped from font space (y-up) to screen
    space (y-down) so the word is upright. Whitespace advances without drawing.
    """
    try:
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.ttLib import TTFont
        from svgpathtools import parse_path
        from svgpathtools.path import transform as transform_path
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment guard
        raise CastingEditorError(
            "text outline requires fonttools + svgpathtools; install requirements.txt"
        ) from exc

    text = text.strip()
    if not text:
        raise CastingEditorError("text outline requires a non-empty string")

    try:
        font = TTFont(str(font_path))
        glyph_set = font.getGlyphSet()
        cmap = font.getBestCmap()
        hmtx = font["hmtx"]
        units_per_em = font["head"].unitsPerEm or 1000
    except Exception as exc:
        raise CastingEditorError(f"text outline could not load the font: {exc}") from exc

    pen_x = 0.0
    subpaths: list[str] = []
    drawn = 0
    for char in text:
        glyph_name = cmap.get(ord(char))
        if glyph_name is None:
            # Unmapped char: advance by a space-width guess so layout survives.
            pen_x += units_per_em * 0.3
            continue
        advance = hmtx[glyph_name][0]
        pen = SVGPathPen(glyph_set)
        glyph_set[glyph_name].draw(pen)
        commands = pen.getCommands()
        if commands.strip():
            # matrix(1,0,0,-1, pen_x, 0): translate to the pen, flip y upright.
            matrix = np.array([[1, 0, pen_x], [0, -1, 0], [0, 0, 1]])
            try:
                positioned = transform_path(parse_path(commands), matrix).d()
            except Exception as exc:
                raise CastingEditorError(
                    f"text outline could not place glyph {char!r}: {exc}"
                ) from exc
            subpaths.append(positioned)
            drawn += 1
        pen_x += advance + tracking * units_per_em

    if drawn == 0:
        raise CastingEditorError(
            "text outline produced no drawable glyphs (only spaces or unsupported "
            "characters)"
        )
    return " ".join(subpaths)
