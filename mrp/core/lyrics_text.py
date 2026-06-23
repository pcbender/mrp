from __future__ import annotations

import re

BRACKET_TAG_PATTERN = re.compile(r"\[[^\]]*\]")
TRAILING_PUNCTUATION_PATTERN = re.compile(r"[.,;:!?]+$")
QUOTE_CHARS = ('"', "“", "”")
SECTION_HEADING_PATTERN = re.compile(r"^#+\s+.+$", re.MULTILINE)


def extract_primary_section(raw: str) -> str:
    """Pick the right section out of a doc with multiple Suno "# Tab N" /
    "# Lyrics" headings -- some docs put the complete lyrics in the first
    section, others in a later one, with no consistent rule. Picks
    whichever section cleans up to the most actual content; always strips
    the heading line itself. A doc with 0 or 1 headings is unaffected.
    """
    headings = list(SECTION_HEADING_PATTERN.finditer(raw))
    if not headings:
        return raw
    sections = []
    for index, match in enumerate(headings):
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(raw)
        sections.append(raw[start:end])
    if len(sections) == 1:
        return sections[0]
    return max(sections, key=lambda section: len(clean_lyrics(section)))


def clean_lyrics(raw: str) -> str:
    """Normalize a raw lyrics doc into storable lyrics_text.

    Drops bracketed structure tags ([Verse 1], [Chorus], ...) entirely,
    collapses blank-line noise to exactly one blank line between sections,
    and strips end-of-line punctuation except on lines ending in quoted
    speech. Trailing hyphens/ellipses are preserved (Musixmatch convention
    for an intentionally unfinished word).
    """
    unescaped = raw.replace("\\[", "[").replace("\\]", "]")

    # Drive exports each source paragraph (i.e. each lyric line) separated by
    # "\n\n" -- a single blank piece between two real lines is just that
    # paragraph-break noise, not an intentional blank line. Two or more
    # consecutive blank pieces means the source had an actual empty
    # paragraph (a real section break), which collapses to exactly one
    # blank line in the output.
    lines: list[str] = []
    blank_run = 0
    for piece in unescaped.split("\n"):
        line = BRACKET_TAG_PATTERN.sub("", piece)
        line = re.sub(r"\s{2,}", " ", line).strip()
        if not line:
            blank_run += 1
            continue
        if lines and blank_run >= 2:
            lines.append("")
        blank_run = 0
        lines.append(_strip_trailing_punctuation(line))

    return "\n".join(lines).strip()


def _strip_trailing_punctuation(line: str) -> str:
    if line.endswith(QUOTE_CHARS):
        return line
    return TRAILING_PUNCTUATION_PATTERN.sub("", line)
