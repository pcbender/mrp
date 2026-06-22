# TODO

Status as of 2026-06-22. Streaming-link enrichment is the active thread;
see `reports/enrichment/` for individual run reports.

## Blocked

- **Spotify per-track link backfill** (7 multi-track releases / 69 tracks:
  `bent`, `free`, `i-m-still-here`, `inner-outer-over-through`,
  `made-by-moving`, `the-messy-middle`, `tria`). Code fix landed in PR #4
  (`build_track()` now copies a track's own `external_urls.spotify`), but
  the live data backfill is blocked by a ~21h Spotify rate limit from
  2026-06-21. Do not attempt before ~16:30 on 2026-06-22 -- probe with a
  single lightweight call first, not a batch.

## Done

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
- **YouTube channel links missing** for `michael-rose` and `stab`
  (`content/artists/*.yaml` `links.youtube`) -- their catalogs haven't
  been touched by `enrich-youtube` yet. Re-run once set.
- **Site icons**: `StreamingLinks.astro` only has custom SVG icons for
  spotify/apple_music/youtube_music. tidal/deezer/amazon_music/youtube/
  bandcamp/soundcloud render as functional but icon-less links; pandora
  will need one too once Odesli covers it.
- **Export staging site for review**: `mrp build` + `mrp stage` (+
  `mrp verify`) once the above link work settles.

## Open questions (untouched this engagement)

- 296 vs 292 song-count discrepancy -- never confirmed where 296 comes
  from (Landr/Amuse dashboard vs. something else).
- 9 skipped Spotify release candidates with slug collisions, sitting in
  `content/import-review/spotify-releases.yaml`, need manual
  disambiguation before they can be promoted.

## Operational note

This working directory (`/home/mrose/mrp`) is shared with the user's own
concurrent terminal/editor activity. Two distinct incidents this session
(a branch-pointer mixup, and the per-track link reversion above) trace
back to this. If practical, avoid having release content files open for
editing while a live enrichment run is in progress.
