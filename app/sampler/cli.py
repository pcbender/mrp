"""
prime-samples: cut hook-centred, loudness-matched 30s web samples from critic output.

Usage:
    python -m sampler.cli --all [--length 30] [--target-lufs -14] [--force]
    python -m sampler.cli --track pcbender--aiteo
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from .select import load_record, select_window

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "app" / "critic" / "out"
SAMPLES_DIR = REPO_ROOT / "site" / "public" / "samples"
CONTENT_RELEASES = REPO_ROOT / "content" / "releases"
OVERRIDES_PATH = Path(__file__).resolve().parent / "overrides.json"
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"


def _load_overrides() -> dict:
    if OVERRIDES_PATH.is_file():
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    return {}


def _two_pass_encode(
    source_path: str,
    start_s: float,
    duration_s: float,
    output_path: Path,
    target_lufs: float = -14.0,
) -> dict:
    """Two-pass loudnorm on the excerpt, then encode stereo 128k MP3."""
    fade_out_start = max(0.0, duration_s - 1.5)
    af_base = (
        f"afade=t=in:st=0:d=0.3,"
        f"afade=t=out:st={fade_out_start}:d=1.5,"
        f"loudnorm=I={target_lufs}:TP=-1:LRA=11"
    )

    # Pass 1 — measure the excerpt
    pass1 = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start_s), "-t", str(duration_s),
         "-i", source_path,
         "-af", af_base + ":print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )

    # Parse measured values from the JSON block in stderr
    af_pass2 = af_base  # fallback to single-pass if parsing fails
    measured_lufs = target_lufs
    match = re.search(r'\{\s*"input_i"\s*:.+?\}', pass1.stderr, re.DOTALL)
    if match:
        try:
            lnorm = json.loads(match.group(0))
            measured_lufs = float(lnorm.get("input_i", target_lufs))
            af_pass2 = (
                f"afade=t=in:st=0:d=0.3,"
                f"afade=t=out:st={fade_out_start}:d=1.5,"
                f"loudnorm=I={target_lufs}:TP=-1:LRA=11"
                f":measured_I={lnorm['input_i']}"
                f":measured_LRA={lnorm['input_lra']}"
                f":measured_TP={lnorm['input_tp']}"
                f":measured_thresh={lnorm['input_thresh']}"
                f":offset={lnorm['target_offset']}"
                f":linear=true"
            )
        except (json.JSONDecodeError, KeyError):
            pass

    # Pass 2 — encode
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pass2 = subprocess.run(
        ["ffmpeg", "-y", "-ss", str(start_s), "-t", str(duration_s),
         "-i", source_path,
         "-af", af_pass2,
         "-ac", "2", "-c:a", "libmp3lame", "-b:a", "128k",
         str(output_path)],
        capture_output=True, text=True,
    )
    return {
        "returncode": pass2.returncode,
        "stderr": pass2.stderr,
        "measured_lufs": measured_lufs,
    }


def _find_release_yaml(track_id: str) -> Path | None:
    """Locate content/releases/{slug}.yaml containing this track."""
    parts = track_id.split("--", 1)
    if len(parts) != 2:
        return None
    artist_slug, track_slug = parts
    for yaml_path in sorted(CONTENT_RELEASES.glob("*.yaml")):
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not data or "release" not in data:
            continue
        release = data["release"]
        if release.get("artist_id") != artist_slug:
            continue
        if release.get("song", {}).get("slug") == track_slug:
            return yaml_path
        if any(t.get("slug") == track_slug for t in release.get("tracks", [])):
            return yaml_path
    return None


def _write_preview_audio(yaml_path: Path, track_slug: str, preview_url: str) -> bool:
    """Set preview_audio on the matching track in the release YAML."""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    release = data["release"]

    song = release.get("song")
    if song and song.get("slug") == track_slug:
        song["preview_audio"] = preview_url
    else:
        matched = False
        for track in release.get("tracks", []):
            if track.get("slug") == track_slug:
                track["preview_audio"] = preview_url
                matched = True
                break
        if not matched:
            return False

    yaml_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return True


def _process_track(
    track_id: str,
    length: float,
    target_lufs: float,
    force: bool,
    overrides: dict,
) -> dict:
    record_path = OUT_DIR / f"{track_id}.json"
    if not record_path.is_file():
        return {"track_id": track_id, "status": "needs_source",
                "message": f"no critic record at {record_path}"}

    record = load_record(OUT_DIR, track_id)
    if "source" not in record:
        return {"track_id": track_id, "status": "skipped",
                "message": "no source field (album-level record)"}
    source_path = record["source"]["path"]
    if not Path(source_path).is_file():
        return {"track_id": track_id, "status": "needs_source",
                "message": f"master not found: {source_path}"}

    total = record["hard_facts"]["duration_s"]
    output_path = SAMPLES_DIR / f"{track_id}.mp3"

    if output_path.is_file() and not force:
        return {"track_id": track_id, "status": "cached",
                "sample_path": str(output_path.relative_to(REPO_ROOT))}

    window = select_window(record, length=length, overrides=overrides)
    start_s, actual_dur = window["start_s"], window["duration_s"]

    if actual_dur < 5.0:
        return {"track_id": track_id, "status": "short_track", "duration_s": total}

    encode = _two_pass_encode(source_path, start_s, actual_dur, output_path, target_lufs)
    if encode["returncode"] != 0:
        return {"track_id": track_id, "status": "encode_error",
                "stderr": encode["stderr"][-500:]}

    preview_url = f"/samples/{track_id}.mp3"
    _, track_slug = track_id.split("--", 1)
    yaml_path = _find_release_yaml(track_id)
    writeback = _write_preview_audio(yaml_path, track_slug, preview_url) if yaml_path else False

    return {
        "track_id": track_id,
        "sample_path": str(output_path.relative_to(REPO_ROOT)),
        "preview_audio": preview_url,
        "start_s": round(start_s, 2),
        "duration_s": round(actual_dur, 2),
        "selection": window["selection"],
        "target_lufs": target_lufs,
        "measured_lufs_out": round(encode["measured_lufs"], 1),
        "format": "mp3_128k",
        "status": "ok",
        "preview_audio_written": writeback,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cut hook-centred web samples from critic output."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true",
                       help="Process every critic record in out/")
    group.add_argument("--track", metavar="ID",
                       help="Process one track by track_id (e.g. pcbender--aiteo)")
    parser.add_argument("--length", type=float, default=30.0, metavar="SEC")
    parser.add_argument("--target-lufs", type=float, default=-14.0, metavar="LUFS")
    parser.add_argument("--force", action="store_true",
                        help="Re-generate even if sample already exists")
    args = parser.parse_args()

    overrides = _load_overrides()
    track_ids = [args.track] if args.track else sorted(
        p.stem for p in OUT_DIR.glob("*.json")
    )

    results = []
    for track_id in track_ids:
        result = _process_track(track_id, args.length, args.target_lufs,
                                args.force, overrides)
        results.append(result)
        status = result["status"]
        sel = result.get("selection", "")
        start = f"  start={result['start_s']}s" if "start_s" in result else ""
        print(f"  {track_id:45s}  [{status}]  {sel}{start}")

    MANIFEST_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nManifest written → {MANIFEST_PATH.relative_to(REPO_ROOT)}")

    errors = [r for r in results if r["status"] not in ("ok", "cached", "skipped")]
    if errors:
        print(f"\n{len(errors)} error(s):")
        for e in errors:
            print(f"  {e['track_id']}: {e['status']} — {e.get('message', '')}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
