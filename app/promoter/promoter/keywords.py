"""
Channel keyword merging and budgeting.

YouTube's channel keywords box (Studio > Settings > Channel > Basic info) is one
comma-separated string capped at 500 characters, with multi-word phrases wrapped
in double quotes. The cap applies to the assembled string, not the keyword count,
so budgeting has to happen against the exact text that gets pasted in.

Merging is append-only on purpose: a channel's keywords should be stable, and
anything already on the record may have been hand-curated. New candidates land
at the end and are the first to be dropped when the budget runs out.

Because nothing ever leaves the list on its own, the per-artist blocklist is the
pruning tool. It reads like a .gitignore and is applied to the whole merged list
on every write, so adding a pattern removes matching keywords retroactively.
"""
from __future__ import annotations

import fnmatch

KEYWORD_BUDGET = 500


def format_keyword(keyword: str) -> str:
    """Render one keyword the way YouTube expects it in the keywords box."""
    keyword = " ".join(str(keyword).split())
    return f'"{keyword}"' if " " in keyword else keyword


def keyword_field(keywords: list[str]) -> str:
    """Assemble the exact string that gets pasted into YouTube Studio."""
    return ", ".join(format_keyword(k) for k in keywords)


def normalize(keywords: list[str]) -> list[str]:
    """Trim, collapse whitespace, and drop case-insensitive duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in keywords or []:
        keyword = " ".join(str(raw or "").split()).strip('"')
        if not keyword:
            continue
        key = keyword.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(keyword)
    return out


def is_blocked(keyword: str, patterns: list[str] | None) -> bool:
    """
    Test one keyword against .gitignore-style patterns.

    Supports `*`, `?`, and `[seq]` globs, `#` comments, blank lines, and `!`
    to re-include. Matching is case-insensitive and spans the whole keyword —
    `PCB*` blocks "PCB Bender", bare `PCB` blocks only the keyword "PCB".
    Later patterns win, so a `!` line can carve an exception out of a broader
    rule above it.
    """
    keyword = " ".join(str(keyword or "").split()).casefold()
    if not keyword:
        return False

    blocked = False
    for raw in patterns or []:
        pattern = " ".join(str(raw or "").split())
        if not pattern or pattern.startswith("#"):
            continue
        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:].strip()
        if not pattern:
            continue
        if fnmatch.fnmatchcase(keyword, pattern.casefold()):
            blocked = not negated
    return blocked


def apply_blocklist(
    keywords: list[str],
    patterns: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Split keywords into (kept, blocked), preserving order in both."""
    kept: list[str] = []
    blocked: list[str] = []
    for keyword in keywords or []:
        (blocked if is_blocked(keyword, patterns) else kept).append(keyword)
    return kept, blocked


def merge_keywords(
    existing: list[str],
    candidates: list[str],
    patterns: list[str] | None = None,
    budget: int = KEYWORD_BUDGET,
) -> tuple[list[str], list[str], list[str]]:
    """
    Append new candidates to the existing list, drop blocked ones, trim to budget.

    Existing keywords keep their order and their priority — they are only
    dropped if they overflow the budget on their own. The blocklist runs before
    budgeting and covers existing keywords too, so a new pattern prunes the list
    retroactively rather than only filtering future candidates.

    Returns (kept, dropped, blocked): `dropped` is what did not fit the budget,
    in input order; `blocked` is what the patterns removed.
    """
    merged = normalize(list(existing or []) + list(candidates or []))
    merged, blocked = apply_blocklist(merged, patterns)

    dropped: list[str] = []
    while merged and len(keyword_field(merged)) > budget:
        dropped.append(merged.pop())

    dropped.reverse()
    return merged, dropped, blocked
