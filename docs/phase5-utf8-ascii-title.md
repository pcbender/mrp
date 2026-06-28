# Phase 5 — UTF-8 Content Encoding + ASCII Search Titles

**Goal:** stop mangling non-ASCII characters in data files; add an optional
`title_ascii` field to releases so the "find a release" search works on a US
keyboard for titles like *Triaτί*.

**Estimated effort:** 4–5 hours, low risk. Everything is mechanical except
deciding the `title_ascii` values for affected releases.

---

## Background

PyYAML's `yaml.safe_dump()` and Python's `json.dumps()` both default to
ASCII-only output. Non-ASCII characters are escaped as `\uXXXX` sequences,
which are valid and parse correctly but are unreadable in a text editor and
produce noisy git diffs.

The site's "find a release" search (`ReleaseBrowser.astro`) compares
`card.dataset.releaseSearch` against the user's query using only
`.toLowerCase().trim()` — no Unicode normalization. Greek or accented
characters in a title cannot be matched by typing the ASCII equivalent.

**Nothing is broken** — pages render correctly, the YAML parses correctly. This
is a readability/ergonomics fix plus a search quality fix.

---

## Current state

### Active YAML write paths (not frozen)

| File | Line | Issue |
|------|------|-------|
| `mrp/core/release.py` | 51 | `yaml.safe_dump(..., sort_keys=False)` — no `allow_unicode` |
| `mrp/core/publish.py` | 130 | `yaml.safe_dump(data, sort_keys=False)` — no `allow_unicode` |

Frozen tools (`migrate_site.py`, `import_site.py`, `promote_spotify.py`,
`clone_*.py`) all explicitly pass `allow_unicode=False` — **do not touch
these**. Their output lives in `content/clone/` and `content/import-review/`
which are frozen tiers.

### Active critic JSON write paths

| File | Line | Issue |
|------|------|-------|
| `app/critic/critic/record.py` | 82 | `json.dumps(..., indent=indent)` — ensure_ascii=True (default) |
| `app/critic/critic/album/record.py` | 74 | same |
| `app/critic/critic/eval.py` | 75 | `json.dumps(data, indent=2)` — same |

### Active content files with non-ASCII in title field

Only 4 files (checked 2026-06-28):

| File | Current title | Needs title_ascii? |
|------|---------------|-------------------|
| `content/releases/tria.yaml` | `Triaτί` | Yes — `"Triati"` |
| `content/releases/hana-on-the-way.yaml` | `Hāna On The Way` | Yes — `"Hana On The Way"` |
| `content/releases/i-cant-quite-make-it-fit.yaml` | `I Can't Quite Make It Fit` | Optional — curly apostrophe; consider `"I Can't Quite Make It Fit"` |
| `content/releases/nearly-nothin-nowhere-fast.yaml` | `Nearly Nothin' Nowhere Fast` | Optional — same |

Note: `tria.yaml`'s title is `Triaτί` (hybrid ASCII/Greek), not fully Greek.
The "Tria" prefix already matches a search for "tria"; it's "triati" that fails.

### 227 files with existing escaped Unicode

Almost all are in `content/clone/` (frozen) or `content/import-review/`
(frozen). A one-time re-encode script should touch **only active tiers**:
`content/releases/`, `content/artists/`, `content/pages/`, `content/posts/`.

---

## Work packages

### WP-5-1 · Fix YAML write paths (forward-only)

**Files:** `mrp/core/release.py:51`, `mrp/core/publish.py:130`

**Change:** add `allow_unicode=True` to both `yaml.safe_dump()` calls.

```python
# release.py line 51 — before
release_path.write_text(yaml.safe_dump(release_record(...), sort_keys=False))
# after
release_path.write_text(yaml.safe_dump(release_record(...), sort_keys=False, allow_unicode=True))

# publish.py line 130 — before
path.write_text(yaml.safe_dump(data, sort_keys=False))
# after
path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
```

**GATE:** confirm existing tests still pass (`pytest tests/`).

---

### WP-5-2 · Fix critic JSON write paths (forward-only)

**Files:** `app/critic/critic/record.py:82`,
`app/critic/critic/album/record.py:74`,
`app/critic/critic/eval.py:75`

**Change:** add `ensure_ascii=False` to each `json.dumps()` call.

```python
# record.py / album/record.py — before
return json.dumps(dataclasses.asdict(self), indent=indent)
# after
return json.dumps(dataclasses.asdict(self), indent=indent, ensure_ascii=False)

# eval.py approve() — before
path.write_text(json.dumps(data, indent=2))
# after
path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
```

