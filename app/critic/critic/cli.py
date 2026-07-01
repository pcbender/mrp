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

from .album.cli import run_album, write_album_report
from .audit import _main as _audit_main
from .eval import approve as eval_approve, calibrate as eval_calibrate
from .pipeline import show as pipeline_show
from .batch import run_batch, write_report
from .catalog import get_artist_name, get_lyrics, get_persona, get_release_meta
from .config import OUT_DIR, critic_model_for, impression_model_for
from .writeback import cmd_writeback as _cmd_writeback
from .dsp import extract_dsp
from .impression import get_impression
from .ingest import ingest
from .synthesize import synthesize
from .tags import extract_tags


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
    print("[2/4] Analysing   DSP…")
    finding.hard_facts = extract_dsp(arr)

    # ── Impression ───────────────────────────────────────────────────────────
    print("[3/4] Impression  Gemini…")
    finding.impression = get_impression(finding.source.proxy,
                                        model=impression_model_for(args.model))

    # ── Tags ─────────────────────────────────────────────────────────────────
    print("      Tags       CLAP…")
    finding.tags = extract_tags(args.audio)

    # ── Synthesize ───────────────────────────────────────────────────────────
    print(f"[4/4] Synthesising  review ({args.model} model, {args.persona} persona)…")
    finding.review = synthesize(
        finding,
        target=args.target,
        target_tier=args.target_tier,
        artist_name=artist_name,
        model=args.model,
        persona=args.persona,
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


def cmd_batch(args: argparse.Namespace) -> None:
    out_dir = Path(args.out) if args.out else OUT_DIR
    findings = run_batch(
        args.manifest,
        model=args.model,
        impression_model=impression_model_for(args.model),
        target=args.target,
        target_tier=args.target_tier,
        out_dir=out_dir,
        skip_impression=args.skip_impression,
        skip_tags=args.skip_tags,
        persona=args.persona,
    )
    print(f"\nProcessed {len(findings)} track(s).")
    write_report(out_dir)


def cmd_report(args: argparse.Namespace) -> None:
    out_dir = Path(args.out) if args.out else OUT_DIR
    write_report(out_dir)


def cmd_album(args: argparse.Namespace) -> None:
    out_dir = Path(args.out) if args.out else OUT_DIR
    record = run_album(
        args.release_slug,
        target=args.target,
        model=args.model,
        out_dir=out_dir,
        persona=args.persona,
    )
    report_path = write_album_report(record, out_dir=out_dir)
    rv = record.review
    print(f"\n{'═' * 60}")
    print(f"  {record.artist} — {args.release_slug}")
    print(f"  Rank {rv.verdict_tier.rank} — {rv.verdict_tier.label}  |  "
          f"sum_vs_parts: {rv.sum_vs_parts}  |  persona: {rv.persona_delivery}")
    print(f"{'═' * 60}")
    print(f"\n{rv.review_text}\n")
    shifts = [t for t in record.track_reviews_in_context if t.context_rank is not None]
    print(f"Context shifts: {len(shifts)} of {len(record.tracklist)}")
    for t in shifts:
        d = "↑" if t.context_rank > t.standalone_rank else "↓"
        print(f"  [{t.position}] {t.track_id.split('--', 1)[-1]}  "
              f"{t.standalone_rank} → {t.context_rank} {d}  {t.context_note}")
    print(f"\nAlbum record  → {out_dir / f'album--{record.album_id}'}.json")
    print(f"Album QA      → {report_path}")


def cmd_approve(args: argparse.Namespace) -> None:
    out_dir = Path(args.out) if args.out else OUT_DIR
    path = eval_approve(
        args.id,
        publish=args.publish,
        all_tracks=args.all_tracks,
        out_dir=out_dir,
    )
    print(f"  Record updated → {path}")


def cmd_writeback(args: argparse.Namespace) -> None:
    _cmd_writeback(args)


def cmd_calibrate(args: argparse.Namespace) -> None:
    out_dir = Path(args.out) if args.out else OUT_DIR
    report_path = eval_calibrate(out_dir=out_dir)
    with open(report_path) as f:
        print(f.read())
    print(f"Report written → {report_path}")


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
        help="dev=Haiku+Gemini-2.0-Flash, default=Sonnet+Gemini-2.5-Pro, hero=Opus+Gemini-3.5-Flash",
    )
    rev.add_argument("--persona", default="default",
                     help="Critic persona (default|pundit|liner, or any file in critic/personas/)")
    rev.add_argument("--out", help=f"Output directory (default: {OUT_DIR})")

    # critic batch …
    bat = sub.add_parser("batch", help="Run pipeline on all tracks in a manifest")
    bat.add_argument("manifest", help="JSON manifest file listing tracks to process")
    bat.add_argument("--target", choices=["blurb", "liner"], default="blurb")
    bat.add_argument("--target-tier", type=int, choices=[2, 3, 4, 5])
    bat.add_argument(
        "--model",
        choices=["dev", "default", "hero"],
        default="dev",
        help="dev=Haiku+Gemini-2.0-Flash, default=Sonnet+Gemini-2.5-Pro, hero=Opus+Gemini-3.5-Flash",
    )
    bat.add_argument("--skip-impression", action="store_true", help="Skip Gemini impression step")
    bat.add_argument("--skip-tags", action="store_true", help="Skip CLAP tags step")
    bat.add_argument("--persona", default="default",
                     help="Critic persona (default|pundit|liner, or any file in critic/personas/)")
    bat.add_argument("--out", help=f"Output directory (default: {OUT_DIR})")

    # critic report …
    rep = sub.add_parser("report", help="Generate QA report from existing out/ findings")
    rep.add_argument("--out", help=f"Output directory (default: {OUT_DIR})")

    # critic show …
    shw = sub.add_parser("show", help="Show pipeline ingredients for a track or album")
    shw.add_argument("id", help="track_id (e.g. pcbender--apa) or release_slug (e.g. tria)")
    shw.add_argument("--save", action="store_true", help="Save to out/pipeline_<id>.md")
    shw.add_argument("--out", help=f"Output directory (default: {OUT_DIR})")

    # critic album …
    alb = sub.add_parser("album", help="Run album pipeline (Pass 2 + 3) on a release")
    alb.add_argument("release_slug", help="Release slug (e.g. tria)")
    alb.add_argument("--target", choices=["album_blurb", "album_long"], default="album_blurb")
    alb.add_argument("--model", choices=["dev", "default", "hero"], default="dev",
                     help="dev=Haiku+Gemini-2.0-Flash, default=Sonnet+Gemini-2.5-Pro, hero=Opus+Gemini-3.5-Flash")
    alb.add_argument("--persona", default="default",
                     help="Critic persona (default|pundit|liner, or any file in critic/personas/)")
    alb.add_argument("--out", help=f"Output directory (default: {OUT_DIR})")

    # critic approve …
    apr = sub.add_parser("approve", help="Approve a track or album review for publishing")
    apr.add_argument("id", help="track_id or album_id (e.g. pcbender--apa or pcbender--tria)")
    apr.add_argument("--publish", action="store_true",
                     help="Mark as publishable (vs. just approved)")
    apr.add_argument("--all-tracks", action="store_true",
                     help="Album only — also approve all contextual track reviews")
    apr.add_argument("--out", help=f"Output directory (default: {OUT_DIR})")

    # critic writeback …
    wb = sub.add_parser("writeback", help="Write critic reviews to site/src/content/reviews/")
    wb_grp = wb.add_mutually_exclusive_group(required=True)
    wb_grp.add_argument("--all", action="store_true", help="Write all records in out/")
    wb_grp.add_argument("--track", metavar="ID", help="Write one track by track_id")
    wb.add_argument("--force", action="store_true", help="Overwrite existing review files")
    wb.add_argument("--out", help=f"Input directory (default: {OUT_DIR})")

    # critic audit …
    aud = sub.add_parser("audit", help="Audit catalog against Masters and generate batch manifest")
    aud.add_argument("--masters-dir", default="/mnt/c/Masters",
                     help="Root directory of audio master files (default: /mnt/c/Masters)")
    aud.add_argument("--manifest", help="Output manifest JSON path (default: manifests/catalog-YYYY-MM-DD.json)")
    aud.add_argument("--report", help="Output audit report path (default: manifests/audit-YYYY-MM-DD.md)")
    aud.add_argument("--force", action="store_true", help="Include already-processed tracks in manifest")
    aud.add_argument("--out", help=f"Critic out/ directory (default: {OUT_DIR})")

    # critic calibrate …
    cal = sub.add_parser("calibrate", help="Check records against calibration spec; write calibration.md")
    cal.add_argument("--out", help=f"Output directory (default: {OUT_DIR})")

    args = parser.parse_args()

    if args.command == "review":
        cmd_review(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "album":
        cmd_album(args)
    elif args.command == "show":
        out_dir = Path(args.out) if args.out else OUT_DIR
        doc = pipeline_show(args.id, save=args.save, out_dir=out_dir)
        if not args.save:
            print(doc)
    elif args.command == "approve":
        cmd_approve(args)
    elif args.command == "writeback":
        cmd_writeback(args)
    elif args.command == "audit":
        import sys
        sys.argv = ["critic audit"]
        argv_parts = ["--masters-dir", args.masters_dir]
        if args.manifest:
            argv_parts += ["--manifest", args.manifest]
        if args.report:
            argv_parts += ["--report", args.report]
        if args.force:
            argv_parts.append("--force")
        if args.out:
            argv_parts += ["--out", args.out]
        sys.argv += argv_parts
        _audit_main()
    elif args.command == "calibrate":
        cmd_calibrate(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
