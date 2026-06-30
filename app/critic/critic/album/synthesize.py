"""
Album synthesis worker (WP-11) — Pass 2 album review.

Consumes an AlbumRecord with features + cohesion already populated.
Calls Claude to write the album-level review, sum_vs_parts, and persona_delivery.
Does NOT rewrite track reviews — that is Pass 3 (recontextualize.py).

Usage:
    python -m critic.album.synthesize <release_slug> [--target album_blurb|album_long]
                                      [--model dev|default|hero] [--out <dir>]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import anthropic

from ..catalog import get_release_tracks, is_release_instrumental
from ..config import ANTHROPIC_API_KEY, CRITIC_MODEL_DEFAULT, CRITIC_MODEL_DEV, CRITIC_MODEL_HERO
from ..utils import scrub_emdash
from ..schema import validate_album_review, warn_issues
from .features import build_features
from .cohesion import build_cohesion
from .record import AlbumRecord, AlbumReview, AlbumVerdictTier

_TIER_LABELS = {2: "soft_floor", 3: "solid", 4: "strong", 5: "essential"}
_MODEL_ALIASES = {"dev": CRITIC_MODEL_DEV, "default": CRITIC_MODEL_DEFAULT, "hero": CRITIC_MODEL_HERO}
_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "album_critic_system.md"
_PERSONAS_DIR = Path(__file__).parent.parent / "personas"


def _load_persona(persona: str, artist_name: str) -> str:
    path = _PERSONAS_DIR / f"{persona}.md"
    if not path.exists():
        path = _PERSONAS_DIR / "default.md"
    return path.read_text().strip().replace("{artist_name}", artist_name or "this artist")


def _load_system_prompt(artist_name: str, persona: str = "default") -> str:
    template = _SYSTEM_PROMPT_PATH.read_text()
    preamble = _load_persona(persona, artist_name)
    return template.replace("{persona_preamble}", preamble)


def _build_user_message(record: AlbumRecord, findings: list[dict], target: str, is_instrumental: bool = False) -> str:
    af = record.album_features
    co = record.cohesion

    mins, secs = divmod(int(af.total_runtime_s), 60)
    runtime_str = f"{mins}m {secs}s"

    # Rank distribution summary
    dist_parts = [f"{label}({rank}): {af.rank_distribution.get(str(rank), 0)}"
                  for rank, label in [(5, "standout"), (4, "highlight"), (3, "dependable"), (2, "soft_floor")]]
    dist_str = "  ".join(p for p in dist_parts if not p.endswith(": 0"))

    # Build slug→title map from catalog so track names are correct (not slugs)
    _tracks = get_release_tracks(record.release_slug) or []
    _title_map = {t["slug"]: t.get("title", t["slug"]) for t in _tracks}

    # Per-track table for the model
    track_lines = []
    for i, (tid, bpm, key, mood, finding) in enumerate(zip(
        record.tracklist,
        af.bpm_curve,
        af.key_progression,
        af.mood_progression,
        findings,
    ), start=1):
        rank = finding["review"]["verdict_tier"]["rank"]
        label = _TIER_LABELS.get(rank, "")
        slug = tid.split("--", 1)[-1]
        track_title = _title_map.get(slug, slug)
        excerpt = finding["review"]["review_text"][:120].rstrip() + "…"
        track_lines.append(
            f"  {i}. {track_title}  |  {bpm} BPM, {key}, {mood}  |  rank {rank} ({label})\n"
            f"     ↳ {excerpt}"
        )

    # Thin-data warning: flag when cohesion metrics couldn't be computed
    thin_warnings: list[str] = []
    if co.palette_consistency == 0.0 and len(record.tracklist) < 2:
        thin_warnings.append("palette consistency unavailable (fewer than 2 tracks)")
    if not is_instrumental and not co.theme_threads:
        thin_warnings.append("no lyrical theme threads detected")

    parts = [
        f"Release: {record.artist} — {record.title}",
        f"Release type: {record.release_type}",
        f"Instrumental: {'yes — no lyrics on any track' if is_instrumental else 'no'}",
        f"Format: {target}",
        *(["", "⚠  DATA NOTES (thin data — avoid asserting arcs for these):", *[f"  - {w}" for w in thin_warnings]] if thin_warnings else []),
        "",
        "=== ARTIST PERSONA ===",
        record.persona or "(none)",
        "",
        "=== TRACKLIST (in sequence) ===",
        *track_lines,
        "",
        "=== ALBUM FEATURES ===",
        f"Total runtime : {runtime_str}",
        f"Rank spread   : {dist_str}",
        f"Peak track    : {record.album_features.peak_track.split('--', 1)[-1]}",
        f"Valley tracks : {[t.split('--', 1)[-1] for t in af.valley_tracks] or 'none'}",
        f"BPM arc       : {' → '.join(str(b) for b in af.bpm_curve)}",
        f"Key arc       : {' → '.join(af.key_progression)}",
        f"Mood arc      : {' → '.join(m for m in af.mood_progression if m)}",
        "",
        "=== COHESION ===",
        f"Palette consistency : {co.palette_consistency:.2f}  ({co.verdict or 'uncalibrated'})",
        f"Theme threads       : {', '.join(co.theme_threads) or 'none detected'}",
        "",
        "---",
        "Return JSON only — no markdown fences, no commentary:",
        '{"review_text": "...", "verdict_tier": {"rank": N, "label": "..."}, '
        '"sum_vs_parts": "greater|equal|lesser", '
        '"persona_delivery": "on_character|expands|off_character", '
        '"anchors_used": ["..."]}',
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


def _enforce_floor(tier: dict) -> dict:
    rank = max(2, min(5, int(tier.get("rank", 2))))
    return {"rank": rank, "label": _TIER_LABELS.get(rank, "soft_floor")}


def album_synthesize(
    record: AlbumRecord,
    findings: list[dict],
    target: str = "album_blurb",
    model: str | None = None,
    persona: str = "default",
) -> AlbumReview:
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")

    selected_model = _MODEL_ALIASES.get(model or "dev", model or CRITIC_MODEL_DEV)
    system = _load_system_prompt(record.artist, persona)
    is_instrumental = is_release_instrumental(record.release_slug)
    user_msg = _build_user_message(record, findings, target, is_instrumental=is_instrumental)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=selected_model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = response.content[0].text
    parsed = _parse_response(raw)
    tier = _enforce_floor(parsed.get("verdict_tier", {}))

    warn_issues(f"album review {record.album_id}", validate_album_review(parsed))

    return AlbumReview(
        target=target,
        review_text=scrub_emdash(parsed.get("review_text", "")),
        verdict_tier=AlbumVerdictTier(rank=tier["rank"], label=tier["label"]),
        sum_vs_parts=parsed.get("sum_vs_parts", ""),
        persona_delivery=parsed.get("persona_delivery", ""),
        anchors_used=parsed.get("anchors_used", []),
        status="pending",
        model=selected_model,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — album synthesis worker")
    parser.add_argument("release_slug", help="Release slug (e.g. tria)")
    parser.add_argument("--target", choices=["album_blurb", "album_long"], default="album_blurb")
    parser.add_argument("--model", choices=["dev", "default", "hero"], default="dev",
                        help="dev=haiku (default), default=sonnet, hero=opus")
    parser.add_argument("--out", help=f"Track records directory")
    args = parser.parse_args()

    from ..config import OUT_DIR
    from ..catalog import get_release_tracks, get_release_meta
    import json as _json
    out_dir = Path(args.out) if args.out else OUT_DIR

    print(f"[1/3] Loading features…")
    record = build_features(args.release_slug, out_dir=out_dir)

    print(f"[2/3] Computing cohesion…")
    meta = get_release_meta(args.release_slug)
    artist_slug = meta["artist_id"]
    tracks = get_release_tracks(args.release_slug)
    findings = [
        _json.loads((out_dir / f"{artist_slug}--{t['slug']}.json").read_text())
        for t in tracks
    ]
    record.cohesion = build_cohesion(args.release_slug, out_dir=out_dir, findings=findings)

    print(f"[3/3] Synthesising album review ({args.model} model)…")
    review = album_synthesize(record, findings, target=args.target, model=args.model)
    record.review = review

    print(f"\n{'─' * 60}")
    print(f"  {record.album_id}")
    print(f"  Rank {review.verdict_tier.rank} — {review.verdict_tier.label}")
    print(f"  Sum vs parts  : {review.sum_vs_parts}")
    print(f"  Persona       : {review.persona_delivery}")
    print(f"{'─' * 60}")
    print(f"\n{review.review_text}\n")
    print(f"  Anchors : {review.anchors_used}")
    print(f"  Status  : {review.status}")


if __name__ == "__main__":
    _main()
