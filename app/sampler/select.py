"""Selection logic: pick the best 30s window from critic metadata."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


def load_record(out_dir: Path, track_id: str) -> dict[str, Any]:
    return json.loads((out_dir / f"{track_id}.json").read_text(encoding="utf-8"))


def _measure_section_rms(source_path: str, start: float, end: float) -> float:
    """Return mean RMS level (dBFS) for a time window using ffmpeg volumedetect."""
    result = subprocess.run(
        ["ffmpeg", "-ss", str(start), "-t", str(end - start), "-i", source_path,
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True
    )
    match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", result.stderr)
    return float(match.group(1)) if match else -100.0


def select_window(
    record: dict[str, Any],
    length: float = 30.0,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fallback ladder — returns {start_s, duration_s, selection}.

    Rung 1: manual override in overrides.json
    Rung 2: first semantically-labelled chorus/hook section
             (sections are currently S1..Sn — this rung won't fire yet)
    Rung 3: highest-energy 30s window by peak RMS across sections
    Rung 4: 25% offset into track (never the cold open)
    """
    track_id = record["track_id"]
    total = record["hard_facts"]["duration_s"]
    sections = record["hard_facts"].get("sections", [])
    source_path = record["source"]["path"]

    actual_len = min(length, total)

    def clamp(start: float) -> tuple[float, float]:
        return max(0.0, min(start, total - actual_len)), actual_len

    # Rung 1 — manual override
    if overrides and track_id in overrides:
        ov = overrides[track_id]
        start, dur = clamp(float(ov["start_s"]))
        return {"start_s": start, "duration_s": dur, "selection": "manual_override"}

    # Rung 2 — semantic section label
    for section in sections:
        label = section.get("label", "").lower()
        if any(kw in label for kw in ("chorus", "hook", "refrain")):
            start, dur = clamp(section["start"])
            return {"start_s": start, "duration_s": dur, "selection": "first_chorus"}

    # Rung 3 — peak energy section
    if sections:
        best_rms, best_start = -200.0, None
        for section in sections:
            rms = _measure_section_rms(source_path, section["start"], section["end"])
            if rms > best_rms:
                best_rms, best_start = rms, section["start"]
        if best_start is not None:
            start, dur = clamp(best_start)
            return {"start_s": start, "duration_s": dur, "selection": "peak_energy"}

    # Rung 4 — fallback offset
    start, dur = clamp(total * 0.25)
    return {"start_s": start, "duration_s": dur, "selection": "fallback_offset"}
