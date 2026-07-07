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

- ~~Artist editor~~ Done 2026-07-07 (PR #65): list + create + full editor
  (identity, bios, links board), schema-validated before write
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
- New Release workflow loads entire site into the content section
