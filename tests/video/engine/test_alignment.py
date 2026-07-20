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
    align_lyrics_document,
    align_project,
    align_token_sequences,
    tokenize_text,
    transcribe_vocals,
)
from mrp.video.cli import app
from mrp.video.project import (
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
