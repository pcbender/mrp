# TODO

Status as of 2026-06-24. Streaming-link enrichment is the active thread;
see `reports/enrichment/` for individual run reports.

## Done

- **Spotify per-track link backfill** (7 multi-track releases / 69 tracks:
  `bent`, `free`, `i-m-still-here`, `inner-outer-over-through`,
  `made-by-moving`, `the-messy-middle`, `tria`). Code fix landed in PR #4;
  the data backfill was blocked by a ~21h Spotify rate limit from
  2026-06-21, which had cleared by 2026-06-23. Probed with a single
  `get_album()` call first, then fetched all 7 albums directly (7 calls
  total -- track data comes back in the album response, no per-track
  fetch needed) and patched `tracks[].links.spotify` in place. All 69
  tracks matched cleanly by `track_number`, no title mismatches.
- Spotify catalog import (`import-spotify` / `promote-spotify`): 161
  releases, artists promoted into `content/`.
- Odesli enrichment (`enrich-links`): release-level only. `ODESLI_API_KEY`
  support added (60 req/min vs 10 anonymous). 6 real matches found so far
  (Tidal/Amazon Music) -- this catalog has weak Odesli coverage overall.
- Apple Music enrichment (`enrich-apple-music`): free iTunes lookup API,
  keyed off each artist's `links.apple_music` artist-page URL. 145/161
  releases, 134 tracks linked. 18 releases unmatched (likely genuinely
  not on Apple Music).
- YouTube/YouTube Music enrichment (`enrich-youtube`): YouTube Data API
  v3, keyed off each artist's `links.youtube` channel URL.
  `GOOGLE_SERVICE_API_KEY` required. 139/161 releases, 120 tracks linked.
  `youtube_music` is derived from the same matched video ID as `youtube`
  (documented assumption, not verified per-track).
- Fixed a data-loss incident (PR #10): 18 apple_music + 66 youtube
  per-track links were silently reverted in the shared working directory
  sometime after merge, on multi-track releases only. Restored via
  fresh idempotent re-runs; not a code bug (verified via isolated
  full-scale repro twice).
- **YouTube channel links**: added `links.youtube` for `stab`
  (`https://www.youtube.com/channel/UCQkfMbYRs06q_SFW5PPSvWw`); `michael-rose`
  confirmed not a YouTube artist (skipped). Re-ran `enrich-youtube` -- 28
  releases and 82 tracks patched across STAB and PCBender catalogs.
- **Promoted the 9 slug-collision Spotify candidates** (PR #16) that were
  skipped during the original import (PR #3) because their auto-generated
  slug collided with an unrelated existing release of the same title:
  Here Comes the Rain (4Castle), Crimson Decision (Lingua Aeternum),
  Crimson Decision (PCBender), What's Best (PCBender), Inner Outer Over
  Through (PCBender), One Day (PCBender), Mad River (PCBender), Tits Up
  (Remix) (PCBender), You Become The Night (STAB). Each confirmed by the
  user as a distinct song (different UPC/ISRC), not a duplicate. Built
  from the candidate data already in
  `content/import-review/spotify-releases.yaml`, reusing cached cover art
  from the original import run.

## Not started

- **Odesli: add `pandora`** to `PLATFORM_MAP` in `mrp/core/enrich_links.py`
  -- confirmed live that Odesli returns a `pandora` key we currently
  discard.
- **Odesli: extend to per-track level.** Unlike the Apple Music/YouTube
  enrichers, `enrich-links` only ever writes release-level links, never
  `tracks[].links`. Needs the same per-track treatment before re-running
  it will produce per-track Tidal/Pandora/Amazon Music icons.
- **Re-run Odesli** with the above two fixes -- independent of the
  Spotify window, can happen anytime.
- **Site icons**: `StreamingLinks.astro` only has custom SVG icons for
  spotify/apple_music/youtube_music. tidal/deezer/amazon_music/youtube/
  bandcamp/soundcloud render as functional but icon-less links; pandora
  will need one too once Odesli covers it.
- **Export staging site for review**: `mrp build` + `mrp stage` (+
  `mrp verify`) once the above link work settles.

## Operational note

This working directory (`/home/mrose/mrp`) is shared with the user's own
concurrent terminal/editor activity. Two distinct incidents this session
(a branch-pointer mixup, and the per-track link reversion above) trace
back to this. If practical, avoid having release content files open for
editing while a live enrichment run is in progress.
