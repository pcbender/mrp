"""Versioned aligned-lyrics editing for the per-track Video workspace."""
from __future__ import annotations

import json
import math
import os
import re
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


def _preflight(root: Path, release: dict[str, Any], track: dict[str, Any]) -> dict[str, Any]:
    path = _preflight_path(root, release, track)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _master_duration(root: Path, release: dict[str, Any], track: dict[str, Any]) -> float | None:
    try:
        duration = float(_preflight(root, release, track).get("master_duration"))
    except (TypeError, ValueError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def lyric_directions(
    root: Path, release: dict[str, Any], track: dict[str, Any]
) -> list[str]:
    """Bracketed performance directions prepare left out of the sung lyric.

    Shown so a line vanishing from the lyric is always visible as a choice
    rather than a silent loss.
    """
    values = _preflight(root, release, track).get("lyric_directions") or []
    return [str(value) for value in values if str(value).strip()]


def transcript_path(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    cache_key: str,
) -> Path:
    return (
        root
        / "assets"
        / "processed"
        / "video"
        / track_key(release, track)
        / "analysis"
        / "cache"
        / "alignment"
        / "transcriptions"
        / f"{cache_key}.json"
    )


def load_transcript(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    document: Any,
) -> dict[str, Any] | None:
    """The cached Whisper transcript behind an aligned document.

    An AI vocal take is the artifact of record — it does not always follow the
    submitted lyric — so the editor shows what was actually sung, with times,
    beside the canonical lines. Returns None when no transcript is on disk.
    """
    metadata = getattr(document, "alignment", None) if document is not None else None
    cache_key = getattr(metadata, "transcription_cache_key", None)
    if not cache_key:
        return None
    path = transcript_path(root, release, track, str(cache_key))
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    response = payload.get("response")
    if not isinstance(response, Mapping):
        return None

    words = [
        {
            "start": float(word["start"]),
            "end": float(word["end"]),
            "text": str(word.get("word", "")).strip(),
        }
        for word in response.get("words") or []
        if _is_number(word.get("start")) and _is_number(word.get("end"))
    ]
    segments = []
    for segment in response.get("segments") or []:
        if not (_is_number(segment.get("start")) and _is_number(segment.get("end"))):
            continue
        start = float(segment["start"])
        end = float(segment["end"])
        segments.append(
            {
                "start": start,
                "end": end,
                "text": str(segment.get("text", "")).strip(),
                "words": [word for word in words if start <= word["start"] <= end],
            }
        )
    if not segments and words:
        segments = [
            {
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": " ".join(word["text"] for word in words),
                "words": words,
            }
        ]
    if not segments:
        return None
    return {
        "path": path.relative_to(root).as_posix(),
        "segments": segments,
        "word_count": len(words),
    }


def _is_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


# Alignment warnings are emitted as "<section id> line <n> <detail>"; anything
# that does not fit that shape is a document-level warning.
_LINE_WARNING = re.compile(r"^(?P<section>\S+) line (?P<line>\d+) (?P<detail>.+)$")


def _warnings(document: Any) -> dict[str, Any]:
    """Split alignment warnings into per-line notes and document-level ones.

    Line notes are keyed "<section id>:<zero-based line index>" to match the
    line_key the editor already posts back.
    """
    metadata = getattr(document, "alignment", None) if document is not None else None
    raw = list(getattr(metadata, "warnings", None) or [])
    lines: dict[str, list[str]] = {}
    general: list[str] = []
    for warning in raw:
        match = _LINE_WARNING.match(str(warning))
        if not match:
            general.append(str(warning))
            continue
        index = int(match.group("line")) - 1
        if index < 0:
            general.append(str(warning))
            continue
        lines.setdefault(f"{match.group('section')}:{index}", []).append(
            match.group("detail")
        )
    return {"lines": lines, "general": general, "total": len(raw)}


# A lyric-source line that is a bare "[Chorus]" marker structures the document
# rather than being sung, and never appears as a cue.
_SECTION_MARKER = re.compile(r"^\[[^]]+]$")


def release_path(root: Path, release: dict[str, Any]) -> Path:
    return root / "content" / "releases" / f"{release.get('slug')}.yaml"


def _lyric_line_numbers(text: str) -> list[int]:
    """Indices into text.splitlines() that carry a sung line, in order."""
    return [
        index
        for index, line in enumerate(text.splitlines())
        if line.strip() and not _SECTION_MARKER.match(line.strip())
    ]


def lyric_source(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    document: Any,
) -> dict[str, Any]:
    """Map each aligned cue back to the lyric line it came from.

    The video reads `lyrics_raw` (section markers and all) while the public
    pages render `lyrics_text`; the two hold the same sung lines in the same
    order, so one edit maintains both. A cue is only editable when its section
    still maps one-to-one — display segmentation splits an over-wide line into
    several cues, and writing a fragment back would corrupt the source.
    """
    blocked: str | None = None
    if track.get("lyrics_source"):
        blocked = (
            "lyrics_source points this track at an external lyric file, "
            "so lyric text is edited there"
        )
    raw = str(track.get("lyrics_raw") or "")
    text = str(track.get("lyrics_text") or "")
    if not blocked and not (raw or text):
        blocked = "this track has no lyrics_raw or lyrics_text to write back to"
    if blocked or document is None:
        return {"editable": False, "reason": blocked, "lines": {}, "sections": {}}

    from mrp.video.workspace import (
        MRPVideoAdapterError,
        _lyrics_from_text,
        track_structure_labels,
    )

    try:
        structured, _directions = _lyrics_from_text(
            raw or text,
            instrumental=bool(track.get("instrumental", False)),
            extra_labels=track_structure_labels(track),
        )
    except MRPVideoAdapterError as exc:
        return {"editable": False, "reason": str(exc), "lines": {}, "sections": {}}

    offsets: dict[str, int] = {}
    counts: dict[str, int] = {}
    cursor = 0
    for section in structured.sections:
        offsets[section.id] = cursor
        counts[section.id] = len(section.lines)
        cursor += len(section.lines)

    lines: dict[str, int] = {}
    sections: dict[str, bool] = {}
    for section in document.sections:
        matches = section.id in counts and counts[section.id] == len(section.lines)
        sections[section.id] = matches
        if not matches:
            continue
        for line_index in range(len(section.lines)):
            lines[f"{section.id}:{line_index}"] = offsets[section.id] + line_index
    return {
        "editable": bool(lines),
        "reason": None if lines else "no section maps one-to-one to the lyric source",
        "lines": lines,
        "sections": sections,
    }


def apply_lyric_text(track: dict[str, Any], changes: Mapping[int, str]) -> int:
    """Fold corrected sung lines into a track's lyrics_raw and lyrics_text.

    Mutates the track in place and returns how many lines changed; the caller
    owns writing the release record, so the edit rides the normal validate-then
    -serialize path rather than a second write of the same file. Both fields
    carry the same sung lines in the same order, so a change at lyric index n
    applies to line n of each. Section markers and blank lines are untouched.
    """
    if not changes:
        return 0
    for field in ("lyrics_raw", "lyrics_text"):
        value = track.get(field)
        if not value:
            continue
        source_lines = str(value).splitlines()
        numbers = _lyric_line_numbers(str(value))
        for index, replacement in changes.items():
            if index >= len(numbers):
                raise TimingEditorError(
                    f"{field} holds {len(numbers)} lyric lines but the aligned "
                    f"document edits line {index + 1}; re-run alignment to resync"
                )
            source_lines[numbers[index]] = replacement
        track[field] = "\n".join(source_lines)
    return len(changes)


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


def _gaps(document: Any, duration: float | None) -> list[dict[str, Any]]:
    """Uncovered spans in the timeline: the lead-in, holes between sections,
    and the tail after the last section (only when the master duration is
    known). Spans under ~50ms are ignored as rounding noise."""
    eps = 0.05
    spans: list[dict[str, Any]] = []
    sections = document.sections
    if sections and sections[0].start > eps:
        spans.append({"start": 0.0, "end": sections[0].start, "kind": "lead"})
    for before, after in zip(sections, sections[1:]):
        if after.start - before.end > eps:
            spans.append(
                {"start": before.end, "end": after.start, "kind": "mid", "after": before.id}
            )
    if sections and duration is not None and duration - sections[-1].end > eps:
        spans.append(
            {"start": sections[-1].end, "end": duration, "kind": "tail", "after": sections[-1].id}
        )
    return spans


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
            "gaps": [],
            "warnings": {"lines": {}, "general": [], "total": 0},
            "transcript": None,
            "directions": lyric_directions(root, release, track),
            "lyric_source": {
                "editable": False,
                "reason": None,
                "lines": {},
                "sections": {},
            },
        }
    document = _load(path)
    duration = _master_duration(root, release, track)
    return {
        "exists": True,
        "path": relative,
        "document": document,
        "summary": _summary(document),
        "master_duration": duration,
        "gaps": _gaps(document, duration),
        "warnings": _warnings(document),
        "transcript": load_transcript(root, release, track, document),
        "directions": lyric_directions(root, release, track),
        "lyric_source": lyric_source(root, release, track, document),
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

    # Lyric text is optional: an older form, or a track whose source cannot be
    # mapped back, posts timing only. The route whitelists the field name, so
    # "absent" arrives as an empty list rather than a missing key.
    line_texts = _field(fields, "line_text", line_count) if fields.get("line_text") else None
    source = lyric_source(root, release, track, original)
    text_changes: dict[int, str] = {}
    if line_texts is not None:
        original_texts = [
            line.text for section in original.sections for line in section.lines
        ]
        for offset, (key, value) in enumerate(zip(line_keys, line_texts, strict=True)):
            replacement = value.strip()
            if replacement == original_texts[offset]:
                continue
            if not replacement:
                raise TimingEditorError(f"line {key} cannot be blank")
            if key not in source["lines"]:
                raise TimingEditorError(
                    f"line {key} cannot be edited here: "
                    f"{source['reason'] or 'its section does not map to the lyric source'}"
                )
            text_changes[source["lines"][key]] = replacement

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
            if line_texts is not None:
                replacement = line_texts[line_offset].strip()
                if replacement:
                    line["text"] = replacement
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
        "text_changes": text_changes,
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
    """Validate and atomically replace one track's versioned timing artifact.

    Lyric-text edits are folded into the passed track dict; persisting the
    release record is the caller's job, since it owns the validate-and-
    serialize path for that file.
    """
    result = validate_timing(root, release, track, fields)
    result["lyrics_changed"] = apply_lyric_text(track, result["text_changes"])
    persist_timing(root, release, track, result["document"])
    return result


def _slugify(value: str) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in value.casefold())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "section"