**GATE:** `python -m critic.schema out/` still reports all clean.

---

### WP-5-3 · Re-encode existing active content files

Write a one-shot script that reads every YAML file in the active content
directories, re-dumps it with `allow_unicode=True`, and writes it back.
Do NOT touch `content/clone/` or `content/import-review/`.

```python
# suggested script location: scripts/fix_unicode.py
import yaml
from pathlib import Path

ACTIVE_DIRS = [
    "content/releases",
    "content/artists",
    "content/pages",
    "content/posts",
]

for dir_ in ACTIVE_DIRS:
    for path in sorted(Path(dir_).glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if data is None:
            continue
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        print(f"re-encoded {path}")
```

Run the script, then `git diff --stat` to confirm only the expected files
changed and no values were altered. Review the diff on `tria.yaml` to confirm
`Triaτί` becomes `Triaτί`.

**GATE:** `git diff content/clone/` shows zero changes. Site still builds
(`cd site && npm run build`).

---

### WP-5-4 · Add `title_ascii` field to release schema and content

**Step 1 — YAML content.** Add `title_ascii` to the 2 releases that need it for
search. The 2 apostrophe-only titles are optional; use judgment.

```yaml
# content/releases/tria.yaml (inside release:)
title: "Triaτί"
title_ascii: "Triati"

# content/releases/hana-on-the-way.yaml
title: "Hāna On The Way"
title_ascii: "Hana On The Way"
```

**Step 2 — TypeScript types.** `site/src/lib/catalog.ts`

Add optional `title_ascii?: string` to `ReleaseRecord` (line ~22) and
`ReleaseCardModel` (line ~31). In `releaseCardModel()` (line 110) read it
through:

```typescript
export interface ReleaseRecord {
  // ...existing fields...
  title_ascii?: string;
}

export interface ReleaseCardModel {
  // ...existing fields...
  titleAscii?: string;
}

// releaseCardModel() function — add one line:
titleAscii: release.title_ascii,
```

**Step 3 — ReleaseGrid.astro.** Pass the new prop to `ReleaseCard`:

```astro
<ReleaseCard
  title={release.title}
  titleAscii={release.titleAscii}
  {/* ...rest of existing props... */}
/>
```

**Step 4 — ReleaseCard.astro.** Accept the prop and include in `searchText`:

```astro
interface Props {
  // ...existing props...
  titleAscii?: string;
}

const { title, titleAscii, artist, ... } = Astro.props;
const searchText = [title, titleAscii, artist, type, releaseDate, cleanSummary]
  .filter(Boolean).join(" ");
```

**GATE:** serve the site locally, search for "triati" — the Triaτί card
appears. Search for "tria" — still appears. Search for "hana" — Hāna card
appears.

---

## Files changed (full list)

```
mrp/core/release.py                          WP-5-1
mrp/core/publish.py                          WP-5-1
app/critic/critic/record.py                  WP-5-2
app/critic/critic/album/record.py            WP-5-2
app/critic/critic/eval.py                    WP-5-2
scripts/fix_unicode.py                       WP-5-3 (run-once, can delete after)
content/releases/tria.yaml                   WP-5-3 + WP-5-4
content/releases/hana-on-the-way.yaml        WP-5-3 + WP-5-4
content/releases/*.yaml  (re-encode only)    WP-5-3
content/artists/*.yaml   (re-encode only)    WP-5-3
content/pages/*.yaml     (re-encode only)    WP-5-3
content/posts/*.yaml     (re-encode only)    WP-5-3
site/src/lib/catalog.ts                      WP-5-4
site/src/components/ReleaseGrid.astro        WP-5-4
site/src/components/ReleaseCard.astro        WP-5-4
```

## Files NOT to touch

```
content/clone/**          frozen WP-clone passthrough — leave escaped
content/import-review/**  frozen import staging — leave escaped
mrp/core/migrate_site.py  frozen migration tool
mrp/core/import_site.py   frozen import tool
mrp/core/promote_spotify.py  frozen Spotify promotion tool
mrp/core/clone_*.py       frozen clone tools
```

---

## Sequencing

WP-5-1 and WP-5-2 are independent and can be done in parallel. WP-5-3 must
come after WP-5-1 (so the re-encode uses the corrected writer pattern).
WP-5-4 can be done in any order relative to WP-5-3; it is purely additive.

Suggested branch: `content/phase5-utf8`
Suggested PR title: `Phase 5: UTF-8 content encoding + title_ascii search field`
