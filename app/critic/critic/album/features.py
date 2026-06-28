"""
Album features worker (WP-9) — Pass 2 prep.

Loads per-track Pass 1 records and computes album-level features:
runtime, BPM/key/mood curves, rank distribution, peaks and valleys.

Never re-runs song extraction. All data comes from existing out/<track_id>.json files.

Usage:
    python -m critic.album.features <release_slug> [--out <dir>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..catalog import get_artist_name, get_persona, get_release_meta, get_release_tracks
from ..config import OUT_DIR
from .record import AlbumFeatures, AlbumRecord


def _load_track(track_id: str, out_dir: Path) -> dict:
    path = out_dir / f"{track_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Pass 1 record missing: {path}\n"
            f"Run `critic batch` for this track before building the album record."
        )
    return json.loads(path.read_text())


def build_features(release_slug: str, out_dir: Path | None = None) -> AlbumRecord:
    """
    Load Pass 1 records for all tracks in release_slug and compute AlbumFeatures.
    Returns a partially-populated AlbumRecord (cohesion/review/context are empty).
    """
    out_dir = Path(out_dir) if out_dir else OUT_DIR

    meta = get_release_meta(release_slug)
    if not meta:
        raise ValueError(f"Release not found in catalog: {release_slug}")

    artist_slug = meta["artist_id"]
    artist_name = get_artist_name(artist_slug)
    persona = get_persona(artist_slug)
    album_id = f"{artist_slug}--{release_slug}"

    tracks = get_release_tracks(release_slug)
    if not tracks:
        raise ValueError(f"No tracks found in release: {release_slug}")

    track_ids = [f"{artist_slug}--{t['slug']}" for t in tracks]
    record_paths = [str(out_dir / f"{tid}.json") for tid in track_ids]

    # Load all Pass 1 records — fail loudly on any missing
    findings = [_load_track(tid, out_dir) for tid in track_ids]

    # ── Curves (one entry per track, in tracklist order) ──────────────────────
    bpm_curve = [f["hard_facts"]["bpm"] for f in findings]
    key_progression = [
        f"{f['hard_facts']['key']} {f['hard_facts']['mode']}".strip()
        for f in findings
    ]
    mood_progression = [
        (f["tags"]["mood"][0] if f["tags"]["mood"] else "")
        for f in findings
    ]
    total_runtime_s = sum(f["hard_facts"]["duration_s"] for f in findings)

    # ── Rank distribution ──────────────────────────────────────────────────────
    ranks = [f["review"]["verdict_tier"]["rank"] for f in findings]
    rank_distribution: dict[str, int] = {str(r): 0 for r in range(2, 6)}
    for r in ranks:
        rank_distribution[str(r)] = rank_distribution.get(str(r), 0) + 1

    # ── Peak / valley ──────────────────────────────────────────────────────────
    max_rank = max(ranks)
    min_rank = min(ranks)
    peak_track = track_ids[ranks.index(max_rank)]
    valley_tracks = [tid for tid, r in zip(track_ids, ranks) if r == min_rank]
    # Valley = peak if all tracks share the same rank (suppress noise)
    if min_rank == max_rank:
        valley_tracks = []

    album_features = AlbumFeatures(
        total_runtime_s=round(total_runtime_s, 1),
        bpm_curve=bpm_curve,
        key_progression=key_progression,
        mood_progression=mood_progression,
        rank_distribution=rank_distribution,
        peak_track=peak_track,
        valley_tracks=valley_tracks,
    )

    return AlbumRecord(
        album_id=album_id,
        release_slug=release_slug,
        artist=artist_name,
        persona=persona,
        tracklist=track_ids,
        track_records=record_paths,
        album_features=album_features,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — album features worker")
    parser.add_argument("release_slug", help="Release slug (e.g. tria)")
    parser.add_argument("--out", help=f"Track records directory (default: {OUT_DIR})")
    args = parser.parse_args()

    record = build_features(args.release_slug, out_dir=args.out)
    af = record.album_features

    print(f"\nAlbum  : {record.artist} — {args.release_slug}  [{record.album_id}]")
    print(f"Tracks : {len(record.tracklist)}")
    print(f"Runtime: {int(af.total_runtime_s // 60)}m {int(af.total_runtime_s % 60)}s")
    print()
    print(f"{'#':<4} {'Track':<30} {'BPM':>6}  {'Key':<12} {'Mood':<16} {'Rank'}")
    print("─" * 76)
    for i, (tid, bpm, key, mood, rank) in enumerate(zip(
        record.tracklist,
        af.bpm_curve,
        af.key_progression,
        af.mood_progression,
        [json.loads(Path(p).read_text())["review"]["verdict_tier"]["rank"]
         for p in record.track_records],
    ), start=1):
        short = tid.split("--", 1)[-1]
        print(f"{i:<4} {short:<30} {bpm:>6.1f}  {key:<12} {mood:<16} {rank}")
    print()
    print(f"Rank distribution : {af.rank_distribution}")
    print(f"Peak track        : {af.peak_track}")
    print(f"Valley track(s)   : {af.valley_tracks or '(none — all same rank)'}")


if __name__ == "__main__":
    _main()
