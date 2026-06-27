"""
Impression worker: sends the Opus proxy to Gemini and captures a
texture/feel/production description.

DSP owns BPM, key, time signature — this worker explicitly avoids them.
Degrades gracefully (returns empty Impression) if GOOGLE_API_KEY is absent
or the google-genai package is unavailable.

Usage:
    python -m critic.impression <audio_or_proxy_path> [--model gemini-2.5-pro]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import GOOGLE_API_KEY, IMPRESSION_MODEL
from .record import Impression

_PROMPT = """\
Listen to this audio and describe what you hear in 3-5 sentences as a music \
professional noting first impressions.

Cover:
- Texture and emotional atmosphere
- Energy level and feel
- Production quality: space, density, how elements sit together
- Any distinctive moment, transition, or quality that defines the track

Do NOT mention BPM, tempo, key, mode, or time signature — those are \
documented separately. Be specific to what you actually hear.
"""


def get_impression(proxy_path: str | Path, model: str | None = None) -> Impression:
    """
    Send proxy.opus to Gemini. Returns empty Impression on any failure so the
    rest of the pipeline continues unaffected.
    """
    if not GOOGLE_API_KEY:
        return Impression(text="", model="")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return Impression(text="", model="")

    selected = model or IMPRESSION_MODEL
    audio_bytes = Path(proxy_path).read_bytes()

    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        response = client.models.generate_content(
            model=selected,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"),
                types.Part.from_text(text=_PROMPT),
            ],
        )
        return Impression(text=response.text.strip(), model=selected)
    except Exception as exc:
        print(f"  ⚠  Gemini impression failed: {exc}")
        return Impression(text="", model="")


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

    if not GOOGLE_API_KEY:
        print("GOOGLE_SERVICE_API_KEY not set — skipping.")
        return

    print(f"Sending proxy to {args.model}…")
    impression = get_impression(proxy_path, model=args.model)

    if not impression.text:
        print("No impression returned.")
    else:
        print(f"\nModel : {impression.model}")
        print(f"\nImpression:\n{impression.text}")


if __name__ == "__main__":
    _main()
