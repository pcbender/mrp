"""
Album CLI (WP-13) — end-to-end Pass 2 → Pass 3 orchestrator.

Usage:
    critic album <release_slug> [--target album_blurb|album_long]
                                [--model dev|default|hero] [--out <dir>]

    python -m critic.album.cli <release_slug> [same flags]
"""
from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from ..catalog import get_release_meta, get_release_tracks
from ..config import OUT_DIR
from .cohesion import build_cohesion
from .features import build_features
from .record import AlbumRecord
from .recontextualize import recontextualize
from .synthesize import album_synthesize


def run_album(
    release_slug: str,
    target: str = "album_blurb",
    model: str = "dev",
    out_dir: Path | None = None,
    persona: str = "default",
) -> AlbumRecord:
    """Full Pass 2 → Pass 3 pipeline for one release. Returns populated AlbumRecord."""
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = get_release_meta(release_slug)
    if not meta:
        raise ValueError(f"Release not found: {release_slug}")
    artist_slug = meta["artist_id"]
    tracks = get_release_tracks(release_slug)

    findings = [
        json.loads((out_dir / f"{artist_slug}--{t['slug']}.json").read_text())
        for t in tracks
    ]

    print(f"[1/4] Features…")
    record = build_features(release_slug, out_dir=out_dir)

    print(f"[2/4] Cohesion…")
    record.cohesion = build_cohesion(release_slug, out_dir=out_dir, findings=findings)

    print(f"[3/4] Album synthesis  ({model} model, {persona} persona)…")
    record.review = album_synthesize(record, findings, target=target, model=model, persona=persona)

    print(f"[4/4] Recontextualising tracks…")
    record.track_reviews_in_context = recontextualize(record, findings, model=model, persona=persona)

    # Prefix with "album--" to prevent collision when a title-track slug
    # matches the release slug (e.g. pcbender--free is both album and track).
    out_path = out_dir / f"album--{record.album_id}.json"
    out_path.write_text(record.to_json())
    print(f"\nAlbum record → {out_path}")

    return record


def write_album_report(record: AlbumRecord, out_dir: Path | None = None) -> Path:
    """Write album_qa.md for one album record. Returns the report path."""
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    af = record.album_features
    rv = record.review
    co = record.cohesion

    lines: list[str] = [
        f"# MRP Critic — Album QA: {record.artist} / {record.release_slug}",
        "",
        f"**Album ID:** `{record.album_id}`",
        "",
        "## Verdict",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Rank | {rv.verdict_tier.rank} — {rv.verdict_tier.label} |",
        f"| Sum vs parts | {rv.sum_vs_parts} |",
        f"| Persona delivery | {rv.persona_delivery} |",
        f"| Status | {rv.status} |",
        f"| Runtime | {int(af.total_runtime_s // 60)}m {int(af.total_runtime_s % 60)}s |",
        f"| Palette consistency | {co.palette_consistency:.2f} ({co.verdict}) |",
        f"| Theme threads | {', '.join(co.theme_threads) or 'none'} |",
        "",
        "## Album Review",
        "",
        rv.review_text,
        "",
        f"_Anchors: {', '.join(rv.anchors_used)}_",
        "",
        "---",
        "",
        "## Track Map",
        "",
        "| # | Track | Standalone | Context | Note |",
        "|---|-------|-----------|---------|------|",
    ]

    for t in record.track_reviews_in_context:
        short = t.track_id.split("--", 1)[-1]
        ctx_rank = str(t.context_rank) if t.context_rank is not None else "—"
        if t.context_rank is not None:
            direction = "↑" if t.context_rank > t.standalone_rank else "↓"
            ctx_rank = f"{t.context_rank} {direction}"
        note = textwrap.shorten(t.context_note, width=80, placeholder="…") if t.context_note else ""
        lines.append(f"| {t.position} | `{short}` | {t.standalone_rank} | {ctx_rank} | {note} |")

    lines += ["", "---", "", "## Contextual Track Reviews", ""]

    for t in record.track_reviews_in_context:
        short = t.track_id.split("--", 1)[-1]
        rank_line = f"standalone {t.standalone_rank}"
        if t.context_rank is not None:
            direction = "↑" if t.context_rank > t.standalone_rank else "↓"
            rank_line += f" → context {t.context_rank} {direction}"
        lines += [
            f"### [{t.position}] {short}  _{rank_line}_",
            "",
            t.review_text,
            "",
        ]
        if t.context_note:
            lines += [f"_Context note: {t.context_note}_", ""]

    report_path = out_dir / "album_qa.md"
    report_path.write_text("\n".join(lines))
    return report_path


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — album pipeline (Pass 2 + 3)")
    parser.add_argument("release_slug", help="Release slug (e.g. tria)")
    parser.add_argument("--target", choices=["album_blurb", "album_long"], default="album_blurb")
    parser.add_argument("--model", choices=["dev", "default", "hero"], default="dev",
                        help="dev=haiku (default), default=sonnet, hero=opus")
    parser.add_argument("--out", help="Output directory for records and reports")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else OUT_DIR

    record = run_album(
        args.release_slug,
        target=args.target,
        model=args.model,
        out_dir=out_dir,
    )

    report_path = write_album_report(record, out_dir=out_dir)

    rv = record.review
    af = record.album_features

    print(f"\n{'═' * 60}")
    print(f"  {record.artist} — {record.release_slug}")
    print(f"  Rank {rv.verdict_tier.rank} — {rv.verdict_tier.label}")
    print(f"  Sum vs parts : {rv.sum_vs_parts}  |  Persona : {rv.persona_delivery}")
    print(f"{'═' * 60}")
    print(f"\n{rv.review_text}\n")

    shifts = [t for t in record.track_reviews_in_context if t.context_rank is not None]
    print(f"Context rank shifts: {len(shifts)} of {len(record.tracklist)}")
    for t in shifts:
        d = "↑" if t.context_rank > t.standalone_rank else "↓"
        short = t.track_id.split("--", 1)[-1]
        print(f"  [{t.position}] {short}  {t.standalone_rank} → {t.context_rank} {d}  {t.context_note}")

    print(f"\nAlbum QA report → {report_path}")


if __name__ == "__main__":
    _main()
