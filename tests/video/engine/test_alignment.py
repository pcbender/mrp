import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import soundfile as sf
import yaml
from typer.testing import CliRunner

from mrp.video.alignment import (
    SpirophonicAlignmentError,
    TranscriptionResult,
    TranscriptWord,
    _carry_manual_sections,
    align_lyrics_document,
    align_project,
    align_token_sequences,
    tokenize_text,
    transcribe_vocals,
)
from mrp.video.cli import app
from mrp.video.project import (
    AlignedLyricLine,
    AlignedLyricSection,
    AlignmentConfig,
    LyricLine,
    LyricSection,
    StructuredLyrics,
    load_aligned_lyrics,
)

runner = CliRunner()
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


class _FakeTranscriptions:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(
            {key: value for key, value in kwargs.items() if key != "file"}
        )
        return self.response


class _FakeOpenAI:
    def __init__(self, response: dict[str, Any]) -> None:
        self.transcriptions = _FakeTranscriptions(response)
        self.audio = SimpleNamespace(transcriptions=self.transcriptions)


def _response() -> dict[str, Any]:
    return {
        "text": "A generated fixture Second line",
        "duration": 2.0,
        "words": [
            {"word": "A", "start": 0.2, "end": 0.32},
            {"word": "generated", "start": 0.36, "end": 0.58},
            {"word": "fixture", "start": 0.62, "end": 0.88},
            {"word": "Second", "start": 1.05, "end": 1.28},
            {"word": "line", "start": 1.32, "end": 1.55},
        ],
        "segments": [
            {
                "text": "A generated fixture Second line",
                "start": 0.2,
                "end": 1.55,
                "avg_logprob": -0.1,
                "no_speech_prob": 0.01,
            }
        ],
    }


def _transcription(words: list[TranscriptWord]) -> TranscriptionResult:
    return TranscriptionResult(
        text=" ".join(word.word for word in words),
        duration=6,
        words=tuple(words),
        segments=(),
        cache_key="fixture-key",
        cache_path=Path("transcription.json"),
        cache_hit=True,
        vocals_hash="fixture-hash",
    )


def _signal(sample_rate: int, duration: float) -> np.ndarray:
    times = np.arange(round(sample_rate * duration)) / sample_rate
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 2 * times)
    signal = 0.2 * envelope * np.sin(2 * np.pi * 220 * times)
    return np.asarray(signal, dtype=np.float32)


