"""
Recontextualize worker (WP-12) — Pass 3 batch contextual reviews.

All standalone reviews plus the Pass 2 album synthesis are sent in a single
API call. The model writes all contextual reviews simultaneously with full
sequence awareness. Writes to track_reviews_in_context on the AlbumRecord.
Never modifies out/<track_id>.json.

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

from ..catalog import get_release_tracks, is_release_instrumental
from ..config import ANTHROPIC_API_KEY, CRITIC_MODEL_DEFAULT, CRITIC_MODEL_DEV, CRITIC_MODEL_HERO
from ..usage import call_claude
from ..schema import validate_context_review, warn_issues
from .record import AlbumRecord, TrackInContext

_MODEL_ALIASES = {"dev": CRITIC_MODEL_DEV, "default": CRITIC_MODEL_DEFAULT, "hero": CRITIC_MODEL_HERO}
_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "track_context_batch_system.md"
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
    is_instrumental: bool = False,
) -> str:
    af = record.album_features
    rv = record.review
    n = len(record.tracklist)

    _tracks = get_release_tracks(record.release_slug) or []
    _title_map = {t["slug"]: t.get("title", t["slug"]) for t in _tracks}

    def _title(tid: str) -> str:
        return _title_map.get(tid.split("--", 1)[-1], tid.split("--", 1)[-1])

    parts = [
        "=== ALBUM ===",
        f"Artist       : {record.artist}",
        f"Instrumental : {'yes — no lyrics on any track' if is_instrumental else 'no'}",
        f"Verdict      : rank {rv.verdict_tier.rank} ({rv.verdict_tier.label})",
        f"Sum vs parts : {rv.sum_vs_parts}",
        f"Strongest    : {_title(af.peak_track)}",
        "",
        f"=== ALL {n} TRACK STANDALONE REVIEWS (in sequence order) ===",
        "",
    ]

    for i, (track_id, finding) in enumerate(zip(record.tracklist, findings), start=1):
        title = _title(track_id)
        rank = finding["review"]["verdict_tier"]["rank"]
        review_text = finding["review"]["review_text"]
        bpm = af.bpm_curve[i - 1] if (i - 1) < len(af.bpm_curve) else "?"
        pos_label = "opener" if i == 1 else ("closer" if i == n else f"track {i} of {n}")
        hints = finding.get("hints") or {}
        hint_str = ", ".join(f"{k}={v}" for k, v in hints.items())
        parts += [
            f"[{i}/{n}] {title}  ({pos_label}, ~{bpm} BPM, standalone rank {rank})",
            f"track_id: {track_id}",
            *([ f"hints: {hint_str}" ] if hint_str else []),
            review_text,
            "",
        ]

    parts += [
        "---",
        f"Return a JSON array of exactly {n} objects, one per track in the same order.",
        "No markdown fences, no commentary before or after the array.",
    ]

    return "\n".join(parts)


def _parse_response(text: str) -> list[dict]:
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON array from model response:\n{text[:500]}")


def recontextualize(
    record: AlbumRecord,
    findings: list[dict],
    model: str | None = None,
    persona: str = "default",
) -> list[TrackInContext]:
    """
    Re-pass all track reviews in album context via a single API call.
    Returns the full track_reviews_in_context list. Does not modify track JSON files.
    """
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")

    selected_model = _MODEL_ALIASES.get(model or "dev", model or CRITIC_MODEL_DEV)
    system = _load_system_prompt(persona, artist_name=record.artist)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    is_instrumental = is_release_instrumental(record.release_slug)
    n = len(record.tracklist)

    user_msg = _build_user_message(record, findings, is_instrumental=is_instrumental)

    print(f"  Sending all {n} tracks in one call…")
    response = call_claude(
        client,
        model=selected_model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )

    parsed_list = _parse_response(response.content[0].text)

    if len(parsed_list) != n:
        raise ValueError(f"Expected {n} items from model, got {len(parsed_list)}")

    results: list[TrackInContext] = []
    for position, (track_id, finding, item) in enumerate(
        zip(record.tracklist, findings, parsed_list), start=1
    ):
        standalone_rank = finding["review"]["verdict_tier"]["rank"]

        raw_cr = item.get("context_rank")
        if raw_cr is not None:
            context_rank = max(2, min(5, int(raw_cr)))
            if context_rank == standalone_rank:
                context_rank = None
                context_note = ""
            else:
                context_note = item.get("context_note", "")
        else:
            context_rank = None
            context_note = ""

        tic_dict = {
            "review_text": item.get("review_text", finding["review"]["review_text"]),
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
            review_text=item.get("review_text", finding["review"]["review_text"]),
            model=selected_model,
        ))

    return results


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — recontextualize worker")
    parser.add_argument("release_slug", help="Release slug (e.g. bent)")
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

    rv = record.review
    print(f"\n{'═' * 60}")
    print(f"  {record.artist} — {args.release_slug}")
    print(f"  Rank {rv.verdict_tier.rank} — {rv.verdict_tier.label}")
    print(f"  Sum vs parts : {rv.sum_vs_parts}  |  Persona : {rv.persona_delivery}")
    print(f"{'═' * 60}\n")
    print(rv.review_text)

    shift_count = sum(1 for t in record.track_reviews_in_context if t.context_rank is not None)
    print(f"\nContext rank shifts: {shift_count} of {len(record.track_reviews_in_context)}")


if __name__ == "__main__":
    _main()
