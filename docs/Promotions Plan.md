# Promotions Plan

External social media promotion strategy and automation roadmap.
Captured 2026-07-07. Extends the admin Promoter tool (currently bios/blurbs)
into a full promotion pipeline. Companion to `MRP Admin Milestones.md`
(v0.3 "Social promo package generator" and "Approval queue" items).

## The three motions

Promotion work splits into three motions that automate very differently:

1. **Release pushes** — the burst around a new single: announce, tease,
   remind, thank.
2. **Always-on catalog promotion** — 173 releases; the feed should never go
   quiet between releases. The most automatable and most neglected motion.
3. **Artist presence** — bios, pinned posts, profile art, playlist pitching
   in the artist apps. Low frequency, mostly maintenance.

## Platform reality check

| Platform | Auto-post? | Notes |
|---|---|---|
| Spotify for Artists | **No** | No public API. Canvas, Artist Pick, playlist pitching are manual, forever. |
| Apple Music for Artists | **No** | Same. Both artist apps are checklist territory, not automation territory. |
| Facebook Pages | Yes | Meta Graph API. Pages only — personal profiles are off-limits (ban risk). |
| Instagram | Yes | Same Meta API; Business/Creator accounts linked to a FB Page only. |
| YouTube (Shorts) | Yes | Data API upload, OAuth (we already have YouTube API footing). |
| TikTok | Yes, painful | Content Posting API requires app review. Do last. |
| Bluesky / Mastodon | Yes, trivially | Open APIs, free, no review. Perfect first connector. |
| X/Twitter | Technically | API is paid (~$100+/mo). Paste manually or skip. |
| Threads | Yes | API exists, Meta ecosystem. |

Honest boundary: the two platforms artists care about most (Spotify/Apple
artist tools) cannot be automated — but everything *around* them can, and
the socials with APIs cover the actual reach.

## Automation pillars

**Promo kit (generate, don't post).** One click per release assembles
everything needed to promote it anywhere:

- 3–5 copy variants per platform (IG caption ≠ Bluesky post), hashtags
- The right links: distributor smart link (LANDR promo page / Amuse
  share link), platform deep links — all already in the release records
- Cover art in platform crops
- **Video short**: cover art + the 30-second Sampler snippet rendered to
  mp4 with ffmpeg — the standard currency for Shorts/TikTok/Reels/Stories
- Raw material already in the system: `promo_blurb`, critic review text,
  artist bios, release metadata

**Claim engine.** The metrics DB (`~/.mrp/metrics.db`) makes the roadmap's
promo claim helper real: stream-count milestones ("just crossed 1,000
streams"), best-month claims, "#1 this month", release anniversaries,
"deep cut of the week" back-catalog rotation. A weekly scan emits
*suggested* posts. This keeps motion #2 alive unattended.

**Approval queue.** Everything generated lands as a draft with a status:
`draft → approved → scheduled → posted`. Nothing external fires without
human approval — same philosophy as the Changes page. Automated
*generation* is a superpower; automated *publishing without review* is how
brands post garbage.

**Connectors.** Once the queue exists, posting approved items is
per-platform plumbing, easiest first: Bluesky/Mastodon → Meta (FB Pages +
IG; map artist → page ID in the artist YAML links) → YouTube Shorts →
TikTok.

**Checklists.** For Spotify/Apple the kit includes a "manual actions" card:
copy ready to paste into playlist pitches, Canvas reminder, Artist Pick
suggestion, deep links into the artist apps. Automating the *preparation*
of manual work is most of its cost.

## Phases (each useful on its own)

- **Phase 1 — Promo Kit generator.** No external APIs, no credentials, no
  risk. Extends the Promoter stage/tab from bios into per-release kits.
  Human copy-pastes; the machine does the assembly.
- **Phase 2 — Queue + calendar + claim engine.** Internal only.
  Release-day cadence templates (announce day 0, video short day 3, review
  quote week 1), milestone triggers from metrics, anniversary/deep-cut
  rotation. Still human-posted, but from a prioritized queue instead of a
  blank page.
- **Phase 3 — Connectors.** Approve in the queue → it posts. Order:
  Bluesky/Mastodon, Meta, YouTube Shorts, TikTok. Credentials in `.env`.
- **Phase 4 — Close the loop.** Pull engagement metrics back where APIs
  allow, join against the streams DB: did the Shorts push move YouTube
  streams? Promotion, not just posting.

## Strategy notes

- **Per-artist voice over volume.** Solo operator, six artist identities.
  Artist records carry distinct bios/blurbs — the copy generator treats
  those as voice guides so PCBender doesn't sound like STAB. Cheap to do;
  it's the difference between "label spam" and "six artists with feeds."
- Platform self-promo/spam rules apply; only official Page/business
  accounts get automated, never personal profiles.
- Quality over cadence: the queue proposes, the human disposes.
