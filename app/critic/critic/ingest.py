"""
Ingest worker: resolve path, copy masters from /mnt/ if needed,
load a downsampled mono array, produce an Opus proxy.

Usage:
    python -m critic.ingest <audio_path> [--track-id <id>]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np

from .config import MASTERS_DIR, PROXY_DIR
from .record import SourceRecord, TrackFinding


def _check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit(
            "ffmpeg not found.\n"
            "Install it with:  sudo apt install ffmpeg"
        )


def _resolve_path(raw: str) -> Path:
    """Copy /mnt/... paths to ext4 MASTERS_DIR via rsync; return local path."""
    p = Path(raw)
    if str(p).startswith("/mnt/"):
        MASTERS_DIR.mkdir(parents=True, exist_ok=True)
        dest = MASTERS_DIR / p.name
        print(f"  Copying from Windows mount → {dest}")
        subprocess.run(["rsync", "-a", "--progress", str(p), str(dest)], check=True)
        return dest
    return p.resolve()


def _make_proxy(src: Path, track_id: str) -> Path:
    PROXY_DIR.mkdir(parents=True, exist_ok=True)
    proxy = PROXY_DIR / f"{track_id}.opus"
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-c:a", "libopus", "-b:a", "96k", str(proxy)],
        capture_output=True,
    )
    if result.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{result.stderr.decode()}")
    return proxy


def ingest(raw_path: str, track_id: str | None = None) -> tuple[TrackFinding, np.ndarray]:
    """
    Resolve path, copy from Windows mount if needed, load audio,
    produce Opus proxy. Returns (TrackFinding, mono_array_at_22050Hz).
    The array is for DSP only — not serialised into the record.
    """
    _check_ffmpeg()

    path = _resolve_path(raw_path)
    if not path.exists():
        sys.exit(f"File not found: {path}")

    slug = track_id or path.stem

    try:
        arr, _ = librosa.load(str(path), sr=22050, mono=True)
    except Exception as exc:
        sys.exit(f"Cannot read audio: {exc}")

    proxy = _make_proxy(path, slug)

    finding = TrackFinding(
        track_id=slug,
        source=SourceRecord(
            type="local_master",
            path=str(path),
            proxy=str(proxy),
        ),
    )

    return finding, arr


def _main() -> None:
    parser = argparse.ArgumentParser(description="MRP Critic — ingest worker")
    parser.add_argument("path", help="Audio file (WAV, AIFF, FLAC, …)")
    parser.add_argument("--track-id", help="Track ID override (default: filename stem)")
    args = parser.parse_args()

    print(f"\nIngesting: {args.path}")
    finding, arr = ingest(args.path, track_id=args.track_id)

    duration_s = len(arr) / 22050
    proxy_path = Path(finding.source.proxy)
    proxy_kb = proxy_path.stat().st_size / 1024

    print(f"\n  Resolved path  : {finding.source.path}")
    print(f"  Proxy          : {finding.source.proxy}")
    print(f"  Proxy size     : {proxy_kb:.1f} KB")
    print(f"  Sample rate    : 22050 Hz (downsampled mono)")
    print(f"  Duration       : {duration_s:.1f}s  ({duration_s / 60:.2f} min)")
    print(f"\nRecord JSON:\n{finding.to_json()}")


if __name__ == "__main__":
    _main()