def _unique_section_id(existing: Sequence[str], base: str) -> str:
    if base not in existing:
        return base
    index = 2
    while f"{base}-{index}" in existing:
        index += 1
    return f"{base}-{index}"


def _rebuild(payload: dict[str, Any]) -> Any:
    """Re-validate an edited aligned-lyrics payload, surfacing field errors."""
    from mrp.video.project import AlignedLyrics

    try:
        return AlignedLyrics.model_validate(payload)
    except ValidationError as exc:
        problems = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            problems.append(f"{location}: {error['msg']}")
        raise TimingEditorError(*problems) from exc


def add_section(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    *,
    section_type: str,
    start: str,
    end: str,
    label: str | None = None,
) -> dict[str, Any]:
    """Insert a manually-defined (typically instrumental) scene into a gap.

    Sections are kept time-ordered and must not overlap an existing one; the
    new scene carries no lyric cues, so any ``type`` is allowed."""
    path = timing_path(root, release, track)
    if not path.is_file():
        raise TimingEditorError("aligned lyrics do not exist; run alignment first")
    stype = section_type.strip()
    if not stype:
        raise TimingEditorError("scene type is required")
    label_text = (label or "").strip()
    start_seconds = _number(start, "scene start")
    end_seconds = _number(end, "scene end")
    if end_seconds <= start_seconds:
        raise TimingEditorError("scene end must be greater than scene start")

    duration = _master_duration(root, release, track)
    if duration is not None and end_seconds > duration + 0.001:
        raise TimingEditorError(
            f"scene ends at {end_seconds:.3f}s, after the {duration:.3f}s master"
        )

    original = _load(path)
    for section in original.sections:
        if start_seconds < section.end - 1e-6 and end_seconds > section.start + 1e-6:
            raise TimingEditorError(
                f"scene {start_seconds:.3f}–{end_seconds:.3f}s overlaps section "
                f"{section.id} ({section.start:.3f}–{section.end:.3f}s)"
            )

    payload = original.model_dump(mode="json", exclude_none=True)
    new_id = _unique_section_id(
        [section.id for section in original.sections],
        _slugify(label_text or stype),
    )
    new_section: dict[str, Any] = {
        "id": new_id,
        "type": stype,
        "start": start_seconds,
        "end": end_seconds,
        "reviewed": True,
        "lines": [],
    }
    if label_text:
        new_section["label"] = label_text
    payload["sections"] = sorted(
        [*payload["sections"], new_section], key=lambda item: item["start"]
    )

    updated = _rebuild(payload)
    persist_timing(root, release, track, updated)
    return {"summary": _summary(updated), "section_id": new_id}


