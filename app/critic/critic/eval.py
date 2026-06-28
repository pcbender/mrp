"""
WP-17 — Eval + approval gate.

Two responsibilities:
  1. Calibration harness: compare current records to expected rungs; flag drift.
  2. Approval gate: flip review status pending → approved → publishable.

Usage:
    critic calibrate                 # check all reference entries, write calibration.md
    critic approve <id>              # pending → approved
    critic approve <id> --publish    # approved → publishable
    critic approve <id> --all-tracks # album: also approve all contextual track reviews

A NOTE about SOUL.md: WP-17 was inspired by Cantor's SOUL.md approval policy,
but mrp owns its own copy of this logic. Do not import or look for SOUL.md.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_CALIBRATION_SPEC = "calibration.yaml"
_CALIBRATION_REPORT = "calibration.md"
_STATUS_ORDER = ("pending", "approved", "publishable")


# ── Approval gate ─────────────────────────────────────────────────────────────

def _resolve_record(id_: str, out_dir: Path) -> tuple[Path, dict]:
    """Return (path, data) for a track or album record."""
    direct = out_dir / f"{id_}.json"
    if direct.exists():
        return direct, json.loads(direct.read_text())
    raise FileNotFoundError(f"No record found for id: {id_!r} in {out_dir}")


def approve(id_: str, publish: bool = False, all_tracks: bool = False, out_dir: Path | None = None) -> Path:
    """
    Flip status on a track or album record.

    publish=False  →  pending / approved → approved
    publish=True   →  pending / approved → publishable
    all_tracks     →  album only — also flip all contextual track reviews
    """
    from .config import OUT_DIR
    out_dir = out_dir or OUT_DIR
    path, data = _resolve_record(id_, out_dir)

    target_status = "publishable" if publish else "approved"
    is_album = "album_id" in data

    if is_album:
        review = data.get("review", {})
        old = review.get("status", "pending")
        review["status"] = target_status
        data["review"] = review

        if all_tracks:
            for tic in data.get("track_reviews_in_context", []):
                tic["status"] = target_status
            print(f"  {id_}  (album + {len(data.get('track_reviews_in_context', []))} contextual reviews)  {old} → {target_status}")
        else:
            print(f"  {id_}  (album only)  {old} → {target_status}")
    else:
        review = data.get("review", {})
        old = review.get("status", "pending")
        review["status"] = target_status
        data["review"] = review
        print(f"  {id_}  {old} → {target_status}")

    path.write_text(json.dumps(data, indent=2))
    return path


# ── Calibration harness ───────────────────────────────────────────────────────

def _rank_drift(actual: int, expected: int) -> str:
    d = actual - expected
    if d == 0:
        return "✓"
    sym = "↑" if d > 0 else "↓"
    severity = "⚠" if abs(d) == 1 else "✗"
    return f"{severity} {sym}{abs(d)}"


def _load_track_rank(track_id: str, out_dir: Path) -> int | None:
    path = out_dir / f"{track_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data.get("review", {}).get("verdict_tier", {}).get("rank")


def _load_album_record(album_id: str, out_dir: Path) -> dict | None:
    path = out_dir / f"{album_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def calibrate(out_dir: Path | None = None) -> Path:
    """Check records against calibration.yaml; write calibration.md. Returns report path."""
    from .config import OUT_DIR
    out_dir = out_dir or OUT_DIR

    spec_path = out_dir / _CALIBRATION_SPEC
    if not spec_path.exists():
        raise FileNotFoundError(f"No calibration spec found at {spec_path}")

    spec = yaml.safe_load(spec_path.read_text())
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [f"# Critic Calibration Report\n\nGenerated: {now}\n"]

    all_pass = True

    # ── Track calibration ─────────────────────────────────────────────────────
    track_refs = spec.get("tracks", [])
    if track_refs:
        lines.append("## Track Ranks\n")
        lines.append("| Track | Expected | Actual | Drift | Note |")
        lines.append("|-------|----------|--------|-------|------|")
        for ref in track_refs:
            tid = ref["track_id"]
            expected = ref["expected_rank"]
            actual = _load_track_rank(tid, out_dir)
            if actual is None:
                lines.append(f"| {tid} | {expected} | — | ⚠ missing | {ref.get('note', '')} |")
                all_pass = False
            else:
                drift = _rank_drift(actual, expected)
                if drift != "✓":
                    all_pass = False
                lines.append(f"| {tid} | {expected} | {actual} | {drift} | {ref.get('note', '')} |")
        lines.append("")

    # ── Album calibration ─────────────────────────────────────────────────────
    album_refs = spec.get("albums", [])
    if album_refs:
        lines.append("## Album Records\n")
        lines.append("| Album | Expected rank | Actual rank | Rank drift | Expected sum_vs_parts | Actual sum_vs_parts | Note |")
        lines.append("|-------|---------------|-------------|------------|----------------------|---------------------|------|")
        for ref in album_refs:
            aid = ref["album_id"]
            exp_rank = ref.get("expected_rank")
            exp_svp = ref.get("expected_sum_vs_parts", "")
            data = _load_album_record(aid, out_dir)
            if data is None:
                lines.append(f"| {aid} | {exp_rank} | — | ⚠ missing | {exp_svp} | — | {ref.get('note', '')} |")
                all_pass = False
            else:
                rev = data.get("review", {})
                act_rank = rev.get("verdict_tier", {}).get("rank")
                act_svp = rev.get("sum_vs_parts", "")
                rank_drift = _rank_drift(act_rank, exp_rank) if act_rank and exp_rank else "—"
                svp_match = "✓" if act_svp == exp_svp else f"⚠ got {act_svp!r}"
                if rank_drift != "✓" or svp_match != "✓":
                    all_pass = False
                lines.append(f"| {aid} | {exp_rank} | {act_rank} | {rank_drift} | {exp_svp} | {act_svp} | {svp_match} · {ref.get('note', '')} |")
        lines.append("")

    # ── Cohesion threshold calibration ────────────────────────────────────────
    lines.append("## Cohesion Thresholds (current calibration)\n")
    lines.append("These are preliminary — calibrate against more albums before hardening.\n")
    lines.append("| Verdict | Threshold | Basis |")
    lines.append("|---------|-----------|-------|")
    lines.append("| cohesive_statement | ≥ 0.85 | deferred — single album reference |")
    lines.append("| varied | 0.65 – 0.85 | Tria EP: palette_consistency=0.79 |")
    lines.append("| shuffle_playlist | < 0.65 | deferred — no reference yet |")
    lines.append("")
    lines.append("To recalibrate, run `critic album <slug>` on additional releases and ")
    lines.append("compare palette_consistency against subjective cohesion judgement.\n")

    # ── Approval status summary ───────────────────────────────────────────────
    all_records = sorted(out_dir.glob("*.json"))
    if all_records:
        lines.append("## Approval Status\n")
        lines.append("| Record | Type | Status |")
        lines.append("|--------|------|--------|")
        for p in all_records:
            if p.name.startswith(("qa_report", "pipeline_", "calibration")):
                continue
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            if "album_id" in data:
                status = data.get("review", {}).get("status", "pending")
                lines.append(f"| {data['album_id']} | album | {status} |")
            else:
                status = data.get("review", {}).get("status", "pending")
                lines.append(f"| {data['track_id']} | track | {status} |")
        lines.append("")

    lines.append(f"**Result: {'PASS' if all_pass else 'DRIFT DETECTED'}**\n")

    report_path = out_dir / _CALIBRATION_REPORT
    report_path.write_text("\n".join(lines))
    return report_path
