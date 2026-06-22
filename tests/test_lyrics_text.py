from __future__ import annotations

from mrp.core.lyrics_text import clean_lyrics

WINDS_OF_CHANGE_RAW = (
    "\\[Verse 1\\]\n\nI walked the road less traveled, beneath the twilight's glow,\n\n"
    "The trees, they whispered secrets of places I will go.\n\n"
    "A melody of freedom, it echoed through the air,\n\n"
    "Calling me to listen to the dreams I’d left somewhere.\n\n"
    "  \n\n\\[Pre-Chorus\\]\n\n"
    "And the wind, it carried stories, of the lives we’ve yet to lead,\n\n"
    "A symphony of voices, planting hope like scattered seeds.\n\n"
    "  \n\n\\[Chorus\\]\n\n"
    "Oh, the winds of change, they’re calling my name,\n\n"
    "Guiding my heart through the fire and flame.\n\n"
)


def test_clean_lyrics_strips_bracket_tags_and_unescapes_them() -> None:
    result = clean_lyrics(WINDS_OF_CHANGE_RAW)
    assert "[" not in result
    assert "]" not in result
    assert "Verse 1" not in result
    assert "Pre-Chorus" not in result


def test_clean_lyrics_separates_sections_by_exactly_one_blank_line() -> None:
    result = clean_lyrics(WINDS_OF_CHANGE_RAW)
    # Verse 1 is 4 lines with no blank lines between them (just paragraph
    # noise in the source); a real blank line only appears at each section
    # boundary (Verse 1 -> Pre-Chorus -> Chorus).
    assert "\n\n\n" not in result
    assert result.split("\n\n") == [
        "I walked the road less traveled, beneath the twilight's glow\n"
        "The trees, they whispered secrets of places I will go\n"
        "A melody of freedom, it echoed through the air\n"
        "Calling me to listen to the dreams I’d left somewhere",
        "And the wind, it carried stories, of the lives we’ve yet to lead\n"
        "A symphony of voices, planting hope like scattered seeds",
        "Oh, the winds of change, they’re calling my name\n"
        "Guiding my heart through the fire and flame",
    ]


def test_clean_lyrics_strips_trailing_punctuation() -> None:
    result = clean_lyrics(WINDS_OF_CHANGE_RAW)
    for line in result.split("\n"):
        if line:
            assert not line.endswith((",", ".", ";", ":", "!", "?"))


def test_clean_lyrics_keeps_quoted_line_punctuation() -> None:
    raw = '[Verse]\n\nShe whispered softly, "I\'ll be home soon."\n\nThen she was gone.'
    result = clean_lyrics(raw)
    assert 'She whispered softly, "I\'ll be home soon."' in result
    assert "Then she was gone" in result
    assert "Then she was gone." not in result


def test_clean_lyrics_preserves_trailing_hyphen_and_ellipsis() -> None:
    raw = "[Verse]\n\nAnd then I felt the words just trail-\n\nInto something I could not finish…"
    result = clean_lyrics(raw)
    assert "trail-" in result
    assert "finish…" in result


def test_clean_lyrics_strips_inline_bracket_content() -> None:
    raw = "[Verse]\n\nSomething here [ad-lib] keeps going on."
    result = clean_lyrics(raw)
    assert "[ad-lib]" not in result
    assert "Something here  keeps going on" not in result  # no double space left behind
    assert "Something here keeps going on" in result


def test_clean_lyrics_does_not_touch_parentheses() -> None:
    raw = "[Chorus]\n\nBreaking the chains, I'm not bound anymore (I'm not bound anymore)."
    result = clean_lyrics(raw)
    assert "(I'm not bound anymore)" in result
    assert result.endswith(")")


def test_clean_lyrics_collapses_multiple_blank_lines_to_one() -> None:
    raw = "[Verse]\n\nLine one.\n\n\n\n\nLine two."
    result = clean_lyrics(raw)
    assert "\n\n\n" not in result
    assert result == "Line one\n\nLine two"


def test_clean_lyrics_trims_leading_and_trailing_whitespace() -> None:
    raw = "\n\n[Verse]\n\nLine one.\n\n"
    result = clean_lyrics(raw)
    assert result == "Line one"