def insert_lyric_line(
    track: dict[str, Any],
    text: str,
    *,
    after: int | None = None,
    before: int | None = None,
) -> None:
    """Splice a new sung line into lyrics_raw and lyrics_text.

    Anchored to a neighbouring lyric line rather than to an absolute offset, so
    a line appended to the end of a section lands before the next section's
    ``[Marker]`` in lyrics_raw instead of after it.
    """
    for field in ("lyrics_raw", "lyrics_text"):
        value = track.get(field)
        if not value:
            continue
        lines = str(value).splitlines()
        numbers = _lyric_line_numbers(str(value))
        if after is not None:
            if after >= len(numbers):
                raise TimingEditorError(
                    f"{field} holds {len(numbers)} lyric lines; cannot anchor a new "
                    f"cue after line {after + 1}. Re-run alignment to resync."
                )
            position = numbers[after] + 1
        elif before is not None:
            if before >= len(numbers):
                raise TimingEditorError(
                    f"{field} holds {len(numbers)} lyric lines; cannot anchor a new "
                    f"cue before line {before + 1}. Re-run alignment to resync."
                )
            position = numbers[before]
        else:
            position = len(lines)
        lines.insert(position, text)
        track[field] = "\n".join(lines)


def add_line(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
    *,
    section_id: str,
    text: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Add a sung cue the aligner never produced, to document and lyric alike.

    A take sings things the submitted lyric never had — an "oooh", an ad-lib —
    and Musixmatch expects those in the published lyric, so a new cue lands in
    lyrics_raw and lyrics_text as well as the video document. Its place within
    the section follows from its start time, so the written order can never
    disagree with the timeline.

    Mutates the track in place; the caller persists the release record.
    """
    path = timing_path(root, release, track)
    if not path.is_file():
        raise TimingEditorError("aligned lyrics do not exist; run alignment first")
    words = " ".join(str(text).split())
    if not words:
        raise TimingEditorError("lyric text is required")
    if _SECTION_MARKER.match(words):
        raise TimingEditorError("a cue cannot be a [section] marker")
    start_seconds = _number(start, "cue start")
    end_seconds = _number(end, "cue end")
    if end_seconds <= start_seconds:
        raise TimingEditorError("cue end must be greater than cue start")

    original = _load(path)
    index = next(
        (
            position
            for position, section in enumerate(original.sections)
            if section.id == section_id
        ),
        None,
    )
    if index is None:
        raise TimingEditorError(f"unknown section {section_id}")
    section = original.sections[index]
    if not section.lines:
        raise TimingEditorError(
            f"section {section_id} has no existing cue to anchor against; add the "
            "line to the track lyric and re-run alignment"
        )

    source = lyric_source(root, release, track, original)
    if f"{section_id}:0" not in source["lines"]:
        raise TimingEditorError(
            f"section {section_id} cannot take a new cue: "
            f"{source['reason'] or 'it does not map one-to-one to the lyric source'}"
        )

    if start_seconds < section.start - 1e-6 or end_seconds > section.end + 1e-6:
        raise TimingEditorError(
            f"cue {start_seconds:.3f}-{end_seconds:.3f}s falls outside section "
            f"{section_id} ({section.start:.3f}-{section.end:.3f}s)"
        )
    for existing in section.lines:
        if start_seconds < existing.end - 1e-6 and end_seconds > existing.start + 1e-6:
            raise TimingEditorError(
                f"cue {start_seconds:.3f}-{end_seconds:.3f}s overlaps "
                f"'{existing.text}' ({existing.start:.3f}-{existing.end:.3f}s)"
            )

    slot = sum(1 for existing in section.lines if existing.start < start_seconds)
    payload = original.model_dump(mode="json", exclude_none=True)
    payload["sections"][index]["lines"].insert(
        slot,
        {
            "text": words,
            "start": start_seconds,
            "end": end_seconds,
            "reviewed": True,
        },
    )
    updated = _rebuild(payload)

    if slot:
        insert_lyric_line(track, words, after=source["lines"][f"{section_id}:{slot - 1}"])
    else:
        insert_lyric_line(track, words, before=source["lines"][f"{section_id}:0"])

    persist_timing(root, release, track, updated)
    return {"summary": _summary(updated), "section_id": section_id, "slot": slot}


def fill_gaps(
    root: Path,
    release: dict[str, Any],
    track: dict[str, Any],
) -> dict[str, Any]:
    """Close timeline holes: add an instrumental intro for the lead-in gap,
    extend each preceding section over mid-song gaps, and stretch the last
    section to the master end. Returns how many gaps were filled (0 = no-op,
    nothing written)."""
    path = timing_path(root, release, track)
    if not path.is_file():
        raise TimingEditorError("aligned lyrics do not exist; run alignment first")
    original = _load(path)
    payload = original.model_dump(mode="json", exclude_none=True)
    sections = payload["sections"]
    duration = _master_duration(root, release, track)
    eps = 0.05
    filled = 0

    if sections and sections[0]["start"] > eps:
        intro_id = _unique_section_id([s["id"] for s in sections], "intro")
        sections.insert(
            0,
            {
                "id": intro_id,
                "type": "instrumental",
                "start": 0.0,
                "end": round(sections[0]["start"], 6),
                "reviewed": True,
                "lines": [],
            },
        )
        filled += 1

    for before, after in zip(sections, sections[1:]):
        if after["start"] - before["end"] > eps:
            before["end"] = after["start"]
            filled += 1

    if duration is not None and sections and duration - sections[-1]["end"] > eps:
        sections[-1]["end"] = round(duration, 6)
        filled += 1

    if filled == 0:
        return {"summary": _summary(original), "filled": 0}

    updated = _rebuild(payload)
    persist_timing(root, release, track, updated)
    return {"summary": _summary(updated), "filled": filled}
