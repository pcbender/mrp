"""
DSP worker: fills hard_facts from the 22050 Hz mono array produced by ingest.

Usage:
    python -m critic.dsp <audio_path> [--track-id <id>]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import warnings
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
from scipy.signal import find_peaks, savgol_filter

from .ingest import ingest
from .record import Confidence, HardFacts, Section

SR = 22050

# Krumhansl-Schmuckler key profiles
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _detect_bpm(arr: np.ndarray) -> tuple[float, float]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tempo, beats = librosa.beat.beat_track(y=arr, sr=SR)

    bpm = float(np.atleast_1d(tempo)[0])

    if len(beats) < 4:
        return round(bpm, 1), 0.3

    ibi = np.diff(librosa.frames_to_time(beats, sr=SR))
    cv = float(ibi.std() / ibi.mean()) if ibi.mean() > 0 else 1.0
    confidence = round(float(np.clip(1.0 - cv, 0.0, 1.0)), 3)
    return round(bpm, 1), confidence


def _detect_key(arr: np.ndarray) -> tuple[str, str, float]:
    chroma = librosa.feature.chroma_cqt(y=arr, sr=SR)
    mean_chroma = chroma.mean(axis=1)

    best_score = -np.inf
    best_key, best_mode = "C", "major"

    for i in range(12):
        for profile, mode in [(_KS_MAJOR, "major"), (_KS_MINOR, "minor")]:
            rotated = np.roll(profile, i)
            score = float(np.corrcoef(mean_chroma, rotated)[0, 1])
            if score > best_score:
                best_score, best_key, best_mode = score, _NOTES[i], mode

    confidence = round(float(np.clip((best_score + 1) / 2, 0.0, 1.0)), 3)
    return best_key, best_mode, confidence


def _estimate_time_sig(arr: np.ndarray) -> str:
    """Best-effort 4/4 vs 3/4 via tempogram triple/quadruple ratio."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tempo, _ = librosa.beat.beat_track(y=arr, sr=SR)

        base = float(np.atleast_1d(tempo)[0])
        if base <= 0:
            return "4/4"

        tg = librosa.feature.tempogram(y=arr, sr=SR, hop_length=512)
        mean_tg = tg.mean(axis=1)
        freqs = librosa.tempo_frequencies(len(mean_tg), hop_length=512, sr=SR)

        def tg_at(t: float) -> float:
            idx = int(np.argmin(np.abs(freqs - t)))
            return float(mean_tg[idx])

        return "3/4" if tg_at(base * 3) > tg_at(base * 4) * 1.2 else "4/4"
    except Exception:
        return "4/4"


def _measure_lufs(arr: np.ndarray) -> float:
    meter = pyln.Meter(SR)
    try:
        loudness = meter.integrated_loudness(arr.astype(np.float64))
        return round(float(loudness), 1) if np.isfinite(loudness) else -99.0
    except Exception:
        return -99.0


def _detect_sections(arr: np.ndarray) -> list[Section]:
    hop = 512
    duration = round(len(arr) / SR, 2)
    min_section_s = 15.0

    mfcc = librosa.feature.mfcc(y=arr, sr=SR, hop_length=hop, n_mfcc=13)
    novelty = np.sum(np.abs(np.diff(mfcc, axis=1)), axis=0)

    # Smooth over ~3 seconds; savgol needs odd window >= 3
    w = max(3, int(3 * SR / hop))
    w = w if w % 2 == 1 else w + 1
    w = min(w, len(novelty) - (1 if len(novelty) % 2 == 0 else 0))

    if w >= 3 and w < len(novelty):
        smooth = savgol_filter(novelty, window_length=w, polyorder=2)
    else:
        smooth = novelty

    min_dist = max(1, int(min_section_s * SR / hop))
    peaks, _ = find_peaks(
        smooth,
        distance=min_dist,
        height=np.percentile(smooth, 70),
    )

    boundary_times = [0.0] + list(
        librosa.frames_to_time(peaks, sr=SR, hop_length=hop)
    ) + [duration]

    return [
        Section(
            start=round(boundary_times[i], 2),
            end=round(boundary_times[i + 1], 2),
            label=f"S{i + 1}",
        )
        for i in range(len(boundary_times) - 1)
    ]


def extract_dsp(arr: np.ndarray) -> HardFacts:
    """Run all DSP analysis and return a populated HardFacts."""
    bpm, bpm_conf = _detect_bpm(arr)
    key, mode, key_conf = _detect_key(arr)
    time_sig = _estimate_time_sig(arr)
    lufs = _measure_lufs(arr)
    sections = _detect_sections(arr)

    return HardFacts(
        bpm=bpm,
        key=key,
        mode=mode,
        time_signature=time_sig,
        duration_s=round(len(arr) / SR, 2),
        lufs=lufs,
        sections=sections,
        confidence=Confidence(bpm=bpm_conf, key=key_conf),
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — DSP worker")
    parser.add_argument("path", help="Audio file")
    parser.add_argument("--track-id", help="Track ID override")
    args = parser.parse_args()

    print(f"Ingesting: {args.path}")
    finding, arr = ingest(args.path, track_id=args.track_id)

    print("Running DSP analysis…")
    finding.hard_facts = extract_dsp(arr)

    print(f"\nhard_facts:\n{json.dumps(dataclasses.asdict(finding.hard_facts), indent=2)}")


if __name__ == "__main__":
    _main()
