"""
critic CLI — end-to-end pipeline.

Usage:
    critic review <audio> --release-slug <slug> --track-slug <slug>
                          [--artist-slug <slug>] [--target blurb|liner]
                          [--target-tier 2-5] [--model dev|default|hero]
                          [--out <dir>]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from .catalog import get_artist_name, get_lyrics, get_persona, get_release_meta
from .config import OUT_DIR
from .dsp import extract_dsp
from .ingest import ingest
from .synthesize import synthesize


def cmd_review(args: argparse.Namespace) -> None:
    out_dir = Path(args.out) if args.out else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Ingest ──────────────────────────────────────────────────────────────
    release_meta = get_release_meta(args.release_slug) if args.release_slug else {}
    artist_slug = args.artist_slug or release_meta.get("artist_id", "")
    track_id = f"{artist_slug}--{args.track_slug}" if artist_slug else args.track_slug

    print(f"[1/3] Ingesting  {args.audio}")
    finding, arr = ingest(args.audio, track_id=track_id)

    # ── Catalog data ─────────────────────────────────────────────────────────
    lyrics = get_lyrics(args.track_slug, release_slug=args.release_slug)
    persona = get_persona(artist_slug) if artist_slug else ""
    artist_name = get_artist_name(artist_slug) if artist_slug else artist_slug
    finding.lyrics = lyrics
    finding.persona = persona

    if not lyrics:
        print("  ⚠  No lyrics found in catalog — review will treat as instrumental.")
    if not persona:
        print("  ⚠  No artist persona found — proceeding without.")

    # ── DSP ──────────────────────────────────────────────────────────────────
    print("[2/3] Analysing  DSP…")
    finding.hard_facts = extract_dsp(arr)

    # ── Synthesize ───────────────────────────────────────────────────────────
    print(f"[3/3] Synthesising  review ({args.model} model)…")
    finding.review = synthesize(
        finding,
        target=args.target,
        target_tier=args.target_tier,
        artist_name=artist_name,
        model=args.model,
    )

    # ── Output ───────────────────────────────────────────────────────────────
    out_path = out_dir / f"{track_id}.json"
    out_path.write_text(finding.to_json())

    review = finding.review
    hf = finding.hard_facts
    print(f"\n{'─' * 60}")
    print(f"  {track_id}")
    print(f"  {hf.bpm} BPM · {hf.key} {hf.mode} · {hf.time_signature} · {hf.lufs} dB LUFS")
    print(f"{'─' * 60}")
    print(f"\n{review.review_text}\n")
    print(f"  Verdict  : rank {review.verdict_tier.rank} — {review.verdict_tier.label}")
    print(f"  Anchors  : {', '.join(review.anchors_used)}")
    print(f"  Status   : {review.status}")
    print(f"\n  Record written → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="critic",
        description="MRP AI music critic pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # critic review …
    rev = sub.add_parser("review", help="Run full pipeline on one track")
    rev.add_argument("audio", help="Path to audio master (WAV, AIFF, FLAC)")
    rev.add_argument("--release-slug", required=True, help="Release slug (matches content/releases/<slug>.yaml)")
    rev.add_argument("--track-slug", required=True, help="Track slug within that release")
    rev.add_argument("--artist-slug", help="Artist slug override (default: from release metadata)")
    rev.add_argument("--target", choices=["blurb", "liner"], default="blurb")
    rev.add_argument("--target-tier", type=int, choices=[2, 3, 4, 5])
    rev.add_argument(
        "--model",
        choices=["dev", "default", "hero"],
        default="dev",
        help="dev=haiku (default), default=sonnet, hero=opus",
    )
    rev.add_argument("--out", help=f"Output directory (default: {OUT_DIR})")

    args = parser.parse_args()

    if args.command == "review":
        cmd_review(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
