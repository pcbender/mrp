import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import PIL

from mrp.video.encoder import OutputTimeline
from mrp.video.renderer import RenderContext
from mrp.video.verification import VerificationExpectation, VerificationReport

RENDER_MANIFEST_VERSION = 1


class SpirophonicManifestError(Exception):
    pass


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_hashes(
    context: RenderContext,
    project_manifest_path: Path,
) -> dict[str, str]:
    project = context.project
    paths = {
        "project": project_manifest_path,
        "lyrics.source": (context.root / project.lyrics.source).resolve(),
        "lyrics.aligned": (context.root / project.lyrics.aligned).resolve(),
        "cards.opening": (context.root / project.cards.opening.file).resolve(),
        "cards.closing": (context.root / project.cards.closing.file).resolve(),
        "text.font": context.font_path,
    }
    hashes = {label: _hash_file(path) for label, path in paths.items()}
    hashes.update(
        {
            f"audio.{name}": value
            for name, value in sorted(context.analysis.input_hashes.items())
        }
    )
    return dict(sorted(hashes.items()))


def _ffmpeg_version() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return "unavailable"
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def build_render_manifest(
    context: RenderContext,
    timeline: OutputTimeline,
    expectation: VerificationExpectation,
    verification: VerificationReport,
    *,
    project_manifest_path: Path,
    output_path: Path,
    encoded_path: Path,
    command: tuple[str, ...],
    performance: dict[str, float | int],
    warnings: tuple[str, ...],
) -> dict[str, Any]:
    recorded_command = list(command)
    if recorded_command:
        recorded_command[-1] = str(output_path)
    casting_sections: dict[str, dict[str, Any]] = {}
    for section in context.lyrics.sections:
        composition = context.section_compositions[section.id]
        casting_sections[section.id] = {
            "key": composition.key,
            "source": composition.casting.source,
            "seed": composition.casting.seed,
            "generator_version": composition.casting.generator_version,
            "traces": [layer.config.id for layer in composition.layers],
        }
    return {
        "version": RENDER_MANIFEST_VERSION,
        "project": {
            "title": context.project.title,
            "manifest": str(project_manifest_path),
            "hash": _hash_file(project_manifest_path),
            "seed": context.project.video.seed,
        },
        "inputs": _input_hashes(context, project_manifest_path),
        "analysis_cache_key": context.analysis.cache_key,
        "timeline": {
            "draft": timeline.draft,
            "cards_included": timeline.include_cards,
            "source_start": timeline.source_audio_start,
            "source_end": timeline.source_audio_end,
            "opening_duration": timeline.opening_duration,
            "song_frame_duration": timeline.song_frames / timeline.fps,
            "closing_duration": timeline.closing_duration,
            "total_frames": timeline.total_frames,
            "output_duration": timeline.output_duration,
        },
        "dependencies": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "pillow": PIL.__version__,
            "ffmpeg": _ffmpeg_version(),
        },
        "encoding": {
            "command": recorded_command,
            "settings": context.project.encoding.model_dump(mode="json"),
        },
        "artistic_presets": {
            "mapping": context.project.visuals.mapping_preset,
            "palette": context.project.visuals.palette_preset,
            "custom_palette": list(context.project.visuals.palette),
        },
        "casting": {
            "auto_enabled": context.project.visuals.auto_casting,
            "sections": casting_sections,
        },
        "performance": performance,
        "output": {
            "path": str(output_path),
            "sha256": _hash_file(encoded_path),
            "expectation": expectation.summary(),
            "metadata": verification.metadata.summary(),
        },
        "verification": {
            "valid": True,
            "checks": list(verification.checks),
        },
        "warnings": list(warnings),
    }


def write_render_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        raise SpirophonicManifestError(
            f"could not write render manifest {path}: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
