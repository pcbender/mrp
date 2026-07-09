# MRP Members and Attribution Plan

Implementation plan for band members, feature credits, and track-level
performer attribution in the flat-file content tier. This is the agreed
lightweight alternative to the full relational model described in
`MRP Identity, Artist, Release, and Credit Model.md` — that document remains
the conceptual reference, but **this plan is what gets built**.

## Goals

1. Represent 4Castle as a band with 5 members, each with a bio, image, and
   likeness notes, so the Concept Visual promoter stage can generate
   visually consistent member imagery.
2. Support track-level performer attribution so promoter copy can say
   things like "Raven's dynamic vocals push the track...", grounded in data
   rather than guessed from prose.
3. Support features between catalog artists, e.g. a PCBender song
   featuring STAB on vocals.
4. Zero migration: all 175 existing release YAMLs and all 6 artist YAMLs
   must validate unchanged. Every new field is optional.

## Design principles (already decided — do not re-litigate)

- **No new record types.** No Person, Persona, Membership, or Credit files.
- **Embed, don't normalize.** Members live inside their band's artist YAML.
- **Two resolution scopes, no polymorphic references:**
  - An **artist id** (in `featuring` or `performers[].artist`) resolves in
    `content/artists/`. Rule: if an act has its own catalog presence, it is
    an artist record (STAB and PCBender already are).
  - A **member slug** (in `performers[].member`) resolves only within the
    `members` list of the release's owning artist (`artist_id`). Members
    have no standalone files.
- **Display strings stay in `credits`** (the existing free-string map, which
  is what pages print). `featuring` and `performers` are the structured
  layer that tooling reads. Both can coexist on the same release.
- Rights/royalty data stays out of `content/` entirely. Not in scope.

## Phase 1 — Schema changes

### `mrp/schemas/artist.schema.json`

Add an optional `members` array to the `artist` object:

```yaml
members:
  - slug: raven-cortez        # required; pattern ^[a-z0-9][a-z0-9-]*$
    name: Raven Cortez        # required
    roles: [lead vocals]      # optional array of strings
    bio: ...                  # optional string
    image: /assets/...        # optional string (site-relative path)
    likeness_notes: ...       # optional string — visual identity prompt
                              # notes for generation consistency
    status: current           # optional enum: current, former, guest
    display_order: 1          # optional integer
```

Schema details: `members` is optional, `minItems: 1` when present, items are
objects with `additionalProperties: false`, required `slug` and `name`.
Member slugs must be unique within the artist (enforce in the lint pass,
Phase 2 — JSON Schema cannot express it).

Also extend the artist `type` enum with `"band"` (currently
`solo | band? — no: solo | project | band` — check the current enum, it is
`["solo", "band", "project", null]`, so `band` already exists; no change
needed if so).

### `mrp/schemas/release.schema.json`

Two additions, both optional:

1. `featuring` — array of artist-id strings (same kebab-case pattern as
   `artist_id`). Allowed at the **release level** and inside the
   **`$defs/song`** object (track level).

2. `performers` — array allowed inside **`$defs/song`** only. Each item is
   an object (`additionalProperties: false`) with:
   - exactly one of `member` (member slug) or `artist` (artist id) —
     use `oneOf` with mutually exclusive `required`
   - `role` — required string (e.g. "lead vocals", "guitar", "producer")
   - `note` — optional string

Example (PCBender single featuring STAB):

```yaml
release:
  artist_id: pcbender
  featuring: [stab]
  credits:
    primary_artist: PCBender
    featured_artist: STAB
  song:
    performers:
      - artist: stab
        role: vocals
```

Example (4Castle track with member attribution):

```yaml
song:
  performers:
    - member: raven-cortez
      role: lead vocals
    - member: theo-marsh
      role: guitar
```

(`theo-marsh` is a placeholder — real member data comes in Phase 4.)

## Phase 2 — Cross-file lint pass

Extend `mrp/core/validate.py` (the existing content validation entry point,
wired through `mrp/cli/main.py`). After per-file JSON Schema validation,
add reference checks:

- Every id in a release's `featuring` (release- and track-level) and every
  `performers[].artist` must match an existing record in `content/artists/`.
- Every `performers[].member` must match a `members[].slug` in the artist
  record referenced by the release's `artist_id`.
- Member slugs must be unique within one artist's `members` list.
- Report failures through the existing validation-error reporting used by
  `validate.py` (see `mrp/schemas/validation-error.schema.json`), same as
  schema errors.

This is a lint pass over ~180 small YAML files; load artists once into a
dict, then stream releases. No database, no index files.

## Phase 3 — Site rendering (minimal)

Keep this deliberately small:

- **Artist page** (`site/src/pages/artists/[slug].astro`): if the artist has
  `members`, render a members section — name, roles, bio, image — ordered by
  `display_order`. Respect `status` (render `former` members under a
  separate heading or omit; simplest acceptable: only render `current` and
  `guest`).
- **Release/song pages** (`ReleaseLanding.astro` / `SongLanding.astro`): if
  `featuring` is present, render "feat. X" after the artist name, where X
  links to the featured artist's page (`/artists/{id}/`) using the artist
  record's `name`. Do **not** attempt to render `performers` on the site
  yet — that data is for the promoter pipeline; site display can come later.
- Loader work happens in `site/src/lib/content.js` / `catalog.ts` as needed
  (e.g. expose `members` and resolve `featuring` ids to artist objects).

## Phase 4 — Populate 4Castle

- Change `content/artists/4castle.yaml` `type` from `project` to `band`.
- Add 5 member entries. **Member names, bios, roles, and likeness notes
  must come from Michael** — do not invent them. Raven Cortez (lead vocals)
  is confirmed; the other four need his input. If building before that
  input arrives, stop and ask rather than stubbing fake members into
  committed content.
- Member images go under `site/public/assets/artists/4castle/` (or stay
  null until images exist).
- Note: content YAMLs in this repo are ASCII-escaped; when writing YAML
  from Python use `allow_unicode=True` and match the existing dump style
  used by the admin/CLI writers.

## Phase 5 — Tests

Extend the existing suite in `tests/`:

- Schema: artist with/without `members` validates; bad member entry
  (missing slug/name, bad slug pattern) fails; release with `featuring`
  and `performers` validates; a `performers` item with both `member` and
  `artist` (or neither) fails.
- Lint: unknown `featuring` id, unknown `member` slug, duplicate member
  slugs each produce a validation error; a correct fixture passes.
- Regression: full validate run over real `content/` stays green
  (proves zero-migration goal).

## Out of scope (explicitly)

- Promoter Concept Visual stage itself — this plan only provides its data
  contract (`members[].likeness_notes`, `performers`, `featuring`).
- Renaming `artist_id`, publish-ladder changes, Person/Persona/Membership/
  Credit record types, likeness asset registry, royalty/publishing fields.
- Member promotion to standalone artist (documented growth path: give the
  member their own artist record later and optionally add an `artist_id`
  pointer to their member entry — nothing to build now).

## Repo rules that apply

- Work on a branch off up-to-date `origin/main` (content commits land on
  main via the admin Changes page — always pull first).
- Do not touch frozen migration/import tools or clone content
  (see `CLAUDE.md` / `docs/CONTENT-PIPELINE.md`).
- Run `graphify update .` after code changes.
- After implementation, update `docs/CONTENT-MODEL.md` to document the new
  fields.
