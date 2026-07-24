import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml

from mrp.video.analysis import FeatureTimeline, analyze_project
from mrp.video.project import (
    AlignedLyricLine,
    AlignedLyrics,
    AlignedLyricSection,
    AlignmentConfig,
    AlignmentMetadata,
    StructuredLyrics,
    load_project_manifest,
    validate_project,
)
from mrp.video.text import SpirophonicTextError, segment_lyrics_for_display

ALIGNMENT_ALGORITHM_VERSION = 1
TRANSCRIPTION_ADAPTER_VERSION = 2
MAX_TRANSCRIPTION_UPLOAD_BYTES = 25_000_000
WORD_TIMESTAMP_EPSILON = 0.01
SUPPORTED_TRANSCRIPTION_SUFFIXES = {
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".ogg",
    ".wav",
    ".webm",
}
ProgressCallback = Callable[[str], None]
_WORD_PATTERN = re.compile(r"[^\W_]+(?:'[^\W_]+)*", flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    word: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    text: str
    start: float
    end: float
    average_log_probability: float | None = None
    no_speech_probability: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    duration: float
    words: tuple[TranscriptWord, ...]
    segments: tuple[TranscriptSegment, ...]
    cache_key: str
    cache_path: Path
    cache_hit: bool
    vocals_hash: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TokenMatch:
    transcript_index: int
    similarity: float


@dataclass(frozen=True, slots=True)
class AlignmentRun:
    aligned: AlignedLyrics
    output_path: Path
    transcription: TranscriptionResult
    warnings: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        status_counts = {"matched": 0, "uncertain": 0, "unmatched": 0}
        for section in self.aligned.sections:
            for line in section.lines:
                if line.status is not None:
                    status_counts[line.status] += 1
        return {
            "output_path": str(self.output_path),
            "transcription_cache_path": str(self.transcription.cache_path),
            "transcription_cache_hit": self.transcription.cache_hit,
            "model": self.aligned.alignment.model if self.aligned.alignment else None,
            "status_counts": status_counts,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class _TimedToken:
    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class _CanonicalLine:
    section_index: int
    line_index: int
    text: str
    tokens: tuple[str, ...]
    token_start: int
    token_end: int


@dataclass(slots=True)
class _LineDraft:
    section_index: int
    line_index: int
    text: str
    token_count: int
    start: float | None
    end: float | None
    confidence: float
    status: Literal["matched", "uncertain", "unmatched"]


class SpirophonicAlignmentError(Exception):
    pass


def tokenize_text(text: str) -> tuple[str, ...]:
    """Normalize text for matching without changing canonical lyric output."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("’", "'").replace("‘", "'")
    return tuple(_WORD_PATTERN.findall(normalized))


def _token_similarity(canonical: str, transcript: str) -> float:
    if canonical == transcript:
        return 1.0
    return SequenceMatcher(None, canonical, transcript, autojunk=False).ratio()


def align_token_sequences(
    canonical_tokens: Sequence[str],
    transcript_tokens: Sequence[str],
    *,
    min_similarity: float,
) -> list[TokenMatch | None]:
    """Globally align canonical and recognized tokens in performance order."""
    canonical_count = len(canonical_tokens)
    transcript_count = len(transcript_tokens)
    gap_penalty = -0.75
    scores = np.empty((canonical_count + 1, transcript_count + 1), dtype=np.float32)
    directions = np.zeros(
        (canonical_count + 1, transcript_count + 1),
        dtype=np.int8,
    )
    scores[0, 0] = 0
    for index in range(1, canonical_count + 1):
        scores[index, 0] = index * gap_penalty
        directions[index, 0] = 2
    for index in range(1, transcript_count + 1):
        scores[0, index] = index * gap_penalty
        directions[0, index] = 3

    for canonical_index, canonical in enumerate(canonical_tokens, start=1):
        for transcript_index, transcript in enumerate(transcript_tokens, start=1):
            similarity = _token_similarity(canonical, transcript)
            match_score = 2 * similarity if similarity >= min_similarity else -2
            diagonal = scores[canonical_index - 1, transcript_index - 1] + match_score
            delete = scores[canonical_index - 1, transcript_index] + gap_penalty
            insert = scores[canonical_index, transcript_index - 1] + gap_penalty
            if diagonal >= delete and diagonal >= insert:
                scores[canonical_index, transcript_index] = diagonal
                directions[canonical_index, transcript_index] = 1
            elif delete >= insert:
                scores[canonical_index, transcript_index] = delete
                directions[canonical_index, transcript_index] = 2
            else:
                scores[canonical_index, transcript_index] = insert
                directions[canonical_index, transcript_index] = 3

    matches: list[TokenMatch | None] = [None] * canonical_count
    canonical_index = canonical_count
    transcript_index = transcript_count
    while canonical_index > 0 or transcript_index > 0:
        direction = directions[canonical_index, transcript_index]
        if direction == 1:
            similarity = _token_similarity(
                canonical_tokens[canonical_index - 1],
                transcript_tokens[transcript_index - 1],
            )
            if similarity >= min_similarity:
                matches[canonical_index - 1] = TokenMatch(
                    transcript_index=transcript_index - 1,
                    similarity=similarity,
                )
            canonical_index -= 1
            transcript_index -= 1
        elif direction == 2:
            canonical_index -= 1
        elif direction == 3:
            transcript_index -= 1
        elif canonical_index > 0:
            canonical_index -= 1
        else:
            transcript_index -= 1
    return matches


def _canonical_lines(
    lyrics: StructuredLyrics,
) -> tuple[list[_CanonicalLine], list[str]]:
    lines: list[_CanonicalLine] = []
    all_tokens: list[str] = []
    for section_index, section in enumerate(lyrics.sections):
        for line_index, line in enumerate(section.lines):
            tokens = tokenize_text(line.text)
            start = len(all_tokens)
            all_tokens.extend(tokens)
            lines.append(
                _CanonicalLine(
                    section_index=section_index,
                    line_index=line_index,
                    text=line.text,
                    tokens=tokens,
                    token_start=start,
                    token_end=len(all_tokens),
                )
            )
    return lines, all_tokens


def _timed_tokens(words: Sequence[TranscriptWord]) -> list[_TimedToken]:
    tokens: list[_TimedToken] = []
    for word in words:
        for token in tokenize_text(word.word):
            tokens.append(_TimedToken(token, word.start, word.end))
    return tokens


def _draft_line_cues(
    canonical_lines: Sequence[_CanonicalLine],
    matches: Sequence[TokenMatch | None],
    transcript_tokens: Sequence[_TimedToken],
    config: AlignmentConfig,
) -> list[_LineDraft]:
    drafts: list[_LineDraft] = []
    for line in canonical_lines:
        line_matches = [
            match
            for match in matches[line.token_start : line.token_end]
            if match is not None
        ]
        if line_matches:
            timed = [
                transcript_tokens[match.transcript_index] for match in line_matches
            ]
            coverage = len(line_matches) / max(1, len(line.tokens))
            average_similarity = sum(match.similarity for match in line_matches) / len(
                line_matches
            )
            confidence = coverage * (0.5 + 0.5 * average_similarity)
            status = (
                "matched"
                if confidence >= config.matched_confidence
                else "uncertain"
            )
            drafts.append(
                _LineDraft(
                    section_index=line.section_index,
                    line_index=line.line_index,
                    text=line.text,
                    token_count=len(line.tokens),
                    start=timed[0].start,
                    end=timed[-1].end,
                    confidence=round(confidence, 6),
                    status=status,
                )
            )
        else:
            drafts.append(
                _LineDraft(
                    section_index=line.section_index,
                    line_index=line.line_index,
                    text=line.text,
                    token_count=len(line.tokens),
                    start=None,
                    end=None,
                    confidence=0,
                    status="unmatched",
                )
            )
    return drafts


def _interpolate_unmatched_lines(
    drafts: list[_LineDraft],
    duration: float,
) -> None:
    index = 0
    while index < len(drafts):
        if drafts[index].start is not None:
            index += 1
            continue
        run_start = index
        while index < len(drafts) and drafts[index].start is None:
            index += 1
        run_end = index
        left = drafts[run_start - 1].end if run_start else 0.0
        right = drafts[run_end].start if run_end < len(drafts) else duration
        if left is None or right is None or right <= left:
            raise SpirophonicAlignmentError(
                "unmatched lyric lines have no positive timing window; "
                "manual timing is required"
            )
        weights = [max(1, draft.token_count) for draft in drafts[run_start:run_end]]
        total_weight = sum(weights)
        cursor = float(left)
        for draft, weight in zip(drafts[run_start:run_end], weights, strict=True):
            line_duration = (right - left) * weight / total_weight
            draft.start = cursor
            draft.end = cursor + line_duration
            cursor = draft.end


def _extend_energy_tail(
    end: float,
    limit: float,
    timeline: FeatureTimeline,
    *,
    activity_threshold: float,
    frame_seconds: float,
) -> float:
    activity = timeline.features.get("vocal_activity")
    if activity is None or limit <= end:
        return end
    index = int(np.searchsorted(timeline.times, end, side="left"))
    extended = end
    found_activity = False
    while index < timeline.frame_count and timeline.times[index] <= limit:
        if activity[index] >= activity_threshold:
            extended = min(limit, float(timeline.times[index]) + frame_seconds / 2)
            found_activity = True
        elif found_activity or timeline.times[index] > end + frame_seconds:
            break
        index += 1
    return extended


def _apply_energy_tails(
    drafts: list[_LineDraft],
    duration: float,
    config: AlignmentConfig,
    timeline: FeatureTimeline | None,
    frame_seconds: float,
) -> None:
    if timeline is None:
        return
    for index, draft in enumerate(drafts):
        if draft.status == "unmatched" or draft.end is None:
            continue
        next_start = (
            drafts[index + 1].start if index + 1 < len(drafts) else duration
        )
        if next_start is None:
            continue
        limit = min(duration, next_start, draft.end + config.max_tail_seconds)
        draft.end = _extend_energy_tail(
            draft.end,
            limit,
            timeline,
            activity_threshold=config.activity_threshold,
            frame_seconds=frame_seconds,
        )


def _provisional_window_seconds(draft: _LineDraft) -> float:
    return min(4.0, max(0.5, draft.token_count * 0.6))


def _bound_line_transitions(
    drafts: list[_LineDraft],
    duration: float,
) -> tuple[_LineDraft, ...]:
    """Prevent overlap and retain collapsed cues as editable manual fallbacks."""
    for current, following in zip(drafts, drafts[1:], strict=False):
        if current.end is None or following.start is None:
            raise SpirophonicAlignmentError(
                "internal error: unresolved lyric timing"
            )
        current.end = min(current.end, following.start)

    repaired: list[_LineDraft] = []
    for index, draft in enumerate(drafts):
        if draft.start is None or draft.end is None:
            raise SpirophonicAlignmentError("internal error: unresolved lyric timing")
        if draft.end > draft.start:
            continue
        anchor = min(duration, max(0.0, draft.start))
        previous_end = drafts[index - 1].end if index else 0.0
        if previous_end is None:
            raise SpirophonicAlignmentError("internal error: unresolved lyric timing")
        target = _provisional_window_seconds(draft)
        left_available = anchor - previous_end
        if left_available > 0:
            draft.start = anchor - min(target, left_available)
            draft.end = anchor
        else:
            following = drafts[index + 1] if index + 1 < len(drafts) else None
            right_limit = following.end if following is not None else duration
            if right_limit is None:
                raise SpirophonicAlignmentError(
                    "internal error: unresolved lyric timing"
                )
            right_available = right_limit - anchor
            if right_available <= 0:
                raise SpirophonicAlignmentError(
                    "recognized lyric timing has no editable fallback window near "
                    f"section {draft.section_index + 1}, "
                    f"line {draft.line_index + 1}"
                )
            width = min(target, right_available)
            if following is not None:
                width = min(width, right_available / 2)
                following.start = anchor + width
            draft.start = anchor
            draft.end = anchor + width
        if draft.end <= draft.start:
            raise SpirophonicAlignmentError(
                "recognized lyric timing has no editable fallback window near "
                f"section {draft.section_index + 1}, line {draft.line_index + 1}"
            )
        draft.confidence = 0
        draft.status = "unmatched"
        repaired.append(draft)
    return tuple(repaired)


def _build_sections(
    lyrics: StructuredLyrics,
    drafts: Sequence[_LineDraft],
    duration: float,
) -> list[AlignedLyricSection]:
    cue_lookup = {
        (draft.section_index, draft.line_index): draft for draft in drafts
    }
    section_bounds: list[tuple[float, float] | None] = []
    section_lines: list[list[AlignedLyricLine]] = []
    for section_index, section in enumerate(lyrics.sections):
        lines: list[AlignedLyricLine] = []
        for line_index, _line in enumerate(section.lines):
            draft = cue_lookup[(section_index, line_index)]
            if draft.start is None or draft.end is None:
                raise SpirophonicAlignmentError(
                    "internal error: unresolved lyric timing"
                )
            lines.append(
                AlignedLyricLine(
                    text=draft.text,
                    start=draft.start,
                    end=draft.end,
                    confidence=draft.confidence,
                    status=draft.status,
                )
            )
        section_lines.append(lines)
        section_bounds.append((lines[0].start, lines[-1].end) if lines else None)

    index = 0
    while index < len(section_bounds):
        if section_bounds[index] is not None:
            index += 1
            continue
        run_start = index
        while index < len(section_bounds) and section_bounds[index] is None:
            index += 1
        run_end = index
        left = section_bounds[run_start - 1][1] if run_start else 0.0
        right = (
            section_bounds[run_end][0]
            if run_end < len(section_bounds)
            else duration
        )
        if right <= left:
            section_ids = ", ".join(
                section.id for section in lyrics.sections[run_start:run_end]
            )
            raise SpirophonicAlignmentError(
                f"empty section timing has no positive window ({section_ids})"
            )
        section_duration = (right - left) / (run_end - run_start)
        for offset, section_index in enumerate(range(run_start, run_end)):
            start = left + offset * section_duration
            section_bounds[section_index] = (start, start + section_duration)

    aligned_sections: list[AlignedLyricSection] = []
    for section, bounds, lines in zip(
        lyrics.sections,
        section_bounds,
        section_lines,
        strict=True,
    ):
        if bounds is None:
            raise SpirophonicAlignmentError("internal error: unresolved section timing")
        aligned_sections.append(
            AlignedLyricSection(
                id=section.id,
                type=section.type,
                label=section.label,
                start=bounds[0],
                end=bounds[1],
                lines=lines,
            )
        )
    return aligned_sections


def align_lyrics_document(
    lyrics: StructuredLyrics,
    transcription: TranscriptionResult,
    *,
    source: Path,
    duration: float,
    config: AlignmentConfig,
    vocal_timeline: FeatureTimeline | None = None,
    frame_seconds: float = 0,
) -> tuple[AlignedLyrics, tuple[str, ...]]:
    """Map timestamped recognized words onto canonical lyric line instances."""
    if duration <= 0:
        raise SpirophonicAlignmentError("master duration must be positive")
    canonical_lines, canonical_tokens = _canonical_lines(lyrics)
    if not canonical_lines:
        raise SpirophonicAlignmentError("structured lyrics contain no lyric lines")
    transcript_tokens = _timed_tokens(transcription.words)
    if not transcript_tokens:
        raise SpirophonicAlignmentError("transcription contains no timed words")
    matches = align_token_sequences(
        canonical_tokens,
        [token.text for token in transcript_tokens],
        min_similarity=config.min_token_similarity,
    )
    drafts = _draft_line_cues(canonical_lines, matches, transcript_tokens, config)
    for draft in drafts:
        if draft.start is not None:
            draft.start = min(duration, max(0, draft.start))
        if draft.end is not None:
            draft.end = min(duration, max(0, draft.end))
    _interpolate_unmatched_lines(drafts, duration)
    _apply_energy_tails(
        drafts,
        duration,
        config,
        vocal_timeline,
        frame_seconds,
    )
    provisional = _bound_line_transitions(drafts, duration)
    sections = _build_sections(lyrics, drafts, duration)
    provisional_ids = {id(draft) for draft in provisional}
    warnings = tuple(
        (
            f"{lyrics.sections[draft.section_index].id} line "
            f"{draft.line_index + 1} received a provisional "
            f"{draft.end - draft.start:.3f}s timing window and requires manual review"
            if id(draft) in provisional_ids
            else f"{lyrics.sections[draft.section_index].id} line "
            f"{draft.line_index + 1} is {draft.status} "
            f"(confidence {draft.confidence:.3f})"
        )
        for draft in drafts
        if draft.status != "matched"
    )
    return (
        AlignedLyrics(version=1, source=source, sections=sections),
        warnings,
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _transcription_key(vocals_hash: str, language: str, model: str) -> str:
    payload = json.dumps(
        {
            "adapter_version": TRANSCRIPTION_ADAPTER_VERSION,
            "vocals_hash": vocals_hash,
            "language": language,
            "model": model,
            "response_format": "verbose_json",
            "timestamp_granularities": ["word", "segment"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _object_to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json"))
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    raise SpirophonicAlignmentError("transcription response has an unsupported shape")


def _parse_transcription_response(
    response: Any,
    *,
    cache_key: str,
    cache_path: Path,
    cache_hit: bool,
    vocals_hash: str,
) -> TranscriptionResult:
    payload = _object_to_mapping(response)
    timestamp_warnings = list(payload.get("timestamp_warnings") or [])
    negative_starts = 0
    regressing_starts = 0
    nonpositive_durations = 0
    parsed_words: list[TranscriptWord] = []
    previous_start = 0.0
    for value in payload.get("words") or []:
        word = _object_to_mapping(value)
        try:
            text = str(word["word"])
            start = float(word["start"])
            end = float(word["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SpirophonicAlignmentError(
                "transcription contains an invalid word timestamp"
            ) from exc
        if not text.strip() or not math.isfinite(start) or not math.isfinite(end):
            raise SpirophonicAlignmentError(
                "transcription contains an invalid word timestamp"
            )
        if start < 0:
            start = 0.0
            negative_starts += 1
        if start < previous_start:
            start = previous_start
            regressing_starts += 1
        if end <= start:
            end = start + WORD_TIMESTAMP_EPSILON
            nonpositive_durations += 1
        parsed_words.append(TranscriptWord(text, start, end))
        previous_start = start
    if not parsed_words:
        raise SpirophonicAlignmentError(
            "transcription response contains no word timestamps"
        )
    if negative_starts or regressing_starts or nonpositive_durations:
        timestamp_warnings.append(
            "normalized Whisper word timestamps "
            f"({negative_starts} negative starts, "
            f"{regressing_starts} regressing starts, "
            f"{nonpositive_durations} nonpositive durations)"
        )

    negative_segment_starts = 0
    nonpositive_segment_durations = 0
    parsed_segments: list[TranscriptSegment] = []
    for value in payload.get("segments") or []:
        segment = _object_to_mapping(value)
        try:
            start = float(segment["start"])
            end = float(segment["end"])
            average_log_probability = (
                float(segment["avg_logprob"])
                if segment.get("avg_logprob") is not None
                else None
            )
            no_speech_probability = (
                float(segment["no_speech_prob"])
                if segment.get("no_speech_prob") is not None
                else None
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SpirophonicAlignmentError(
                "transcription contains an invalid segment timestamp"
            ) from exc
        numeric_values = (
            start,
            end,
            average_log_probability,
            no_speech_probability,
        )
        if any(
            value is not None and not math.isfinite(value) for value in numeric_values
        ):
            raise SpirophonicAlignmentError(
                "transcription contains an invalid segment timestamp"
            )
        if start < 0:
            start = 0.0
            negative_segment_starts += 1
        if end <= start:
            end = start + WORD_TIMESTAMP_EPSILON
            nonpositive_segment_durations += 1
        parsed_segments.append(
            TranscriptSegment(
                text=str(segment.get("text", "")),
                start=start,
                end=end,
                average_log_probability=average_log_probability,
                no_speech_probability=no_speech_probability,
            )
        )
    if negative_segment_starts or nonpositive_segment_durations:
        timestamp_warnings.append(
            "normalized Whisper segment timestamps "
            f"({negative_segment_starts} negative starts, "
            f"{nonpositive_segment_durations} nonpositive durations)"
        )
    duration = float(payload.get("duration") or parsed_words[-1].end)
    if not math.isfinite(duration) or duration <= 0:
        raise SpirophonicAlignmentError("transcription duration must be positive")
    return TranscriptionResult(
        text=str(payload.get("text", "")),
        duration=duration,
        words=tuple(parsed_words),
        segments=tuple(parsed_segments),
        cache_key=cache_key,
        cache_path=cache_path,
        cache_hit=cache_hit,
        vocals_hash=vocals_hash,
        warnings=tuple(timestamp_warnings),
    )


def _transcription_payload(result: TranscriptionResult) -> dict[str, Any]:
    return {
        "version": 1,
        "cache_key": result.cache_key,
        "vocals_hash": result.vocals_hash,
        "response": {
            "text": result.text,
            "duration": result.duration,
            "words": [
                {"word": word.word, "start": word.start, "end": word.end}
                for word in result.words
            ],
            "segments": [
                {
                    "text": segment.text,
                    "start": segment.start,
                    "end": segment.end,
                    "avg_logprob": segment.average_log_probability,
                    "no_speech_prob": segment.no_speech_probability,
                }
                for segment in result.segments
            ],
            "timestamp_warnings": list(result.warnings),
        },
    }


def _load_raw_transcription_cache(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpirophonicAlignmentError(
            f"invalid raw transcription cache {path}: {exc}; use --retranscribe"
        ) from exc
    if not isinstance(payload, dict):
        raise SpirophonicAlignmentError(
            f"invalid raw transcription cache {path}: expected a JSON object; "
            "use --retranscribe"
        )
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_transcription_cache(
    path: Path,
    cache_key: str,
    vocals_hash: str,
) -> TranscriptionResult:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpirophonicAlignmentError(
            f"invalid transcription cache {path}: {exc}; use --retranscribe"
        ) from exc
    if payload.get("version") != 1 or payload.get("cache_key") != cache_key:
        raise SpirophonicAlignmentError(
            f"invalid transcription cache {path}: key mismatch; use --retranscribe"
        )
    return _parse_transcription_response(
        payload.get("response", {}),
        cache_key=cache_key,
        cache_path=path,
        cache_hit=True,
        vocals_hash=vocals_hash,
    )


def _prepare_transcription_upload(
    vocals_path: Path,
    cache_dir: Path,
    vocals_hash: str,
    config: AlignmentConfig,
) -> Path:
    if (
        vocals_path.suffix.casefold() in SUPPORTED_TRANSCRIPTION_SUFFIXES
        and vocals_path.stat().st_size <= MAX_TRANSCRIPTION_UPLOAD_BYTES
    ):
        return vocals_path

    upload_path = cache_dir / "uploads" / f"{vocals_hash}.mp3"
    if (
        upload_path.is_file()
        and upload_path.stat().st_size <= MAX_TRANSCRIPTION_UPLOAD_BYTES
    ):
        return upload_path
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SpirophonicAlignmentError(
            "ffmpeg is required to prepare the vocal stem for transcription"
        )
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = upload_path.with_name(f".{upload_path.name}.{os.getpid()}.tmp")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(vocals_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        f"{config.upload_bitrate_kbps}k",
        "-map_metadata",
        "-1",
        "-f",
        "mp3",
        str(temporary),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        if temporary.stat().st_size > MAX_TRANSCRIPTION_UPLOAD_BYTES:
            raise SpirophonicAlignmentError(
                "prepared vocal upload still exceeds the OpenAI 25 MB limit"
            )
        os.replace(temporary, upload_path)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SpirophonicAlignmentError(
            f"could not prepare vocal stem for transcription: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return upload_path


def _openai_client() -> Any:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SpirophonicAlignmentError(
            "OPENAI_API_KEY is required when no cached transcription exists"
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SpirophonicAlignmentError(
            "OpenAI alignment support is not installed; run "
            "'uv pip install -r requirements-video-align.txt'"
        ) from exc
    return OpenAI()


def transcribe_vocals(
    vocals_path: Path,
    *,
    language: str,
    cache_dir: Path,
    config: AlignmentConfig,
    retranscribe: bool = False,
    client: Any | None = None,
) -> TranscriptionResult:
    """Return cached or newly requested Whisper word and segment timestamps."""
    vocals_hash = _hash_file(vocals_path)
    cache_key = _transcription_key(vocals_hash, language, config.model)
    cache_path = cache_dir / "transcriptions" / f"{cache_key}.json"
    raw_cache_path = cache_path.with_suffix(".raw.json")
    if cache_path.is_file() and not retranscribe:
        return _load_transcription_cache(cache_path, cache_key, vocals_hash)

    if raw_cache_path.is_file() and not retranscribe:
        response: Any = _load_raw_transcription_cache(raw_cache_path)
    else:
        upload_path = _prepare_transcription_upload(
            vocals_path,
            cache_dir,
            vocals_hash,
            config,
        )
        api_client = client or _openai_client()
        try:
            with upload_path.open("rb") as audio_file:
                response = api_client.audio.transcriptions.create(
                    file=audio_file,
                    model=config.model,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                    language=language,
                    temperature=0,
                )
        except Exception as exc:
            raise SpirophonicAlignmentError(
                f"OpenAI transcription failed: {exc}"
            ) from exc
        response = _object_to_mapping(response)
        _write_json_atomic(raw_cache_path, response)
    result = _parse_transcription_response(
        response,
        cache_key=cache_key,
        cache_path=cache_path,
        cache_hit=False,
        vocals_hash=vocals_hash,
    )
    _write_json_atomic(cache_path, _transcription_payload(result))
    return result


def _write_aligned_yaml(path: Path, aligned: AlignedLyrics) -> None:
    payload = aligned.model_dump(mode="json", exclude_none=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def align_project(
    manifest_path: Path,
    *,
    force: bool = False,
    retranscribe: bool = False,
    client: Any | None = None,
    progress: ProgressCallback | None = None,
) -> AlignmentRun:
    """Transcribe vocals, align canonical lines, and safely write aligned YAML."""
    notify = progress or (lambda _message: None)
    manifest = manifest_path.expanduser().resolve()
    project = load_project_manifest(manifest)
    if project.lyrics.aligned is None:
        raise SpirophonicAlignmentError(
            "lyrics.aligned must name the editable aligned lyric artifact"
        )
    output_path = (manifest.parent / project.lyrics.aligned).resolve()
    if output_path.exists() and not force:
        raise SpirophonicAlignmentError(
            f"aligned lyrics already exist: {output_path}; use --force to overwrite"
        )
    vocals_relative = project.audio.stems.get("vocals")
    if vocals_relative is None:
        raise SpirophonicAlignmentError(
            "automatic alignment requires an audio.stems.vocals file"
        )

    notify("Validating project inputs")
    report = validate_project(manifest, validate_aligned=False)
    notify("Loading shared vocal-energy analysis")
    analysis_run = analyze_project(manifest, validate_aligned=False)
    vocals_path = (manifest.parent / vocals_relative).resolve()
    alignment_cache = (manifest.parent / project.alignment.cache_dir).resolve()
    notify("Loading or requesting Whisper timestamps")
    transcription = transcribe_vocals(
        vocals_path,
        language=project.lyrics.language,
        cache_dir=alignment_cache,
        config=project.alignment,
        retranscribe=retranscribe,
        client=client,
    )

    notify("Splitting oversized lyric lines into sequential display cues")
    try:
        display_lyrics, segmentation_warnings = segment_lyrics_for_display(
            report.lyrics,
            font_path=(manifest.parent / project.text.font).resolve(),
            config=project.text,
            video_width=project.video.width,
        )
    except SpirophonicTextError as exc:
        raise SpirophonicAlignmentError(str(exc)) from exc
    notify("Matching canonical lyric lines")
    vocal_timeline = analysis_run.bundle.tracks["vocals"]
    frame_seconds = analysis_run.bundle.hop_length / analysis_run.bundle.sample_rate
    aligned_without_metadata, alignment_warnings = align_lyrics_document(
        display_lyrics,
        transcription,
        source=project.lyrics.source,
        duration=analysis_run.bundle.duration,
        config=project.alignment,
        vocal_timeline=vocal_timeline,
        frame_seconds=frame_seconds,
    )
    warnings = (
        *transcription.warnings,
        *segmentation_warnings,
        *alignment_warnings,
    )
    metadata = AlignmentMetadata(
        model=project.alignment.model,
        transcription_cache_key=transcription.cache_key,
        source_hash=_hash_file((manifest.parent / project.lyrics.source).resolve()),
        vocals_hash=transcription.vocals_hash,
        warnings=list(warnings),
    )
    aligned = AlignedLyrics(
        version=1,
        source=aligned_without_metadata.source,
        alignment=metadata,
        sections=aligned_without_metadata.sections,
    )
    notify("Writing editable aligned lyrics")
    _write_aligned_yaml(output_path, aligned)
    return AlignmentRun(aligned, output_path, transcription, warnings)