def _write_alignment_project(root: Path) -> Path:
    project = {
        "version": 1,
        "title": "Alignment Fixture",
        "audio": {
            "master": "audio/master.wav",
            "stems": {"vocals": "audio/vocals.wav"},
        },
        "lyrics": {
            "source": "lyrics.yaml",
            "aligned": "build/lyrics.aligned.yaml",
            "language": "en",
        },
        "cards": {
            "opening": {"file": "cards/opening.jpg", "duration": 1},
            "closing": {"file": "cards/closing.jpg", "duration": 1},
        },
        "text": {"font": "assets/font.ttf"},
        "analysis": {
            "sample_rate": 8000,
            "frame_length": 512,
            "hop_length": 128,
            "low_cutoff_hz": 200,
            "high_cutoff_hz": 1500,
            "attack_seconds": 0.02,
            "release_seconds": 0.1,
            "cache_dir": "build/test-analysis",
        },
        "alignment": {"cache_dir": "build/test-alignment"},
    }
    for relative in ("cards/opening.jpg", "cards/closing.jpg"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    font = root / "assets" / "font.ttf"
    font.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FONT_PATH, font)
    (root / "lyrics.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sections": [
                    {
                        "id": "verse_1",
                        "type": "verse",
                        "lines": [
                            {"text": "A generated fixture"},
                            {"text": "Second line"},
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    audio_dir = root / "audio"
    audio_dir.mkdir()
    sf.write(audio_dir / "master.wav", _signal(8000, 2), 8000)
    sf.write(audio_dir / "vocals.wav", _signal(16000, 2), 16000)
    manifest = root / "project.yaml"
    manifest.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")
    return manifest


def test_sequence_alignment_keeps_repeated_words_in_performance_order() -> None:
    canonical = tokenize_text("We rise, we rise")
    transcript = tokenize_text("we rise tonight we rise")

    matches = align_token_sequences(canonical, transcript, min_similarity=0.72)

    assert [match.transcript_index if match else None for match in matches] == [
        0,
        1,
        3,
        4,
    ]


def test_line_alignment_preserves_canonical_text_and_instrumental_window() -> None:
    lyrics = StructuredLyrics(
        version=1,
        sections=[
            LyricSection(
                id="verse",
                type="verse",
                lines=[LyricLine(text="Hello, WORLD!")],
            ),
            LyricSection(id="break", type="instrumental", lines=[]),
            LyricSection(
                id="chorus",
                type="chorus",
                lines=[LyricLine(text="Sing again")],
            ),
        ],
    )
    transcription = _transcription(
        [
            TranscriptWord("hello", 0.5, 0.8),
            TranscriptWord("world", 0.9, 1.2),
            TranscriptWord("sing", 4.0, 4.2),
            TranscriptWord("again", 4.3, 4.6),
        ]
    )

    aligned, warnings = align_lyrics_document(
        lyrics,
        transcription,
        source=Path("lyrics.yaml"),
        duration=6,
        config=AlignmentConfig(),
    )

    assert warnings == ()
    assert aligned.sections[0].lines[0].text == "Hello, WORLD!"
    assert aligned.sections[0].lines[0].status == "matched"
    assert aligned.sections[1].start == pytest.approx(1.2)
    assert aligned.sections[1].end == pytest.approx(4.0)
    assert aligned.sections[2].lines[0].text == "Sing again"


def test_unmatched_line_gets_editable_timing_and_review_warning() -> None:
    lyrics = StructuredLyrics(
        version=1,
        sections=[
            LyricSection(
                id="verse",
                type="verse",
                lines=[
                    LyricLine(text="Hello"),
                    LyricLine(text="Missing words"),
                    LyricLine(text="Goodbye"),
                ],
            )
        ],
    )
    transcription = _transcription(
        [
            TranscriptWord("hello", 0.5, 1.0),
            TranscriptWord("goodbye", 3.0, 3.5),
        ]
    )

    aligned, warnings = align_lyrics_document(
        lyrics,
        transcription,
        source=Path("lyrics.yaml"),
        duration=4,
        config=AlignmentConfig(),
    )

    missing = aligned.sections[0].lines[1]
    assert (missing.start, missing.end) == pytest.approx((1.0, 3.0))
    assert missing.status == "unmatched"
    assert missing.confidence == 0
    assert warnings == ("verse line 2 is unmatched (confidence 0.000)",)


def test_collapsed_recognized_line_gets_provisional_manual_timing() -> None:
    lyrics = StructuredLyrics(
        version=1,
        sections=[
            LyricSection(
                id="intro",
                type="verse",
                lines=[LyricLine(text="Before")],
            ),
            LyricSection(
                id="verse",
                type="verse",
                lines=[
                    LyricLine(text="The wind blows cold again"),
                    LyricLine(text="Memories warming me"),
                ],
            ),
        ],
    )
    transcription = _transcription(
        [
            TranscriptWord("before", 1.0, 2.0),
            TranscriptWord("the", 5.0, 5.1),
            TranscriptWord("wind", 5.0, 5.2),
            TranscriptWord("blows", 5.0, 5.3),
            TranscriptWord("cold", 5.0, 5.4),
            TranscriptWord("again", 5.0, 6.0),
            TranscriptWord("memories", 5.0, 6.5),
            TranscriptWord("warming", 6.6, 6.8),
            TranscriptWord("me", 6.9, 7.2),
        ]
    )

    aligned, warnings = align_lyrics_document(
        lyrics,
        transcription,
        source=Path("lyrics.yaml"),
        duration=8,
        config=AlignmentConfig(),
    )

    provisional = aligned.sections[1].lines[0]
    following = aligned.sections[1].lines[1]
    assert (provisional.start, provisional.end) == pytest.approx((2.0, 5.0))
    assert provisional.status == "unmatched"
    assert provisional.confidence == 0
    assert following.start == pytest.approx(5.0)
    assert warnings == (
        "verse line 1 received a provisional 3.000s timing window "
        "and requires manual review",
    )


def test_stranded_lines_borrow_a_window_instead_of_failing_alignment() -> None:
    """An AI vocal take can sing a late line early, stranding the lines between.

    The document orders "Stranded one/two" before "After", but the take sings
    "after" immediately when "Before" ends, leaving a zero-width gap. Alignment
    must still produce an editable document rather than raising.
    """
    lyrics = StructuredLyrics(
        version=1,
        sections=[
            LyricSection(
                id="verse",
                type="verse",
                lines=[
                    LyricLine(text="Before"),
                    LyricLine(text="Stranded one"),
                    LyricLine(text="Stranded two"),
                    LyricLine(text="After"),
                ],
            )
        ],
    )
    transcription = _transcription(
        [
            TranscriptWord("before", 1.0, 2.0),
            TranscriptWord("after", 2.0, 3.0),
        ]
    )

    aligned, warnings = align_lyrics_document(
        lyrics,
        transcription,
        source=Path("lyrics.yaml"),
        duration=4,
        config=AlignmentConfig(),
    )

    lines = aligned.sections[0].lines
    # Each neighbour lends half of the 0.5s the two stranded lines need.
    assert (lines[1].start, lines[1].end) == pytest.approx((1.75, 2.0))
    assert (lines[2].start, lines[2].end) == pytest.approx((2.0, 2.25))
    assert lines[1].status == "unmatched"
    assert lines[2].status == "unmatched"
    # The recognized neighbours give up only the borrowed sliver.
    assert lines[0].end == pytest.approx(1.75)
    assert lines[3].start == pytest.approx(2.25)
    assert warnings == (
        "verse line 2 has no recognized audio window — the surrounding cues are "
        "adjacent, so it borrowed a 0.250s window and requires manual timing",
        "verse line 3 has no recognized audio window — the surrounding cues are "
        "adjacent, so it borrowed a 0.250s window and requires manual timing",
    )


def test_stranded_run_keeps_every_line_ordered_and_positive() -> None:
    """A long stranded run stays monotonic: the timing editor needs valid spans."""
    lyrics = StructuredLyrics(
        version=1,
        sections=[
            LyricSection(
                id="verse",
                type="verse",
                lines=[LyricLine(text="Before")]
                + [LyricLine(text=f"Stranded {index}") for index in range(7)]
                + [LyricLine(text="After")],
            )
        ],
    )
    transcription = _transcription(
        [
            TranscriptWord("before", 1.0, 2.0),
            TranscriptWord("after", 2.0, 3.0),
        ]
    )

    aligned, warnings = align_lyrics_document(
        lyrics,
        transcription,
        source=Path("lyrics.yaml"),
        duration=4,
        config=AlignmentConfig(),
    )

    lines = aligned.sections[0].lines
    for line in lines:
        assert line.end > line.start
    for current, following in zip(lines, lines[1:], strict=False):
        assert current.end <= following.start + 1e-9
    assert all(line.status == "unmatched" for line in lines[1:8])
    assert len(warnings) == 7


def test_stranded_lines_still_fail_when_no_neighbour_can_lend() -> None:
    from mrp.video.alignment import _borrow_stranded_window, _LineDraft

    def _draft(start: float | None, end: float | None) -> _LineDraft:
        return _LineDraft(
            section_index=0,
            line_index=0,
            text="line",
            token_count=1,
            start=start,
            end=end,
            confidence=0,
            status="matched" if start is not None else "unmatched",
        )

    # Both neighbours are zero-width, so there is nothing to borrow.
    drafts = [_draft(2.0, 2.0), _draft(None, None), _draft(2.0, 2.0)]
    assert _borrow_stranded_window(drafts, 1, 2, 2.0, 2.0, 4.0) is None


def test_transcription_adapter_caches_word_timestamps(tmp_path: Path) -> None:
    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"small fixture")
    client = _FakeOpenAI(_response())
    config = AlignmentConfig()

    first = transcribe_vocals(
        vocals,
        language="en",
        cache_dir=tmp_path / "cache",
        config=config,
        client=client,
    )
    second = transcribe_vocals(
        vocals,
        language="en",
        cache_dir=tmp_path / "cache",
        config=config,
        client=client,
    )

    assert not first.cache_hit
    assert second.cache_hit
    assert first.cache_path.is_file()
    assert len(client.transcriptions.calls) == 1
    assert client.transcriptions.calls[0] == {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities": ["word", "segment"],
        "language": "en",
        "temperature": 0,
    }
    assert second.words == first.words


def test_transcription_adapter_normalizes_real_world_timestamp_edges(
    tmp_path: Path,
) -> None:
    vocals = tmp_path / "vocals.wav"
    vocals.write_bytes(b"small fixture")
    response = _response()
    response["words"] = [
        {"word": "A", "start": -0.02, "end": 0.0},
        {"word": "generated", "start": 0.2, "end": 0.2},
        {"word": "fixture", "start": 0.19, "end": 0.3},
    ]
    response["segments"][0]["end"] = response["segments"][0]["start"]
    client = _FakeOpenAI(response)

    result = transcribe_vocals(
        vocals,
        language="en",
        cache_dir=tmp_path / "cache",
        config=AlignmentConfig(),
        client=client,
    )

    assert [word.start for word in result.words] == pytest.approx([0.0, 0.2, 0.2])
    assert [word.end for word in result.words] == pytest.approx([0.01, 0.21, 0.3])
    assert result.warnings == (
        "normalized Whisper word timestamps (1 negative starts, "
        "1 regressing starts, 2 nonpositive durations)",
        "normalized Whisper segment timestamps (0 negative starts, "
        "1 nonpositive durations)",
    )
    assert result.segments[0].end == pytest.approx(result.segments[0].start + 0.01)
    assert len(list((tmp_path / "cache" / "transcriptions").glob("*.raw.json"))) == 1


def test_project_alignment_is_safe_editable_and_cache_first(tmp_path: Path) -> None:
    manifest = _write_alignment_project(tmp_path)
    client = _FakeOpenAI(_response())

    first = align_project(manifest, client=client)

    assert not first.transcription.cache_hit
    assert first.output_path.is_file()
    saved = load_aligned_lyrics(first.output_path)
    assert [line.text for line in saved.sections[0].lines] == [
        "A generated fixture",
        "Second line",
    ]
    assert saved.alignment is not None
    assert saved.alignment.transcription_cache_key == first.transcription.cache_key
    assert saved.alignment.warnings == []

    with pytest.raises(SpirophonicAlignmentError, match="--force"):
        align_project(manifest, client=client)

    forced = align_project(manifest, force=True, client=client)
    assert forced.transcription.cache_hit
    assert len(client.transcriptions.calls) == 1

    result = runner.invoke(app, ["align", str(manifest), "--force", "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["transcription_cache_hit"] is True
    assert summary["status_counts"] == {
        "matched": 2,
        "uncertain": 0,
        "unmatched": 0,
    }


def _append_manual_section(
    path: Path, section_id: str, start: float, end: float
) -> None:
    """Stage a hand-added instrumental the way the admin timing editor does."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["sections"].append(
        {
            "id": section_id,
            "type": "instrumental",
            "label": section_id.replace("-", " ").title(),
            "start": start,
            "end": end,
            "reviewed": True,
            "lines": [],
        }
    )
    document["sections"].sort(key=lambda section: section["start"])
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_realignment_keeps_hand_added_instrumental_sections(tmp_path: Path) -> None:
    """A forced re-align must not silently delete staging it cannot regenerate.

    Sections come from the canonical lyric source, so one carrying no lines has
    nothing to be rebuilt from. Overwriting used to drop them outright, which
    turned deliberate instrumental staging into uncovered gaps.
    """
    manifest = _write_alignment_project(tmp_path)
    client = _FakeOpenAI(_response())
    first = align_project(manifest, client=client)
    sung_end = max(section.end for section in first.aligned.sections)
    _append_manual_section(first.output_path, "outro", sung_end, sung_end + 0.4)

    rerun = align_project(manifest, force=True, client=client)

    carried = {section.id: section for section in rerun.aligned.sections}
    assert "outro" in carried, "hand-added section was dropped by re-alignment"
    assert carried["outro"].start == pytest.approx(sung_end)
    assert carried["outro"].end == pytest.approx(sung_end + 0.4)
    # The carry survives the round trip to disk, not just the in-memory run.
    assert "outro" in {
        section.id for section in load_aligned_lyrics(rerun.output_path).sections
    }
    assert not any("outro" in warning for warning in rerun.warnings)


def test_realignment_drops_a_manual_section_that_now_covers_sung_time(
    tmp_path: Path,
) -> None:
    """Alignment owns any span it placed lyrics in, and warns rather than failing.

    Exercised against the carry helper directly: reproducing the collision
    end-to-end would mean hand-editing sung boundaries that re-alignment
    immediately recomputes, which tests the fixture rather than the rule.
    """
    previous = tmp_path / "lyrics.aligned.yaml"
    previous.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "source": "lyrics.yaml",
                "sections": [
                    {
                        "id": "verse_1",
                        "type": "verse",
                        "start": 0.0,
                        "end": 1.0,
                        "lines": [
                            {"text": "A generated fixture", "start": 0.0, "end": 1.0}
                        ],
                    },
                    {
                        "id": "overlap",
                        "type": "instrumental",
                        "start": 4.0,
                        "end": 5.0,
                        "reviewed": True,
                        "lines": [],
                    },
                    # Still clear of the vocal after re-alignment, so it returns.
                    {
                        "id": "kept",
                        "type": "instrumental",
                        "start": 5.0,
                        "end": 6.0,
                        "reviewed": True,
                        "lines": [],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    # Re-alignment now stretches the vocal across what "overlap" was staged over.
    rebuilt = [
        AlignedLyricSection(
            id="verse_1",
            type="verse",
            start=0.0,
            end=4.5,
            lines=[AlignedLyricLine(text="A generated fixture", start=0.0, end=4.5)],
        )
    ]

    merged, warnings = _carry_manual_sections(rebuilt, previous)

    assert [section.id for section in merged] == ["verse_1", "kept"]
    assert len(warnings) == 1
    assert "overlap" in warnings[0]
    assert "4.000s–5.000s" in warnings[0]


def test_a_lyric_less_intro_and_outro_take_the_time_around_the_singing() -> None:
    lyrics = StructuredLyrics(
        version=1,
        sections=[
            LyricSection(id="intro", type="intro", lines=[]),
            LyricSection(
                id="verse", type="verse", lines=[LyricLine(text="Hello world")]
            ),
            LyricSection(id="outro", type="outro", lines=[]),
        ],
    )
    transcription = _transcription(
        [TranscriptWord("hello", 2.0, 2.5), TranscriptWord("world", 2.5, 3.0)]
    )

    aligned, _warnings = align_lyrics_document(
        lyrics,
        transcription,
        source=Path("lyrics.yaml"),
        duration=8,
        config=AlignmentConfig(),
    )

    assert [section.id for section in aligned.sections] == ["intro", "verse", "outro"]
    # The intro is the time before the first word, the outro the time after the
    # last, out to the end of the master.
    assert (aligned.sections[0].start, aligned.sections[0].end) == pytest.approx(
        (0.0, 2.0)
    )
    assert (aligned.sections[2].start, aligned.sections[2].end) == pytest.approx(
        (3.0, 8.0)
    )


def test_a_lyric_less_section_with_no_room_is_dropped_not_fatal() -> None:
    """Singing from the first sample leaves an intro nothing to occupy."""
    lyrics = StructuredLyrics(
        version=1,
        sections=[
            LyricSection(id="intro", type="intro", lines=[]),
            LyricSection(
                id="verse", type="verse", lines=[LyricLine(text="Hello world")]
            ),
        ],
    )
    transcription = _transcription(
        [TranscriptWord("hello", 0.0, 0.5), TranscriptWord("world", 0.5, 1.0)]
    )

    aligned, _warnings = align_lyrics_document(
        lyrics,
        transcription,
        source=Path("lyrics.yaml"),
        duration=4,
        config=AlignmentConfig(),
    )

    assert [section.id for section in aligned.sections] == ["verse"]
