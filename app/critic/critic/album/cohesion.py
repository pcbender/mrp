"""
Cohesion worker (WP-10) — cross-track palette + lyrical theme pass.

palette_consistency: centroid cosine similarity over binary tag vectors
(genre ⊕ mood ⊕ instrument). Falls back to this because Pass 1 stores
only top-k labels, not raw probability scores. Flag: method="discrete_tags".
When Pass 1 stores full score vectors, swap the vector builder and drop the flag.

theme_threads: words recurring across >= min_tracks tracks' lyrics.

Thresholds for cohesion verdict are placeholders — calibrate in WP-17.

Usage:
    python -m critic.album.cohesion <release_slug> [--out <dir>]
"""
from __future__ import annotations

import argparse
import math
import re
from collections import Counter
from pathlib import Path

from ..catalog import get_release_meta, get_release_tracks
from ..config import OUT_DIR
from ..tags import _GENRES, _INSTRUMENTS, _MOODS
from .features import build_features
from .record import CohesionResult

# Full label vocabulary: 14 + 13 + 12 = 39 dimensions
_ALL_LABELS = _GENRES + _MOODS + _INSTRUMENTS

# Rough initial thresholds — calibrate against real albums in WP-17
_THRESHOLD_COHESIVE = 0.85
_THRESHOLD_VARIED = 0.65

_STOP = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "was", "are", "were", "be", "been", "being",
    "i", "you", "we", "it", "this", "that", "my", "your", "me", "not",
    "have", "has", "what", "do", "so", "if", "all", "more", "just",
    "no", "by", "from", "as", "its", "their", "our", "still", "each",
    "into", "than", "then", "when", "will", "can", "they", "one", "who",
    "him", "her", "his", "she", "he", "how", "now", "yet",
}


def _tag_vector(tags: dict) -> list[float]:
    present = set(tags.get("genre", []) + tags.get("mood", []) + tags.get("instruments", []))
    return [1.0 if label in present else 0.0 for label in _ALL_LABELS]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _palette_consistency(findings: list[dict]) -> float:
    if len(findings) < 2:
        return 1.0
    vectors = [_tag_vector(f["tags"]) for f in findings]
    n = len(vectors)
    dim = len(_ALL_LABELS)
    centroid = [sum(v[i] for v in vectors) / n for i in range(dim)]
    sims = [_cosine(v, centroid) for v in vectors]
    return round(sum(sims) / len(sims), 4)


def _theme_threads(findings: list[dict], min_tracks: int | None = None) -> list[str]:
    """Words appearing in at least half the tracks (min 2)."""
    n = len(findings)
    threshold = max(2, min_tracks if min_tracks is not None else math.ceil(n / 2))

    word_track_count: Counter[str] = Counter()
    for f in findings:
        text = (f.get("lyrics") or "").lower()
        words = set(re.findall(r"[a-z']{3,}", text))
        for w in words:
            if w not in _STOP and not w.startswith("'"):
                word_track_count[w] += 1

    recurring = [w for w, cnt in word_track_count.items() if cnt >= threshold]
    # Sort by frequency desc, then alpha for stability
    recurring.sort(key=lambda w: (-word_track_count[w], w))
    return recurring[:8]


def _verdict(consistency: float, n_tracks: int) -> str:
    if n_tracks < 2:
        return ""
    if consistency >= _THRESHOLD_COHESIVE:
        return "cohesive_statement"
    if consistency >= _THRESHOLD_VARIED:
        return "varied"
    return "shuffle_playlist"


def build_cohesion(
    release_slug: str,
    out_dir: Path | None = None,
    findings: list[dict] | None = None,
) -> CohesionResult:
    """
    Compute cohesion for a release. If findings are already loaded (by the
    orchestrator), pass them in to avoid re-reading disk.
    """
    import json

    out_dir = Path(out_dir) if out_dir else OUT_DIR

    if findings is None:
        meta = get_release_meta(release_slug)
        if not meta:
            raise ValueError(f"Release not found: {release_slug}")
        artist_slug = meta["artist_id"]
        tracks = get_release_tracks(release_slug)
        findings = [
            json.loads((out_dir / f"{artist_slug}--{t['slug']}.json").read_text())
            for t in tracks
        ]

    consistency = _palette_consistency(findings)
    threads = _theme_threads(findings)
    verdict = _verdict(consistency, len(findings))

    return CohesionResult(
        palette_consistency=consistency,
        theme_threads=threads,
        verdict=verdict,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — cohesion worker")
    parser.add_argument("release_slug", help="Release slug (e.g. tria)")
    parser.add_argument("--out", help=f"Track records directory (default: {OUT_DIR})")
    args = parser.parse_args()

    result = build_cohesion(args.release_slug, out_dir=args.out)

    print(f"\nPalette consistency : {result.palette_consistency:.4f}  (method: discrete_tags, 39-dim centroid cosine)")
    print(f"Cohesion verdict    : {result.verdict or '(deferred — calibrate in WP-17)'}")
    print(f"Theme threads       : {result.theme_threads or '(none above threshold)'}")


if __name__ == "__main__":
    _main()
