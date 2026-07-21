"""Versioned aligned-lyrics editing for the per-track Video workspace."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from pydantic import ValidationError

from mrp.admin.video_workspace import track_key


class TimingEditorError(Exception):
    def __init__(self, *problems: str):
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


def timing_path(root: Path, release: dict[str, Any], track: dict[str, Any]) -> Path:
    return (
        root
        / "assets"
        / "source"
        / "video"
        / track_key(release, track)
        / "lyrics.aligned.yaml"
    )


def _preflight_path(root: Path, release: dict[str, Any], track: dict[str, Any]) -> Path:
    return (
        root
        / "assets"
        / "processed"
        / "video"
        / track_key(release, track)
        / "logs"
        / "preflight.json"
    )


def _master_duration(root: Path, release: dict[str, Any], track: dict[str, Any]) -> float | None:
    path = _preflight_path(root, release, track)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        duration = float(value.get("master_duration"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def _load(path: Path):
    from mrp.video.project import SpirophonicValidationError, load_aligned_lyrics

    try:
        return load_aligned_lyrics(path)
    except SpirophonicValidationError as exc:
        raise TimingEditorError(*exc.problems) from exc


def _summary(document: Any) -> dict[str, int | bool]:
    counts = {"matched": 0, "uncertain": 0, "unmatched": 0}
    pending = 0
    total_lines = 0
    reviewed_lines = 0
    reviewed_sections = 0
    for section in document.sections:
        if section.reviewed is True:
            reviewed_sections += 1
        for line in section.lines:
            total_lines += 1
            if line.reviewed is True:
                reviewed_lines += 1
            if line.status in counts:
                counts[line.status] += 1
            if line.status in {"uncertain", "unmatched"} and line.reviewed is not True:
                pending += 1
    return {
        **counts,
        "sections": len(document.sections),
        "reviewed_sections": reviewed_sections,
        "lines": total_lines,
        "reviewed_lines": reviewed_lines,
        "pending_review": pending,
        "review_complete": pending == 0,
    }


def load_timing(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
) -> dict[str, Any]:
    path = timing_path(root, release, track)
    relative = path.relative_to(root).as_posix()
    if not path.is_file():
        return {
            "exists": False,
            "path": relative,
            "document": None,
            "summary": None,
            "master_duration": _master_duration(root, release, track),
        }
    document = _load(path)
    return {
        "exists": True,
        "path": relative,
        "document": document,
        "summary": _summary(document),
        "master_duration": _master_duration(root, release, track),
    }


def _field(fields: Mapping[str, Sequence[str]], name: str, count: int) -> list[str]:
    values = [str(value) for value in fields.get(name, [])]
    if len(values) != count:
        raise TimingEditorError(
            f"{name} supplied {len(values)} values; expected {count}"
        )
    return values


def _number(value: str, label: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise TimingEditorError(f"{label} must be a number") from exc
    if not math.isfinite(number) or number < 0:
        raise TimingEditorError(f"{label} must be a finite non-negative number")
    return round(number, 6)


def _reviewed(value: str) -> bool:
    return value.casefold() in {"true", "1", "yes", "on"}


def _write(path: Path, document: Any) -> None:
    payload = document.model_dump(mode="json", exclude_none=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_timing(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    fields: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Build and validate a timing edit without changing the source artifact."""
    from mrp.video.project import AlignedLyrics

    path = timing_path(root, release, track)
    if not path.is_file():
        raise TimingEditorError("aligned lyrics do not exist; run alignment first")
    original = _load(path)
    payload = original.model_dump(mode="json", exclude_none=True)

    section_count = len(original.sections)
    section_ids = _field(fields, "section_id", section_count)
    section_starts = _field(fields, "section_start", section_count)
    section_ends = _field(fields, "section_end", section_count)
    section_reviews = _field(fields, "section_reviewed", section_count)
    expected_section_ids = [section.id for section in original.sections]
    if section_ids != expected_section_ids:
        raise TimingEditorError("section identities or order changed while saving")

    expected_line_keys = [
        f"{section.id}:{line_index}"
        for section in original.sections
        for line_index, _line in enumerate(section.lines)
    ]
    line_count = len(expected_line_keys)
    line_keys = _field(fields, "line_key", line_count)
    line_starts = _field(fields, "line_start", line_count)
    line_ends = _field(fields, "line_end", line_count)
    line_reviews = _field(fields, "line_reviewed", line_count)
    if line_keys != expected_line_keys:
        raise TimingEditorError("line identities or order changed while saving")

    line_offset = 0
    for section_index, section in enumerate(payload["sections"]):
        section["start"] = _number(
            section_starts[section_index],
            f"section {section_ids[section_index]} start",
        )
        section["end"] = _number(
            section_ends[section_index],
            f"section {section_ids[section_index]} end",
        )
        section["reviewed"] = _reviewed(section_reviews[section_index])
        for line_index, line in enumerate(section.get("lines") or []):
            key = expected_line_keys[line_offset]
            line["start"] = _number(line_starts[line_offset], f"line {key} start")
            line["end"] = _number(line_ends[line_offset], f"line {key} end")
            line["reviewed"] = _reviewed(line_reviews[line_offset])
            line_offset += 1

    try:
        updated = AlignedLyrics.model_validate(payload)
    except ValidationError as exc:
        problems = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            problems.append(f"{location}: {error['msg']}")
        raise TimingEditorError(*problems) from exc

    duration = _master_duration(root, release, track)
    if duration is not None and updated.sections[-1].end > duration + 0.001:
        raise TimingEditorError(
            f"final section ends at {updated.sections[-1].end:.3f}s, "
            f"after the {duration:.3f}s master"
        )

    return {
        "path": path.relative_to(root).as_posix(),
        "document": updated,
        "summary": _summary(updated),
        "master_duration": duration,
    }


def persist_timing(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    document: Any,
) -> None:
    """Atomically replace one track's validated timing artifact."""
    _write(timing_path(root, release, track), document)


def save_timing(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    fields: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Validate and atomically replace one track's versioned timing artifact."""
    result = validate_timing(root, release, track, fields)
    persist_timing(root, release, track, result["document"])
    return result
