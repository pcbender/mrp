"""
Impression worker: sends the Opus proxy to Gemini and captures a
texture/feel/production description.

DSP owns BPM, key, time signature — this worker explicitly avoids them.
Fails loudly (ImpressionError) when Gemini is unavailable for any reason: a
review written without the listening pass is silently thinner, so opting out
has to be explicit (``critic batch --skip-impression``), never a fallthrough.

Usage:
    python -m critic.impression <audio_or_proxy_path> [--model gemini-pro-latest]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import GEMINI_API_KEY, IMPRESSION_MODEL, gemini_client
from .record import Impression
from .usage import record_gemini
from .utils import scrub_emdash


class ImpressionError(RuntimeError):
    """Gemini could not produce an impression; the critic must not proceed."""


def _describe(exc: BaseException) -> str:
    """One readable line for a google-genai error (str() dumps the whole JSON)."""
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    message = " ".join(str(message).split())[:300]
    return f"{code} {message}" if code else message

_PROMPT = """\
Listen to this audio and describe what you hear in 3-5 sentences as a music \
professional noting first impressions.

Cover:
- Texture and emotional atmosphere
- Energy level and feel
- Production quality: space, density, how elements sit together
- Any distinctive moment, transition, or quality that defines the track

Do NOT mention BPM, tempo, key, mode, or time signature — those are \
documented separately. Be specific to what you actually hear. \
Do NOT use em dashes (—); use commas, colons, or rephrase instead.
"""


def get_impression(proxy_path: str | Path, model: str | None = None) -> Impression:
    """Send proxy.opus to Gemini. Raises ImpressionError on any failure."""
    if not GEMINI_API_KEY:
        raise ImpressionError("GOOGLE_GEMINI_API_KEY not set (environment or .env)")

    try:
        from google.genai import types
    except ImportError as exc:
        raise ImpressionError("google-genai package is not installed") from exc

    selected = model or IMPRESSION_MODEL
    audio_bytes = Path(proxy_path).read_bytes()

    try:
        client = gemini_client()
        response = client.models.generate_content(
            model=selected,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"),
                types.Part.from_text(text=_PROMPT),
            ],
        )
    except Exception as exc:
        raise ImpressionError(f"Gemini impression failed ({selected}): {_describe(exc)}") from exc

    record_gemini(response)
    text = scrub_emdash((response.text or "").strip())
    if not text:
        raise ImpressionError(f"Gemini impression came back empty ({selected})")
    # Record the concrete model that answered: `selected` may be a `-latest`
    # alias, which would say nothing useful about this record six months on.
    return Impression(text=text, model=response.model_version or selected)


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — Gemini impression worker")
    parser.add_argument("path", help="Audio master or existing .opus proxy path")
    parser.add_argument("--track-id")
    parser.add_argument("--model", default=IMPRESSION_MODEL)
    args = parser.parse_args()

    proxy_path = args.path
    if not args.path.endswith(".opus"):
        from .ingest import ingest
        print(f"Ingesting {args.path}…")
        finding, _ = ingest(args.path, track_id=args.track_id)
        proxy_path = finding.source.proxy

    print(f"Sending proxy to {args.model}…")
    impression = get_impression(proxy_path, model=args.model)
    print(f"\nModel : {impression.model}")
    print(f"\nImpression:\n{impression.text}")


if __name__ == "__main__":
    _main()
