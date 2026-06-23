from __future__ import annotations

from mrp.core.lyrics_text import clean_lyrics, extract_primary_section

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


def test_extract_primary_section_returns_raw_when_no_headings() -> None:
    raw = "[Verse]\n\nLine one.\n\nLine two."
    assert extract_primary_section(raw) == raw


def test_extract_primary_section_strips_single_heading() -> None:
    raw = "# Lyrics\n\n[Verse]\n\nLine one."
    assert extract_primary_section(raw) == "\n\n[Verse]\n\nLine one."


def test_extract_primary_section_picks_the_longer_cleaned_section() -> None:
    # Real-world pattern (e.g. "Tits Up"): Tab 1 has the full structured
    # song, Tab 2 is a short stripped-tag duplicate -- Tab 1 should win.
    raw = (
        "# Tab 1\n\n[Verse 1]\n\nFirst line of the real song.\n\n"
        "[Chorus]\n\nSecond line that matters too.\n\n"
        "# Tab 2\n\nFirst line of the real song."
    )
    chosen = extract_primary_section(raw)
    cleaned = clean_lyrics(chosen)
    assert "Second line that matters too" in cleaned


def test_extract_primary_section_picks_later_section_when_it_is_longer() -> None:
    # Real-world pattern (e.g. "On Down The Way"): Tab 1 is a short
    # fragment, Tab 2 has the actual full structured song.
    raw = (
        "# Tab 1\n\nJust a short fragment line.\n\n"
        "# Tab 2\n\n[Verse 1]\n\nA much longer first line of the real song.\n\n"
        "[Chorus]\n\nWith a second line and even more content here."
    )
    chosen = extract_primary_section(raw)
    cleaned = clean_lyrics(chosen)
    assert "much longer first line" in cleaned
    assert "even more content" in cleaned


def test_clean_lyrics_strips_hash_prefixed_tag_lines() -> None:
    # Variant structure-tag style with no space after the hash, distinct
    # from "# Tab N" doc headings (which always have a space).
    raw = "\\#Verse\n\nFirst real lyric line.\n\n\\#Chorus\n\nSecond real lyric line."
    result = clean_lyrics(raw)
    assert "#" not in result
    assert "Verse" not in result
    assert "First real lyric line" in result
    assert "Second real lyric line" in result


def test_extract_primary_section_prefers_a_section_named_lyrics() -> None:
    # Real-world pattern: Suno docs with named tabs ("Lyrics", "Style",
    # "Persona", "Exclusions") rather than "Tab N" -- only "Lyrics" is
    # actual lyrics; "Style" here is deliberately the longest section to
    # prove the name match wins over the length heuristic.
    raw = (
        "# Lyrics\n\n[Verse]\n\nShort real lyric line.\n\n"
        "# Style\n\nA very long prompt-style paragraph describing the desired "
        "instrumentation and production aesthetic in great detail, much longer "
        "than the actual lyrics section above by design.\n\n"
        "# Exclusions\n\nwhispers, screaming, metal"
    )
    chosen = extract_primary_section(raw)
    cleaned = clean_lyrics(chosen)
    assert cleaned == "Short real lyric line"


def test_extract_primary_section_prefers_bracket_style_over_hash_style() -> None:
    # Real-world pattern (e.g. "Inner Outer"): a \#hash-tagged condensed
    # tab can edge out a [bracket]-tagged tab on raw length even though
    # the bracket-tagged one is the primary take -- bracket style should
    # win when both exist and are close in length.
    raw = (
        "# Tab 1\n\n[Verse]\n\nThe real primary version of this line.\n\n"
        "# Tab 2\n\n\\#Verse\n\nThe real primary version of this line plus extra."
    )
    chosen = extract_primary_section(raw)
    cleaned = clean_lyrics(chosen)
    assert cleaned == "The real primary version of this line"


def test_clean_lyrics_strips_parenthetical_structure_tags() -> None:
    # Real-world pattern (e.g. "On the Advent of a Dream"): some docs use
    # (Verse 1) / (Pre-Chorus) / (Chorus) parenthetical tags instead of
    # [brackets].
    raw = "(Verse 1)\n\nFirst real lyric line.\n\n(Pre-Chorus)\n\nSecond real lyric line."
    result = clean_lyrics(raw)
    assert "(Verse 1)" not in result
    assert "(Pre-Chorus)" not in result
    assert "First real lyric line" in result
    assert "Second real lyric line" in result


def test_clean_lyrics_strips_parenthetical_production_directions() -> None:
    # Real-world pattern (e.g. "Pixy Stix"): free-form production notes
    # and call-and-response role labels, also parenthetical.
    raw = (
        "(Bass & Drums Kick In - Funky Groove)\n\n"
        "Real lyric line here.\n\n"
        "(Lead:)\n\n"
        "Another real lyric line."
    )
    result = clean_lyrics(raw)
    assert "Funky Groove" not in result
    assert "(Lead:)" not in result
    assert "Real lyric line here" in result
    assert "Another real lyric line" in result


def test_clean_lyrics_keeps_legitimate_parenthetical_lyric_lines() -> None:
    # Real-world pattern (e.g. "Slow Down"): a standalone parenthetical
    # backing-vocal echo line is real lyric content, not a tag, and must
    # survive even though it's the only thing on its line.
    raw = "When it keeps moving through you\n\n(through you)\n\nWhen it keeps moving through you"
    result = clean_lyrics(raw)
    assert "(through you)" in result
