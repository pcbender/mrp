"""
Synthesis worker: calls Claude with lyrics + persona + hard_facts to
produce review_text, verdict_tier, and anchors_used.

Usage:
    python -m critic.synthesize <finding_json> [--target blurb|liner]
                                [--target-tier 2-5] [--model dev|default|hero]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
from pathlib import Path

import anthropic

from .config import ANTHROPIC_API_KEY, CRITIC_MODEL_DEFAULT, CRITIC_MODEL_DEV, CRITIC_MODEL_HERO
from .record import Review, TrackFinding, VerdictTier

_TIER_LABELS = {2: "soft_floor", 3: "dependable", 4: "highlight", 5: "standout"}
_MODEL_ALIASES = {"dev": CRITIC_MODEL_DEV, "default": CRITIC_MODEL_DEFAULT, "hero": CRITIC_MODEL_HERO}
_SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompts" / "critic_system.md"


def _load_system_prompt(artist_name: str) -> str:
    template = _SYSTEM_PROMPT_PATH.read_text()
    return template.replace("{artist_name}", artist_name or "this artist")


def _build_user_message(
    finding: TrackFinding,
    target: str,
    target_tier: int | None,
    artist_name: str,
) -> str:
    hf = finding.hard_facts
    mins, secs = divmod(int(hf.duration_s), 60)
    duration_str = f"{mins}:{secs:02d}"

    conf_notes: list[str] = []
    if hf.confidence.key < 0.65:
        conf_notes.append(f"key uncertain ({hf.confidence.key:.2f})")
    if hf.confidence.bpm < 0.65:
        conf_notes.append(f"tempo uncertain ({hf.confidence.bpm:.2f})")
    conf_str = "; ".join(conf_notes) if conf_notes else "high confidence"

    sections_str = ", ".join(
        f"{s.label} {s.start:.0f}s–{s.end:.0f}s" for s in hf.sections
    )

    tier_line = ""
    if target_tier is not None:
        label = _TIER_LABELS.get(target_tier, "dependable")
        tier_line = f"TARGET TIER: land on rank {target_tier} ({label}).\n"

    parts = [
        f"Track: {finding.track_id}",
        f"Artist: {artist_name or '(unknown)'}",
        f"Format: {target}",
        tier_line,
        "=== ARTIST PERSONA ===",
        finding.persona or "(none)",
        "",
        "=== LYRICS ===",
        finding.lyrics or "(instrumental — no lyrics)",
        "",
        "=== HARD FACTS ===",
        f"BPM: {hf.bpm}  |  Key: {hf.key} {hf.mode}  |  Time: {hf.time_signature}",
        f"Duration: {duration_str}  |  LUFS: {hf.lufs} dB  |  Detection: {conf_str}",
        f"Structure ({len(hf.sections)} sections): {sections_str}",
    ]

    if finding.tags.genre or finding.tags.mood or finding.tags.instruments:
        parts += [
            "",
            "=== TAGS ===",
            f"Genre: {', '.join(finding.tags.genre) or 'n/a'}",
            f"Mood: {', '.join(finding.tags.mood) or 'n/a'}",
            f"Instruments: {', '.join(finding.tags.instruments) or 'n/a'}",
        ]

    if finding.impression.text:
        parts += ["", "=== AUDIO IMPRESSION ===", finding.impression.text]

    parts += [
        "",
        "---",
        "Return JSON only — no markdown fences, no commentary:",
        '{"review_text": "...", "verdict_tier": {"rank": N, "label": "..."}, "anchors_used": ["..."]}',
    ]

    return "\n".join(parts)


def _parse_response(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences if model added them despite instructions
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Last resort: find outermost braces
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


def synthesize(
    finding: TrackFinding,
    target: str = "blurb",
    target_tier: int | None = None,
    artist_name: str = "",
    model: str | None = None,
) -> Review:
    if not ANTHROPIC_API_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")

    selected_model = _MODEL_ALIASES.get(model or "dev", model or CRITIC_MODEL_DEV)
    system = _load_system_prompt(artist_name)
    user_msg = _build_user_message(finding, target, target_tier, artist_name)

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

    return Review(
        target=target,
        review_text=parsed.get("review_text", ""),
        status="pending",
        verdict_tier=VerdictTier(rank=tier["rank"], label=tier["label"]),
        anchors_used=parsed.get("anchors_used", []),
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — synthesis worker")
    parser.add_argument("finding", help="Path to finding JSON file")
    parser.add_argument("--target", choices=["blurb", "liner"], default="blurb")
    parser.add_argument("--target-tier", type=int, choices=[2, 3, 4, 5])
    parser.add_argument("--artist", default="", help="Artist name for system prompt")
    parser.add_argument(
        "--model",
        choices=["dev", "default", "hero"],
        default="dev",
        help="dev=haiku, default=sonnet, hero=opus",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.finding).read_text())
    finding = TrackFinding(**{
        k: v for k, v in data.items()
        if k in {f.name for f in dataclasses.fields(TrackFinding)}
    })
    # Re-hydrate nested dataclasses from dicts
    from .record import Confidence, HardFacts, Impression, Review, Section, SourceRecord, Tags, VerdictTier
    if isinstance(finding.source, dict):
        finding.source = SourceRecord(**finding.source)
    if isinstance(finding.hard_facts, dict):
        hf = finding.hard_facts
        hf["sections"] = [Section(**s) for s in hf.get("sections", [])]
        hf["confidence"] = Confidence(**hf.get("confidence", {}))
        finding.hard_facts = HardFacts(**hf)
    if isinstance(finding.tags, dict):
        finding.tags = Tags(**finding.tags)
    if isinstance(finding.impression, dict):
        finding.impression = Impression(**finding.impression)
    if isinstance(finding.review, dict):
        rv = finding.review
        rv["verdict_tier"] = VerdictTier(**rv.get("verdict_tier", {}))
        finding.review = Review(**rv)

    print(f"Synthesizing review for: {finding.track_id}  [{args.target}]")
    review = synthesize(
        finding,
        target=args.target,
        target_tier=args.target_tier,
        artist_name=args.artist,
        model=args.model,
    )
    finding.review = review

    print(f"\nVerdict : rank {review.verdict_tier.rank} — {review.verdict_tier.label}")
    print(f"Anchors : {review.anchors_used}")
    print(f"\nReview:\n{review.review_text}")
    print(f"\nFull record:\n{finding.to_json()}")


if __name__ == "__main__":
    _main()
