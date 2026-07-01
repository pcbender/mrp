"""
Gemini-backed generation for artist blurbs and bios.
"""
from __future__ import annotations

from pathlib import Path

from .config import GOOGLE_API_KEY, MODEL_DEFAULT

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _call_gemini(system: str, user: str, model: str) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_SERVICE_API_KEY not set")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GOOGLE_API_KEY)
    response = client.models.generate_content(
        model=model,
        config=types.GenerateContentConfig(system_instruction=system),
        contents=user,
    )
    return response.text.strip()


def generate_blurb(
    artist_name: str,
    bio_short: str,
    recent_releases: list[dict],
    model: str = MODEL_DEFAULT,
) -> str:
    """
    Generate a promo_blurb for an artist given their bio and recent release reviews.
    recent_releases: list of dicts with keys: title, release_type, release_date, review_text
    """
    system = (_PROMPTS_DIR / "blurb_system.md").read_text().replace("{artist_name}", artist_name)

    release_blocks = []
    for rel in recent_releases:
        block = [
            f"Release: {rel['title']} ({rel['release_type']}, {rel['release_date']})",
        ]
        if rel.get("review_text"):
            block.append(f"Critic review:\n{rel['review_text']}")
        else:
            block.append("(no critic review yet)")
        release_blocks.append("\n".join(block))

    user = "\n\n".join([
        f"Artist: {artist_name}",
        f"Bio:\n{bio_short or '(no bio available)'}",
        "Recent releases:\n" + "\n\n---\n\n".join(release_blocks),
    ])

    return _call_gemini(system, user, model)


def generate_bio(
    artist_name: str,
    artist_type: str,
    lyrics_entries: list[dict],
    model: str = MODEL_DEFAULT,
) -> tuple[str, str]:
    """
    Generate bio_short and bio_long from lyrics.
    Returns (bio_short, bio_long).
    """
    system = (
        (_PROMPTS_DIR / "bio_system.md").read_text()
        .replace("{artist_name}", artist_name)
        .replace("{artist_type}", artist_type or "solo artist")
    )

    lyric_blocks = []
    for entry in lyrics_entries:
        header = f"[{entry['release_title']} — {entry['track_title']}]"
        lyric_blocks.append(f"{header}\n{entry['lyrics_text']}")

    user = "\n\n---\n\n".join(lyric_blocks) if lyric_blocks else "(no lyrics available)"

    raw = _call_gemini(system, user, model)
    return _parse_bio_response(raw)


def _parse_bio_response(raw: str) -> tuple[str, str]:
    """Parse the bio_short / --- / bio_long format."""
    short = ""
    long_ = ""

    if "---" in raw:
        parts = raw.split("---", 1)
        short_block = parts[0].strip()
        long_block = parts[1].strip()

        if short_block.startswith("bio_short:"):
            short = short_block[len("bio_short:"):].strip()
        else:
            short = short_block

        if long_block.startswith("bio_long:"):
            long_ = long_block[len("bio_long:"):].strip()
        else:
            long_ = long_block
    else:
        # Fallback: treat whole response as bio_long, extract first sentence as short
        long_ = raw
        first_sentence_end = raw.find(". ")
        short = raw[: first_sentence_end + 1].strip() if first_sentence_end != -1 else raw[:200]

    return short, long_
