"""
Output validation for all critic workers (WP-14).

Validates that synthesized records have required fields, valid enumerations,
and non-empty text. Used as a post-generation guard in all three writers
(track, album, recontextualize) — warns loudly but does not suppress output,
since a flawed review is still more useful than no review.

Usage (standalone):
    python -m critic.schema <out_dir>  — validate all records in out/
"""
from __future__ import annotations

import json
from pathlib import Path

_VALID_RANKS = {2, 3, 4, 5}
_VALID_SUM_VS_PARTS = {"greater", "equal", "lesser"}
_VALID_PERSONA_DELIVERY = {"on_character", "expands", "off_character"}


# ── Per-record validators ─────────────────────────────────────────────────────

def validate_track_review(review: dict) -> list[str]:
    """Return list of issues. Empty list = valid."""
    issues: list[str] = []
    if not review.get("review_text", "").strip():
        issues.append("review_text is empty")
    rank = review.get("verdict_tier", {}).get("rank")
    if rank not in _VALID_RANKS:
        issues.append(f"verdict_tier.rank out of range: {rank!r} (must be 2–5)")
    if not review.get("anchors_used"):
        issues.append("anchors_used is empty")
    return issues


def validate_album_review(review: dict) -> list[str]:
    issues: list[str] = []
    if not review.get("review_text", "").strip():
        issues.append("review_text is empty")
    rank = review.get("verdict_tier", {}).get("rank")
    if rank not in _VALID_RANKS:
        issues.append(f"verdict_tier.rank out of range: {rank!r} (must be 2–5)")
    if review.get("sum_vs_parts") not in _VALID_SUM_VS_PARTS:
        issues.append(f"invalid sum_vs_parts: {review.get('sum_vs_parts')!r}")
    if review.get("persona_delivery") not in _VALID_PERSONA_DELIVERY:
        issues.append(f"invalid persona_delivery: {review.get('persona_delivery')!r}")
    if not review.get("anchors_used"):
        issues.append("anchors_used is empty")
    return issues


def validate_context_review(tic: dict) -> list[str]:
    issues: list[str] = []
    if not tic.get("review_text", "").strip():
        issues.append("review_text is empty")
    s_rank = tic.get("standalone_rank")
    if s_rank not in _VALID_RANKS:
        issues.append(f"standalone_rank out of range: {s_rank!r}")
    c_rank = tic.get("context_rank")
    if c_rank is not None:
        if c_rank not in _VALID_RANKS:
            issues.append(f"context_rank out of range: {c_rank!r}")
        if c_rank == s_rank:
            issues.append("context_rank equals standalone_rank (should be null when unchanged)")
        if not tic.get("context_note", "").strip():
            issues.append("context_note required when context_rank is set")
    return issues


def validate_record(data: dict) -> dict[str, list[str]]:
    """
    Validate a full record (track or album). Returns a dict mapping
    section name → list of issues. Empty lists mean that section is clean.
    """
    results: dict[str, list[str]] = {}

    if "album_id" in data:
        results["album_review"] = validate_album_review(data.get("review", {}))
        for i, tic in enumerate(data.get("track_reviews_in_context", []), 1):
            key = f"track_in_context[{i}] {tic.get('track_id', '')}"
            issues = validate_context_review(tic)
            if issues:
                results[key] = issues
    else:
        results["review"] = validate_track_review(data.get("review", {}))

    return {k: v for k, v in results.items() if v}


def warn_issues(label: str, issues: list[str]) -> None:
    """Print validation warnings to stdout without raising."""
    if issues:
        for issue in issues:
            print(f"  ⚠  [{label}] {issue}")


# ── Bulk validator (CLI) ──────────────────────────────────────────────────────

def validate_out_dir(out_dir: Path) -> bool:
    """Validate all records in out_dir. Returns True if all clean."""
    records = sorted(out_dir.glob("*.json"))
    if not records:
        print(f"No JSON records found in {out_dir}")
        return True

    all_clean = True
    for path in records:
        if path.name.startswith(("qa_report", "pipeline_")):
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"✗  {path.name}: JSON parse error — {exc}")
            all_clean = False
            continue

        issues = validate_record(data)
        if issues:
            all_clean = False
            print(f"✗  {path.name}:")
            for section, section_issues in issues.items():
                for issue in section_issues:
                    print(f"     [{section}] {issue}")
        else:
            print(f"✓  {path.name}")

    return all_clean


if __name__ == "__main__":
    import argparse
    import sys
    from .config import OUT_DIR

    parser = argparse.ArgumentParser(description="MRP Critic — output validator")
    parser.add_argument("out_dir", nargs="?", help=f"Records directory (default: {OUT_DIR})")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    clean = validate_out_dir(out_dir)
    sys.exit(0 if clean else 1)
