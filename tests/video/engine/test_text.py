from pathlib import Path

import numpy as np
import pytest

from mrp.video.project import (
    LyricLine,
    LyricSection,
    StructuredLyrics,
    TextConfig,
)
from mrp.video.text import (
    LyricCue,
    SpirophonicTextError,
    draw_lyric_overlay,
    segment_lyrics_for_display,
    split_lyric_text,
)

FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


@pytest.mark.skipif(not FONT_PATH.is_file(), reason="target Ubuntu font unavailable")
def test_oversized_line_splits_at_natural_phrase_boundary() -> None:
    fragments = split_lyric_text(
        "Hold on, we're almost home",
        font_path=FONT_PATH,
        size=60,
        maximum_width=620,
    )

    assert fragments == ("Hold on,", "we're almost home")


@pytest.mark.skipif(not FONT_PATH.is_file(), reason="target Ubuntu font unavailable")
def test_segmentation_preserves_source_and_reports_sequential_cues() -> None:
    lyrics = StructuredLyrics(
        version=1,
        sections=[
            LyricSection(
                id="verse",
                type="verse",
                lines=[LyricLine(text="Hold on, we're almost home")],
            )
        ],
    )
    config = TextConfig(
        font=FONT_PATH,
        size=60,
        maximum_width_fraction=0.33,
    )

    segmented, warnings = segment_lyrics_for_display(
        lyrics,
        font_path=FONT_PATH,
        config=config,
        video_width=1920,
    )

    assert lyrics.sections[0].lines[0].text == "Hold on, we're almost home"
    assert [line.text for line in segmented.sections[0].lines] == [
        "Hold on,",
        "we're almost home",
    ]
    assert warnings == ("verse line 1 split into 2 sequential display cues",)


@pytest.mark.skipif(not FONT_PATH.is_file(), reason="target Ubuntu font unavailable")
def test_fixed_size_renderer_rejects_unsplit_line() -> None:
    frame = np.full((1080, 1920, 3), (16, 16, 20), dtype=np.uint8)
    config = TextConfig(
        font=FONT_PATH,
        size=60,
        maximum_width_fraction=0.4,
    )
    cue = LyricCue(
        text="This deliberately oversized lyric must become sequential cues",
        alpha=1,
    )

    with pytest.raises(SpirophonicTextError, match="align --force"):
        draw_lyric_overlay(
            frame,
            cue,
            config=config,
            font_path=FONT_PATH,
            reference_height=1080,
        )


@pytest.mark.skipif(not FONT_PATH.is_file(), reason="target Ubuntu font unavailable")
def test_lyric_overlay_changes_only_glyph_region_without_background_box() -> None:
    frame = np.full((1080, 1920, 3), (16, 16, 20), dtype=np.uint8)
    config = TextConfig(font=FONT_PATH, size=60)
    cue = LyricCue(
        text="Stay",
        alpha=1,
    )

    rendered = draw_lyric_overlay(
        frame,
        cue,
        config=config,
        font_path=FONT_PATH,
        reference_height=1080,
    )

    changed_pixels = np.any(rendered != frame, axis=2)
    assert 0 < np.count_nonzero(changed_pixels) < 10_000
