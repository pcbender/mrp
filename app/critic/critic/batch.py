"""
Batch runner and QA report generator.

critic batch <manifest.json>   — run full pipeline on every entry in the manifest
critic report                   — generate sorted QA report from existing out/*.json

Manifest format (JSON array):
  [
    {
      "audio":        "/mnt/c/Masters/Joni.wav",
      "release_slug": "attunement",
      "track_slug":   "joni",
      "artist_slug":  "pcbender",
      "target":       "blurb"
    },
    ...
  ]

Report is sorted by verdict rank ascending (weakest first) so QA attention
goes to the bottom of the ladder.
"""
from __future__ import annotations

import csv
import json
import textwrap
import traceback
from pathlib import Path

from .catalog import get_artist_name, get_lyrics, get_persona, get_release_meta
from .config import OUT_DIR
from .dsp import extract_dsp
from .impression import get_impression
from .ingest import ingest
from .record import TrackFinding
from .synthesize import synthesize
from .tags import extract_tags


def _hydrate(data: dict) -> TrackFinding:
    from .record import Confidence, HardFacts, Impression, Review, Section, SourceRecord, Tags, VerdictTier

    f = TrackFinding(**{k: v for k, v in data.items()
                        if k in {"track_id", "lyrics", "persona", "source",
                                 "hard_facts", "tags", "impression", "review"}})
    if isinstance(f.source, dict):
        f.source = SourceRecord(**f.source)
    if isinstance(f.hard_facts, dict):
        hf = dict(f.hard_facts)
        hf["sections"] = [Section(**s) for s in hf.get("sections", [])]
        hf["confidence"] = Confidence(**hf.get("confidence", {}))
        f.hard_facts = HardFacts(**hf)
    if isinstance(f.tags, dict):
        f.tags = Tags(**f.tags)
    if isinstance(f.impression, dict):
        f.impression = Impression(**f.impression)
    if isinstance(f.review, dict):
        rv = dict(f.review)
        rv["verdict_tier"] = VerdictTier(**rv.get("verdict_tier", {}))
        from .record import Review as R
        f.review = R(**rv)
    return f


def run_batch(
    manifest_path: str | Path,
    model: str = "dev",
    target: str = "blurb",
    target_tier: int | None = None,
    out_dir: Path | None = None,
    skip_impression: bool = False,
    skip_tags: bool = False,
) -> list[TrackFinding]:
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = json.loads(Path(manifest_path).read_text())
    results: list[TrackFinding] = []

    for i, entry in enumerate(entries, 1):
        audio = entry["audio"]
        release_slug = entry.get("release_slug", "")
        track_slug = entry.get("track_slug", "")
        artist_slug = entry.get("artist_slug", "")
        row_target = entry.get("target", target)

        release_meta = get_release_meta(release_slug) if release_slug else {}
        if not artist_slug:
            artist_slug = release_meta.get("artist_id", "")
        track_id = f"{artist_slug}--{track_slug}" if artist_slug else track_slug

        print(f"\n[{i}/{len(entries)}] {track_id}  ({audio})")

        try:
            print("  ingest…")
            finding, arr = ingest(audio, track_id=track_id)
            finding.lyrics = get_lyrics(track_slug, release_slug=release_slug)
            finding.persona = get_persona(artist_slug) if artist_slug else ""

            print("  DSP…")
            finding.hard_facts = extract_dsp(arr)

            if not skip_impression:
                print("  impression…")
                finding.impression = get_impression(finding.source.proxy)

            if not skip_tags:
                print("  tags…")
                finding.tags = extract_tags(audio)

            artist_name = get_artist_name(artist_slug) if artist_slug else artist_slug
            print("  synthesize…")
            finding.review = synthesize(
                finding,
                target=row_target,
                target_tier=target_tier,
                artist_name=artist_name,
                model=model,
            )

            out_path = out_dir / f"{track_id}.json"
            out_path.write_text(finding.to_json())
            rank = finding.review.verdict_tier.rank
            label = finding.review.verdict_tier.label
            print(f"  → rank {rank} ({label})  saved: {out_path.name}")
            results.append(finding)

        except Exception:
            print(f"  ✗ failed:")
            traceback.print_exc()

    return results


def write_report(out_dir: Path | None = None) -> tuple[Path, Path]:
    """
    Read all *.json findings in out_dir and write qa_report.md + qa_report.csv.
    Returns (md_path, csv_path).
    """
    out_dir = out_dir or OUT_DIR
    findings: list[TrackFinding] = []

    for p in sorted(out_dir.glob("*.json")):
        if p.name.startswith("qa_report"):
            continue
        try:
            findings.append(_hydrate(json.loads(p.read_text())))
        except Exception as exc:
            print(f"  ⚠  skipping {p.name}: {exc}")

    # Sort ascending by rank (weakest first)
    findings.sort(key=lambda f: (
        f.review.verdict_tier.rank if f.review else 99,
        f.track_id,
    ))

    md_path = out_dir / "qa_report.md"
    csv_path = out_dir / "qa_report.csv"

    _write_md(findings, md_path)
    _write_csv(findings, csv_path)

    print(f"\nQA report: {md_path}")
    print(f"QA CSV   : {csv_path}")
    return md_path, csv_path


def _write_md(findings: list[TrackFinding], path: Path) -> None:
    lines = [
        "# MRP Critic — QA Report",
        "",
        "_Sorted weakest-first (rank 2 → 5). Review and approve each entry._",
        "",
        f"| Rank | Label | Track | Review (truncated) | Status |",
        f"|------|-------|-------|--------------------|--------|",
    ]
    for f in findings:
        if not f.review:
            continue
        rv = f.review
        snippet = textwrap.shorten(rv.review_text, width=120, placeholder="…")
        lines.append(
            f"| {rv.verdict_tier.rank} | {rv.verdict_tier.label} "
            f"| `{f.track_id}` | {snippet} | {rv.status} |"
        )

    lines += ["", "---", ""]
    for f in findings:
        if not f.review:
            continue
        rv = f.review
        hf = f.hard_facts
        lines += [
            f"## rank {rv.verdict_tier.rank} — {rv.verdict_tier.label} · `{f.track_id}`",
            "",
            f"**{hf.bpm} BPM · {hf.key} {hf.mode} · {hf.lufs} dB LUFS**",
            "",
            rv.review_text,
            "",
            f"_Anchors: {', '.join(rv.anchors_used)}_",
            f"_Status: {rv.status}_",
            "",
        ]

    path.write_text("\n".join(lines))


def _write_csv(findings: list[TrackFinding], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "rank", "label", "track_id",
            "bpm", "key", "mode", "lufs",
            "review_text", "anchors", "status",
        ])
        for finding in findings:
            if not finding.review:
                continue
            rv = finding.review
            hf = finding.hard_facts
            writer.writerow([
                rv.verdict_tier.rank,
                rv.verdict_tier.label,
                finding.track_id,
                hf.bpm,
                hf.key,
                hf.mode,
                hf.lufs,
                rv.review_text,
                "; ".join(rv.anchors_used),
                rv.status,
            ])
