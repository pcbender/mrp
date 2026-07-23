"""AI generation of raw SVG shapes for the Actor Designer.

The model draws only the shapes — humans give them life in the designer
(trace, color, drivers). Every generated document is validated through
``split_svg_subpaths`` so whatever comes back is guaranteed importable as
path-family actor components.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from mrp.admin.video_casting import CastingEditorError, split_svg_subpaths
from mrp.core.spotify_client import load_dotenv

MODEL = "claude-opus-4-8"
MAX_TOKENS = 16000

_SVG_BLOCK = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.IGNORECASE)

_SYSTEM_PROMPT = """\
You design line-art marks for a music-video renderer that draws every shape
as an animated stroke trace (no fills are ever painted). Respond with ONE
SVG document and nothing else.

Hard requirements:
- A single <svg> element with viewBox="0 0 512 512".
- Only these drawable elements: <path>, <circle>, <ellipse>, <rect>,
  <polygon>, <polyline>, <line>. No <text>, <g>, <defs>, <use>, transforms,
  gradients, images, styles, or fill/stroke attributes.
- Each <path> d attribute must hold exactly ONE subpath (a single M command).
- At most {max_subpaths} drawable elements in total.
- Design for stroke tracing: bold, legible line work that reads at small
  sizes. Lettering must be drawn as path outlines or single-stroke lines,
  never <text>.
"""


def _anthropic_client(repo: Path) -> Any:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - environment guard
        import sys

        raise CastingEditorError(
            "svg generation requires the anthropic package; the admin is "
            f"running under {sys.executable} — install requirements.txt into "
            "that environment (or restart the admin from the repo .venv)"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY") or load_dotenv(
        Path(repo) / ".env"
    ).get("ANTHROPIC_API_KEY")
    if not api_key:
        raise CastingEditorError(
            "svg generation requires ANTHROPIC_API_KEY in the environment or repo .env"
        )
    return anthropic.Anthropic(api_key=api_key)


def _response_text(response: Any) -> str:
    return "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )


def _extract_svg(text: str) -> str:
    match = _SVG_BLOCK.search(text)
    if match is None:
        raise CastingEditorError("svg generation returned no <svg> document")
    return match.group(0)


def generate_svg_shapes(
    root: Path,
    brief: str,
    *,
    max_subpaths: int = 6,
    client: Any | None = None,
) -> dict[str, Any]:
    """Generate raw SVG shapes for a brief and split them into subpaths.

    Returns ``{"svg": <markup>, "subpaths": [{"d", "closed"}, ...]}``. Invalid
    model output gets one corrective retry (the validation errors are fed
    back) before raising CastingEditorError.
    """
    brief = brief.strip()
    if not brief:
        raise CastingEditorError("svg generation requires a design brief")
    max_subpaths = max(1, min(9, max_subpaths))
    api = client or _anthropic_client(root)
    system = _SYSTEM_PROMPT.format(max_subpaths=max_subpaths)
    messages: list[dict[str, Any]] = [{"role": "user", "content": brief}]
    errors: list[str] = []
    for _attempt in range(2):
        response = api.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=system,
            messages=messages,
        )
        text = _response_text(response)
        try:
            svg = _extract_svg(text)
            subpaths = split_svg_subpaths(svg, limit=max_subpaths)
        except CastingEditorError as exc:
            errors = list(exc.problems)
            messages.append({"role": "assistant", "content": text or "(empty)"})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "That SVG failed validation: "
                        + "; ".join(errors)
                        + ". Send a corrected SVG document that meets every "
                        "requirement, and nothing else."
                    ),
                }
            )
            continue
        return {"svg": svg, "subpaths": subpaths}
    raise CastingEditorError(
        *(f"svg generation failed after retry: {problem}" for problem in errors)
    )


def artist_brief(root: Path, artist_id: str) -> str:
    """Design brief for an artist name mark, driven by the artist's identity."""
    path = Path(root) / "content" / "artists" / f"{artist_id}.yaml"
    if not path.is_file():
        raise CastingEditorError(f"artist record does not exist: {artist_id}")
    record = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    artist = record.get("artist") or {}
    name = artist.get("name") or artist_id
    lines = [
        f'Design a wordmark for the recording artist "{name}".',
        "The artist's name must be clearly legible as the centerpiece of the "
        "mark, drawn as stroke lettering.",
    ]
    bio = (artist.get("bio_short") or "").strip()
    if bio:
        lines.append(f"Artist identity, to set the mood of the design: {bio}")
    likeness = artist.get("likeness_notes")
    if isinstance(likeness, str) and likeness.strip():
        lines.append(f"Visual identity notes: {likeness.strip()}")
    return "\n".join(lines)
