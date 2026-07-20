# MRP Admin Milestones

The living roadmap. Update this doc as milestones complete or priorities
change — it replaces the retired TODO.md and the pre-workspace planning docs.

## MRP Admin v0.1 — Complete

- Launch local admin server
- List releases from content/releases
- Create new release draft
- Edit existing release YAML safely
- Validate release
- Run status
- Run enrich links
- Show missing platform links

## MRP Admin v0.2 — Complete

- Master audio path selection
- Generate 30-second snippet
- Cover art asset handling
- Run review/impression pipeline
- Build/stage/verify/approve/publish controls

Proven live: two releases ("A Distant Memory", "On To Potter's Field")
published to production end-to-end through the UI.

## Near-term cleanup (small, unscheduled)

- Split blurb vs liner: critic records share a single `review_text` field
  for both (and `album_blurb` vs `album_long`)
- Monitoring stage is a stub — decide what thin-but-useful looks like
- ~~Re-run `enrich-links` across the catalog~~ Done 2026-07-06/07: replaced by
  the converging "Run Missing Links" job (patience windows from release_date,
  expiry into `automation.links_na`, promo→Apple→YouTube→Odesli source order,
  Odesli circuit breaker). First full run settled the back catalog: 75 links
  added, 1142 slots settled (PRs #61–#63)

## MRP Admin v0.3

- ~~Catalog page~~ Done 2026-07-10: a **Catalog** nav item (`/catalog`) that
  flattens every track across all releases into one searchable list (title,
  artist, release, #, duration; explicit/instrumental flags). Free-text
  search over track/artist/release plus an artist filter, mirroring the
  Releases-list HTMX pattern; each row links to the per-track workspace
  editor (`/releases/{slug}/tracks/{track_slug}`). Read-only list — no track
  writes. Files: `mrp/admin/routes/catalog.py`,
  `mrp/admin/templates/catalog/`, `tests/test_admin_catalog.py`
- ~~Artist editor~~ Done 2026-07-07 (PR #65): list + create + full editor
  (identity, bios, links board), schema-validated before write
  - ~~**Band members editor**~~ Done 2026-07-09: the schema, cross-file
    lint, and public rendering for band `members` shipped in PR #73; this
    adds the admin editing surface. A **Band Members** card on the artist
    form (shown for bands / any artist with members) lists members with
    completeness dots (roles, bio, image, likeness_notes) linking to a
    per-member detail editor, modeled on the tracks experience. Full CRUD:
    add (`/artists/{id}/members/new` → `POST /members`), edit + slug-change
    (`GET|POST /artists/{id}/members/{slug}`), delete (drops the `members`
    key when the last one goes, honoring `minItems:1`). HTMX save validates
    the whole artist record (schema + unique-slug guard) before writing via
    `serialize_structured_record`. Fields: `slug`, `name`, `roles`,
    `status`, `display_order`, `image`, `likeness_notes`, `bio`. Files:
    `mrp/admin/routes/artists.py`, `mrp/admin/templates/artists/`.
    Still open: fill 4Castle members' `likeness_notes` + `image` (null) for
    the Concept Visual stage
- ~~**Release attribution editor**~~ Done 2026-07-09: the release editor now
  exposes the `featuring` / `performers` fields from PR #73. Release-level
  `featuring` (comma-separated artist IDs, datalist-assisted) on the Details
  tab; per-track `featuring` + a `performers` editor (add/remove rows, each
  a member-or-artist + role + optional note) on the track detail page. Saves
  run the schema check plus cross-file guards that resolve featured artists
  and performer artists against `content/artists/` and performer members
  against the release's owning band — mirroring `mrp/core/validate.py`.
  Files: `mrp/admin/routes/workspace.py`,
  `mrp/admin/templates/releases/workspace/{details,track_detail}.html`
- ~~Post editor~~ Done 2026-07-07 (PR #65): full CRUD; new posts get
  `source.system: admin` (schema extended); migrated-WP provenance preserved
  on edit. Note: the site renders posts regardless of status — status is
  workflow bookkeeping, not a publish gate (possible follow-up in
  `site/src/lib/content.js`)
- Social promo package generator (posts, video shorts) — plan captured in
  `Promotions Plan.md` (2026-07-07). ~~Phase 1: per-release promo kit~~ Done
  2026-07-07 (PR #67): promoter-kit job on the Promoter stage — voice-guided
  per-platform copy, 9:16 video short (cover + snippet), crops, smart link,
  Spotify/Apple checklist. Phases 2–4 (queue/calendar/claims, connectors,
  feedback loop) open
- Approval queue for website/social/artist updates — Phase 2 of
  `Promotions Plan.md` (queue + calendar + claim engine)
- Show pipeline logs/reports

### Promoter Video Generation — Three Modes

The Promoter tab should preserve the current static ffmpeg path while adding
more expressive video options as explicit, user-triggered upgrades:

- **Static cover** — current default and fallback: deterministic ffmpeg render
  from release cover + sampler snippet; no external dependency
- ~~**Animated cover**~~ Done 2026-07-07 (PR #69): Nim-powered cover animation
  via the admin's own MCP client (OAuth discovery + dynamic client
  registration, token in `~/.mrp`); Seedance 2 Fast silent 9:16 bed, local
  ffmpeg loop + snippet mux; Connect Nim / Check credits on the Promoter tab
- **Concept visual** — high-end mode 3, spec captured 2026-07-07 in
  `Promotions Plan.md` ("Mode 3 spec — Concept Visual"): Gemini concept
  brief → Nim artist-look image (likeness-consistent wardrobe/setting/hair
  per release; proven with STAB) → Nim video render + local snippet mux,
  human gate between every stage

### MRP Music Video Designer

Planned 2026-07-20. Move the headless Python renderer from Spirophonic into
MRP, leave the Spirophonic React browser instrument unchanged, and build the
production editor as a new FastAPI/Jinja/HTMX workspace stage. The phased
architecture, backward-compatible stems and music-video track contracts,
isolated renderer test lanes, job requirements, and Astro compatibility gates
are captured in [MRP Music Video Designer Plan](<MRP Music Video Designer Plan.md>).

Implementation begins with optional schema contracts and compatibility tests;
the renderer moves only after existing and enriched track records are proven to
validate and build through Astro without leaking private production paths.

Milestones 1 and the MRP side of Milestone 2 were implemented 2026-07-20 on
`feat/music-video-designer-plan`: optional per-track contracts remain backward
compatible, the headless renderer and parity suite now live in `mrp.video`, and
`scripts/mrp video ...` exposes lazy diagnostic commands. Removal of the donor
Python renderer is intentionally a separate post-merge change; the Spirophonic
React application remains untouched.

Milestone 3 was implemented 2026-07-20 on the same branch: a release/track
adapter now creates symbolic versioned projects and ignored runtime manifests,
aggregates repeated semantic stem roles deterministically, records input hashes
and preflight results, detects stale artifacts, and exposes prepare, analyze,
align, preview, and render commands under `scripts/mrp video track ...`.

## MRP Admin v0.4

- ~~LANDR/Amuse CSV import~~ Done 2026-07-07 (PR #66): Metrics page imports
  LANDR royalty CSVs + Amuse XLSX (rolling-range) exports from the
  `/mnt/c/Docs` drop folder; header-signature detection, SHA-256 row-hash
  dedupe so overlapping monthly downloads are no-ops
- ~~Analytics database~~ Done 2026-07-07 (PR #66): normalized `royalty_rows`
  in `~/.mrp/metrics.db` (outside git, shared by both checkouts), UPC/ISRC
  on every row for future catalog joins; proof report: Streams by Artist
  with distributor split + net USD
- Top songs / platform / revenue tables
- Promo claim helper, e.g. "Seaward Sings is currently our #1 streamed song"

## MRP Admin v0.5 — Complete

- ~~Add Distributor field to the release model and make the pipeline
  distributor-aware~~ Done 2026-07-06/07 (PRs #60–#63): schema + 173-release
  backfill, required dropdown on the Details tab, inference from UPC at
  Spotify import, and the combined "Distributor Promo Links" job (LANDR
  scrape vs Amuse smart-link API, UPC cross-checked)
- Backfill is automatic from UPC blocks (ground-truthed 2026-07-06 against
  known releases in every block): 12-digit UPCs with 05xxxx/99xxxx prefixes
  → LANDR (149 releases); 13-digit 73xxxx (Sweden GS1) → Amuse (23).
  Spotify's API has no distributor field — `label`/`copyrights` are
  distributor-submitted text, so UPC is the only reliable signal.
  Sole exception: `tits-up-remix` has no UPC and needs a manual tag.


## TODO List
- ~~git integration~~ Done 2026-07-07 (PR #64): Changes page — review diffs,
  Approve & Push commits content/assets pathspecs to main (validation gate,
  branch guard, pull --ff-only). Runtime split: admin runs from the
  `~/mrp-admin` clone pinned to main; dev tree stays free for branches
- Git operations follow-up (make the Changes page the real push path so we
  stop dropping to a shell): the admin only pulls at approve time and only
  `--ff-only`, so `~/mrp-admin` can silently fall behind `origin/main` after a
  dev-side merge, and a failed pre-pull still commits → a diverged clone whose
  push fails and needs manual reconcile. Wanted: a "behind/ahead origin/main"
  indicator on the Changes page (fetch on load), and a decision on
  pull-on-load vs. surfacing divergence before Approve. Keeps the two clones,
  one truth invariant honest without shell surgery.
- ~~Changes page → controlled publishing workflow~~ Done 2026-07-11 (PRs
  #82–#84): the Changes page is now a staging → verify → production → verify →
  commit ladder (`docs/MRP Changes Page Workflow.md`). Nav change indicator,
  per-change entity + publish eligibility (release must be approved/live),
  generated commit messages, background staging/production deploys with
  signature-based verification/invalidation, and a gated "Approve, Commit,
  and Push" that only commits once both environments are verified. Proven
  live end-to-end (commit `9674e8f`).
- Changes publish follow-up — **remote-production rollback**: the ladder
  reuses `publish()`'s safety helpers but its archive/restore snapshot is
  *local-production* only, so a remote rsync deploy has no automatic
  point-in-time snapshot to roll back to. Options: rsync-pull a snapshot of
  the remote docroot before each deploy, or keep the last-good build
  server-side for a one-command restore. Add a "Roll back production" control
  once a snapshot exists.
- ~~New Release workflow loads entire site into the content section~~ Fixed
  2026-07-10: the Spotify import step-2 form ("Create Release") posts via
  htmx into `#step2`, so its `303` redirect was followed by htmx and the full
  workspace page (nav included) was swapped into the panel. Now returns an
  `HX-Redirect` header for a real browser navigation to
  `/releases/{slug}/details` (same pattern as the member-save fix, PR #77).
