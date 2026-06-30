"""
Recontextualize worker (WP-12) — Pass 3 per-track contextual reviews.

For each track, re-passes the standalone review knowing sequence position,
neighbors, and the Pass 2 album verdict. Writes to track_reviews_in_context
on the AlbumRecord. Never modifies out/<track_id>.json.

Usage:
    python -m critic.album.recontextualize <release_slug> [--model dev|default|hero]
                                           [--out <dir>]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import anthropic

from ..catalog import is_release_instrumental
from ..config import ANTHROPIC_API_KEY, CRITIC_MODEL_DEFAULT, CRITIC_MODEL_DEV, CRITIC_MODEL_HERO
from ..schema import validate_context_review, warn_issues
from .record import AlbumRecord, AlbumReview, TrackInContext

_TIER_LABELS = {2: "soft_floor", 3: "solid", 4: "strong", 5: "essential"}
_MODEL_ALIASES = {"dev": CRITIC_MODEL_DEV, "default": CRITIC_MODEL_DEFAULT, "hero": CRITIC_MODEL_HERO}
_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "track_context_system.md"
_PERSONAS_DIR = Path(__file__).parent.parent / "personas"


def _load_persona(persona: str, artist_name: str = "") -> str:
    path = _PERSONAS_DIR / f"{persona}.md"
    if not path.exists():
        path = _PERSONAS_DIR / "default.md"
    return path.read_text().strip().replace("{artist_name}", artist_name or "this artist")


def _load_system_prompt(persona: str = "default", artist_name: str = "") -> str:
    template = _SYSTEM_PROMPT_PATH.read_text()
    preamble = _load_persona(persona, artist_name)
    return template.replace("{persona_preamble}", preamble)


def _build_user_message(
    record: AlbumRecord,
    findings: list[dict],
    position: int,       # 1-based
    is_instrumental: bool = False,
) -> str:
    idx = position - 1
    track_id = record.tracklist[idx]
    finding = findings[idx]
    af = record.album_features
    rv = record.review

    short_name = track_id.split("--", 1)[-1]
    n = len(record.tracklist)

    prev_name = record.tracklist[idx - 1].split("--", 1)[-1] if idx > 0 else None
    next_name = record.tracklist[idx + 1].split("--", 1)[-1] if idx < n - 1 else None

    standalone_rank = finding["review"]["verdict_tier"]["rank"]
    standalone_text = finding["review"]["review_text"]

    # Arc summary: mood and tempo trajectory across all tracks
    arc_parts = []
    for i, (tid, bpm, mood) in enumerate(zip(
        record.tracklist, af.bpm_curve, af.mood_progression
    ), start=1):
        marker = f"→ [{i}]" if i == position else f"  [{i}]"
        arc_parts.append(f"{marker} {tid.split('--', 1)[-1]}  ({bpm} BPM, {mood})")

    parts = [
        f"Track   : {short_name}  (position {position} of {n})",
        f"Previous: {prev_name or '(opener)'}",
        f"Next    : {next_name or '(closer — this is the last track)'}",
        "",
        "=== ALBUM CONTEXT ===",
        f"Instrumental album: {'yes' if is_instrumental else 'no'}",
        f"Album verdict    : {rv.verdict_tier.label} (rank {rv.verdict_tier.rank})",
        f"Sum vs parts     : {rv.sum_vs_parts}",
        f"Strongest track  : {af.peak_track.split('--', 1)[-1]}",
        f"Rank spread      : {af.rank_distribution}",
        "",
        "Arc (→ marks this track):",
        *arc_parts,
        "",
        "=== STANDALONE REVIEW ===",
        f"Standalone rank  : {standalone_rank}",
        standalone_text,
        "",
        "---",
        "Return JSON only — no markdown fences:",
        '{"context_rank": N or null, "context_note": "...", "review_text": "..."}',
    ]

    return "\n".join(parts)


def _parse_response(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from model response:\n{text}")


def recontextualize(
    record: AlbumRecord,
    findings: list[dict],
    model: str | None = None,
    persona: str = "default",
) -> list[TrackInContext]:
    """
    Re-pass each track review in album context. Returns the full
    track_reviews_in_context list. Does not touch any track JSON files.
    """
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")

    selected_model = _MODEL_ALIASES.get(model or "dev", model or CRITIC_MODEL_DEV)
    system = _load_system_prompt(persona, artist_name=record.artist)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    is_instrumental = is_release_instrumental(record.release_slug)

    results: list[TrackInContext] = []

    for position, (track_id, finding) in enumerate(
        zip(record.tracklist, findings), start=1
    ):
        short = track_id.split("--", 1)[-1]
        print(f"  [{position}/{len(record.tracklist)}] {short}…")

        standalone_rank = finding["review"]["verdict_tier"]["rank"]
        user_msg = _build_user_message(record, findings, position, is_instrumental=is_instrumental)

        response = client.messages.create(
            model=selected_model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )

        parsed = _parse_response(response.content[0].text)

        # Validate context_rank: must differ from standalone or be null
        raw_cr = parsed.get("context_rank")
        if raw_cr is not None:
            context_rank = max(2, min(5, int(raw_cr)))
            if context_rank == standalone_rank:
                # Model echoed standalone — treat as null
                context_rank = None
                context_note = ""
            else:
                context_note = parsed.get("context_note", "")
        else:
            context_rank = None
            context_note = ""

        tic_dict = {
            "review_text": parsed.get("review_text", finding["review"]["review_text"]),
            "standalone_rank": standalone_rank,
            "context_rank": context_rank,
            "context_note": context_note,
        }
        warn_issues(f"context review {track_id}", validate_context_review(tic_dict))

        results.append(TrackInContext(
            track_id=track_id,
            position=position,
            standalone_rank=standalone_rank,
            context_rank=context_rank,
            context_note=context_note,
            review_text=parsed.get("review_text", finding["review"]["review_text"]),
            model=selected_model,
        ))

    return results


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — recontextualize worker")
    parser.add_argument("release_slug", help="Release slug (e.g. tria)")
    parser.add_argument("--model", choices=["dev", "default", "hero"], default="dev")
    parser.add_argument("--out", help="Track records directory")
    args = parser.parse_args()

    from ..config import OUT_DIR
    from ..catalog import get_release_tracks, get_release_meta
    from .features import build_features
    from .cohesion import build_cohesion
    from .synthesize import album_synthesize
    import json as _json

    out_dir = Path(args.out) if args.out else OUT_DIR

    print("[1/4] Loading features…")
    record = build_features(args.release_slug, out_dir=out_dir)

    meta = get_release_meta(args.release_slug)
    artist_slug = meta["artist_id"]
    tracks = get_release_tracks(args.release_slug)
    findings = [
        _json.loads((out_dir / f"{artist_slug}--{t['slug']}.json").read_text())
        for t in tracks
    ]

    print("[2/4] Computing cohesion…")
    record.cohesion = build_cohesion(args.release_slug, out_dir=out_dir, findings=findings)

    print("[3/4] Album synthesis…")
    record.review = album_synthesize(record, findings, model=args.model)

    print("[4/4] Recontextualizing tracks…")
    record.track_reviews_in_context = recontextualize(record, findings, model=args.model)

    # Album summary header
    rv = record.review
    print(f"\n{'═' * 60}")
    print(f"  ALBUM: {record.artist} — {args.release_slug}")
    print(f"  Rank {rv.verdict_tier.rank} — {rv.verdict_tier.label}  |  "
          f"sum_vs_parts: {rv.sum_vs_parts}  |  persona: {rv.persona_delivery}")
    print(f"{'═' * 60}")
    print(f"\n{rv.review_text}\n")

    # All tracks: standalone vs contextual side by side
    for t in record.track_reviews_in_context:
        idx = t.position - 1
        standalone_text = findings[idx]["review"]["review_text"]
        shift_str = (
            f"  context_rank → {t.context_rank} {'↑' if t.context_rank > t.standalone_rank else '↓'}  {t.context_note}"
            if t.context_rank is not None
            else "  context_rank → null"
        )
        short = t.track_id.split("--", 1)[-1]
        print(f"{'─' * 60}")
        print(f"  [{t.position}] {short}  (standalone rank {t.standalone_rank}){shift_str}")
        print(f"{'─' * 60}")
        print(f"STANDALONE:\n{standalone_text}")
        print(f"\nCONTEXTUAL:\n{t.review_text}\n")


if __name__ == "__main__":
    _main()
