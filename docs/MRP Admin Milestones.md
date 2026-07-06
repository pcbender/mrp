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
- Re-run `enrich-links` across the catalog (per-track + pandora support
  landed after the last full run)

## MRP Admin v0.3

- Artist editor (promoter stage covers bios/blurbs; full record editing
  still requires hand-editing YAML)
- Social promo package generator (posts, video shorts)
- Approval queue for website/social/artist updates
- Show pipeline logs/reports
- Post editor

## MRP Admin v0.4

- LANDR/Amuse CSV import
- Analytics database
- Top songs / platform / revenue tables
- Promo claim helper, e.g. "Seaward Sings is currently our #1 streamed song"

## MRP Admin v0.5

- Add Distributor field to the release model and make the pipeline
  distributor-aware (link update LANDR vs Amuse)
