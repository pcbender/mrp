from __future__ import annotations

import re

BRACKET_TAG_PATTERN = re.compile(r"\[[^\]]*\]")
TRAILING_PUNCTUATION_PATTERN = re.compile(r"[.,;:!?]+$")
QUOTE_CHARS = ('"', "“", "”")
SECTION_HEADING_PATTERN = re.compile(r"^#+\s+.+$", re.MULTILINE)
# A line that is *only* a hash-prefixed tag word with no space after the
# hash (e.g. "#Verse", "#Pre-chorus") -- a variant structure-tag style seen
# in some docs, distinct from the "# Tab N" / "# Lyrics" doc headings above
# (which always have a space after the hash).
HASH_TAG_LINE_PATTERN = re.compile(r"^#\S+$")
# Some docs use (Verse 1) / (Pre-Chorus) / (Bass & Drums Kick In) / (Lead:)
# style parenthetical structure/production-direction tags instead of
# [brackets]. Parentheses are otherwise left alone -- they're frequently
# legitimate lyric content (backing-vocal echoes like "(through you)") --
# so only a whole line that is a single parenthetical AND whose content
# matches known direction vocabulary (or ends in a role label like
# "Lead:") gets treated as a tag rather than a lyric.
PAREN_LINE_PATTERN = re.compile(r"^\((.*)\)$")
PAREN_DIRECTION_KEYWORD_PATTERN = re.compile(
    r"(?i)\b(verse|chorus|pre-chorus|bridge|outro|intro|refrain|breakdown|hook|"
    r"instrumental|ambient|interlude|fade|final|reprise|spoken|solo|groove|funk|"
    r"drums?|guitar|bass|horns?|backups?)\b"
)


def extract_primary_section(raw: str) -> str:
    """Pick the right section out of a doc with multiple "# ..." headings.

    Docs with Suno tabs typically have one section actually titled
    "Lyrics", distinct from others like "Style"/"Persona"/"Exclusions"
    that are prompt notes, not lyrics -- prefer that section by name
    whenever it's present. Otherwise (e.g. multiple "# Tab N" sections
    with no section named "Lyrics") fall back to whichever section cleans
    up to the most actual content. A doc with 0 or 1 headings is
    unaffected.
    """
    headings = list(SECTION_HEADING_PATTERN.finditer(raw))
    if not headings:
        return raw
    sections = []
    for index, match in enumerate(headings):
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(raw)
        title = match.group().lstrip("#").strip()
        sections.append((title, raw[start:end]))
    if len(sections) == 1:
        return sections[0][1]
    for title, body in sections:
        if title.lower() == "lyrics":
            return body
    # Between near-equal candidates, a section using [bracket] structure
    # tags is more often the primary/canonical take than one using the
    # \#hash style (seen repeatedly as a condensed alternate/secondary
    # version) -- only fall back to pure length when neither or both use
    # brackets.
    bodies = [body for _title, body in sections]
    bracketed = [body for body in bodies if BRACKET_TAG_PATTERN.search(body)]
    candidates = bracketed or bodies
    return max(candidates, key=lambda section: len(clean_lyrics(section)))


def clean_lyrics(raw: str) -> str:
    """Normalize a raw lyrics doc into storable lyrics_text.

    Drops bracketed structure tags ([Verse 1], [Chorus], ...) entirely,
    collapses blank-line noise to exactly one blank line between sections,
    and strips end-of-line punctuation except on lines ending in quoted
    speech. Trailing hyphens/ellipses are preserved (Musixmatch convention
    for an intentionally unfinished word).
    """
    unescaped = raw.replace("\\[", "[").replace("\\]", "]").replace("\\#", "#")

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
        if HASH_TAG_LINE_PATTERN.match(line) or _is_direction_only_line(line):
            line = ""
        if not line:
            blank_run += 1
            continue
        if lines and blank_run >= 2:
            lines.append("")
        blank_run = 0
        lines.append(_strip_trailing_punctuation(line))

    return "\n".join(lines).strip()


def _is_direction_only_line(line: str) -> bool:
    match = PAREN_LINE_PATTERN.match(line)
    if not match:
        return False
    inner = match.group(1).strip()
    return bool(PAREN_DIRECTION_KEYWORD_PATTERN.search(inner)) or inner.endswith(":")


def _strip_trailing_punctuation(line: str) -> str:
    if line.endswith(QUOTE_CHARS):
        return line
    return TRAILING_PUNCTUATION_PATTERN.sub("", line)
