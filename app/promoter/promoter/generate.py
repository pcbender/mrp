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
        url = f"/releases/{rel['slug']}/"
        block = [
            f"Release: {rel['title']} ({rel['release_type']}, {rel['release_date']}) — URL: {url}",
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


KIT_COPY_KEYS = [
    "instagram", "facebook", "bluesky", "x", "threads",
    "youtube_description", "playlist_pitch", "artist_pick",
]


def generate_kit(
    artist: dict,
    release: dict,
    review_text: str,
    model: str = MODEL_DEFAULT,
) -> dict:
    """
    Generate per-platform promo copy for one release.
    Returns a dict with KIT_COPY_KEYS plus "hashtags" (list of strings).
    """
    artist_name = artist.get("name", "")
    system = (_PROMPTS_DIR / "kit_system.md").read_text().replace("{artist_name}", artist_name)

    tracks = release.get("tracks") or ([release["song"]] if release.get("song") else [])
    track_titles = ", ".join(t.get("title", "") for t in tracks if t.get("title"))

    voice_parts = [f"Artist: {artist_name}"]
    if artist.get("bio_short"):
        voice_parts.append(f"Bio:\n{artist['bio_short']}")
    if artist.get("promo_blurb"):
        voice_parts.append(f"Current promo blurb (voice reference):\n{artist['promo_blurb']}")

    release_parts = [
        f"Release: {release.get('title', '')} ({release.get('release_type', '')},"
        f" released {release.get('release_date') or 'unreleased'})",
        f"Tracks: {track_titles}",
    ]
    if release.get("summary"):
        release_parts.append(f"Summary: {release['summary']}")
    if release.get("description"):
        release_parts.append(f"Description:\n{release['description']}")
    if review_text:
        release_parts.append(f"Critic review:\n{review_text}")
    else:
        release_parts.append("(no critic review yet)")

    user = "\n\n".join(voice_parts + release_parts)
    raw = _call_gemini(system, user, model)
    kit = _parse_kit_response(raw)

    missing = [k for k in KIT_COPY_KEYS if not str(kit.get(k) or "").strip()]
    if missing:
        raise ValueError(f"Kit generation incomplete — missing: {', '.join(missing)}")
    tags = kit.get("hashtags")
    if not isinstance(tags, list):
        tags = [t for t in str(tags or "").split() if t.startswith("#")]
    kit["hashtags"] = [str(t).strip() for t in tags if str(t).strip()]
    return kit


def _parse_kit_response(raw: str) -> dict:
    """Parse the JSON kit, tolerating markdown fences the model may add."""
    import json as _json
    import re as _re

    try:
        return _json.loads(raw)
    except _json.JSONDecodeError:
        pass
    match = _re.search(r"```(?:json)?\s*(.*?)\s*```", raw, _re.DOTALL)
    if match:
        try:
            return _json.loads(match.group(1))
        except _json.JSONDecodeError:
            pass
    match = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if match:
        try:
            return _json.loads(match.group(0))
        except _json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON kit from model response:\n{raw[:400]}")


def generate_keywords(
    artist: dict,
    existing: list[str],
    seats=None,
) -> dict:
    """
    Propose YouTube channel keywords for an artist.

    Candidates come from the artist's own catalog (see `evidence.py`), not from
    a model — channel keywords describe the artist, and a model asked to invent
    them will happily claim a genre one track suggested. Three vendors then vote
    on the gated candidates, and a keyword needs a quorum to survive.

    Returns the full run: candidates, gate results, ballots, tally, and the
    keywords that reached consensus. Nothing is written here.
    """
    from . import evidence as ev
    from .config import TRIUMVIRATE
    from .triumvirate import collect_ballots, consensus

    artist_id = artist.get("id", "")
    gathered = ev.gather(artist_id)
    total = gathered["total_releases"]
    passed, rejected = ev.gated(gathered["candidates"], total)

    lines = [f"{c.term} — {c.evidence(total)}" for c in passed]
    lines += [f"{t} — tempo, from measured BPM across the catalog"
              for t in ev.tempo_terms(gathered["bpm"])]
    lines += [f"{n} — artist name variant" for n in ev.name_variants(artist.get("name", ""))]
    terms = [line.split(" — ", 1)[0] for line in lines]

    ballots, errors = collect_ballots(artist, lines, seats or TRIUMVIRATE)
    if len(ballots) < 2:
        raise RuntimeError(
            "Need at least two ballots to form a consensus. "
            + "; ".join(f"{v}: {e}" for v, e in errors.items())
        )

    kept, tally = consensus(terms, ballots)
    kept = [k for k in kept if k.casefold() not in {e.casefold() for e in existing}]

    return {
        "total_releases": total,
        "matched": gathered["matched"],
        "passed": passed,
        "rejected": rejected,
        "terms": terms,
        "ballots": ballots,
        "errors": errors,
        "tally": tally,
        "keywords": kept,
    }


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
