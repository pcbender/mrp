# Spotify Catalog Import v0.2 Candidate

The WXR/live-capture migration only covers what existed on
`maricoparecords.com` at crawl time: 4 artists
(`4castle`, `lingua-aeternum`, `pcbender`, `stab`) and 32 releases. The real
roster has grown to 6-7 artists with releases the old site never listed. This
adds a second, independent import source — the Spotify Web API — that
backfills the gap, following the same additive/reviewable pattern as
`import-site`: write draft candidates under `content/import-review/`, never
write directly to `content/artists/` or `content/releases/`.

Distributor dashboards (Landr, Amuse) are not the primary source. They have no
export/API, their DOM changes without notice, and automating a login is
fragile even against your own account. They remain the fallback for the
handful of fields Spotify's API never exposes (songwriter/producer/mastering
credits, catalog number, publisher entity, pre-release drafts) — filled in by
hand during review, not scraped.

## Roster input

Spotify has no reliable artist-name search for indie catalogs, so the importer
takes explicit Spotify artist URLs rather than searching. A human-edited
roster file drives it:

```yaml
# content/import-review/spotify-roster.yaml
artists:
  - artist_id: 4castle            # existing content/artists/4castle.yaml
    spotify_url: null              # null = reuse artist.links.spotify already on file
  - artist_id: lingua-aeternum
    spotify_url: null
  - artist_id: pcbender
    spotify_url: null
  - artist_id: stab
    spotify_url: null
  - artist_id: null                # unknown until lookup; importer proposes a slug
    spotify_url: https://open.spotify.com/artist/...
  - artist_id: null
    spotify_url: https://open.spotify.com/artist/...
  - artist_id: null
    spotify_url: https://open.spotify.com/artist/...
```

For the 3 known artists, the importer reads `artist.links.spotify` out of the
existing `content/artists/*.yaml`/`.json` records instead of repeating the
URL. For the new artists you supply, leave `artist_id: null` and the importer
slugifies the Spotify display name (same `slugify()` used by
`mrp/core/release.py`) and reports the proposed id for confirmation; you can
pin an explicit id in the roster instead if you already know what you want.

## Auth and dependencies

- Spotify Client Credentials flow (app-only token, no personal login,
  read-only public catalog data). Requires a free Spotify Developer app for a
  `client_id`/`client_secret`.
- Credentials load from `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`
  environment variables, or from an untracked `.env` file at the repo root
  (`KEY=VALUE` per line; real environment variables take precedence over
  `.env` if both are set) — never committed either way. `.env` is already
  gitignored. Added a line to `docs/AGENT-USAGE.md` Safety Rules: "Do not add
  Spotify API credentials to git."
- New dependency: `requests` (clean retry/header handling for Spotify's 429 +
  `Retry-After`). Added to `requirements.txt` — this is the first network
  dependency the repo has needed.

## Known Spotify API quirks (this app)

Discovered running the first live import; both are dev-mode/new-app
restrictions, not bugs in this code:

- `GET /artists/{id}/albums` rejects any `limit` value at all (even
  Spotify's own default of 20) with `400 Invalid limit`. Fixed by omitting
  `limit` entirely and relying on the server default page size; `next`-based
  pagination is unaffected.
- The batch `GET /tracks?ids=...` ("Get Several Tracks") endpoint returns
  `403 Forbidden`. The singular `GET /tracks/{id}` works fine. `get_tracks()`
  fetches one track per request instead of batching — acceptable at this
  catalog's scale (one request per track per import run).

## New module: `mrp/core/spotify_client.py`

Thin wrapper, no business logic:

- `get_token()` — client-credentials token, cached in memory for its TTL.
- `get_artist(artist_id)`, `get_artist_albums(artist_id)` (paginated,
  `include_groups=album,single`), `get_album(album_id)` (full track list +
  `external_ids`, `label`, `copyrights`).
- Retries on 429 honoring `Retry-After`; raises on other non-2xx.

## New module: `mrp/core/import_spotify.py`

Mirrors `import_site.py`'s shape (`import_spotify(repo, roster, ...) -> report
dict` with `command`, `status`, `summary`, `outputs`, `notes`,
`report_path`).

For each roster artist:

1. Resolve artist_id (existing record or slugified name) and fetch
   `GET /artists/{id}`.
2. Fetch all albums/singles via `GET /artists/{id}/albums`, filtered to items
   where the roster artist is the primary (`artists[0].id`) — drops
   "appears on" and compilation noise.
3. Fetch each `GET /albums/{id}` for full track data.
4. Map to candidate records (see below).

### Artist candidate mapping

| MRP field | Source |
|---|---|
| `id` | roster override or slugified Spotify `name` |
| `name` | Spotify `name` |
| `image` | Spotify largest `images[0].url` (remote URL, see Assets) |
| `links.spotify` | Spotify `external_urls.spotify` |
| `bio_short`, `bio_long`, `type`, `default_publisher`, other `links.*` | left null — Spotify has none of these; drafted collaboratively during review (you supply source material — press kit, EPK, prior bio text — I draft copy, you approve/edit) |
| `visibility` | `draft` until reviewed |

### Release candidate mapping

| MRP field | Source |
|---|---|
| `title` | album `name` |
| `release_date` | album `release_date`, **only if** `release_date_precision == "day"`; otherwise left null and flagged in `notes` (schema requires a full ISO date — Spotify sometimes only knows year/month) |
| `upc` | album `external_ids.upc` |
| `label` | album `label` (often the distributor name as submitted, not "Maricopa Records" — flagged for review, not assumed) |
| `cover_image` | largest album image (remote URL, see Assets) |
| `links.spotify` | album `external_urls.spotify` |
| `model` / `release_type` | by **track count**, not Spotify's `album_type`, for consistency with the existing heuristic in `migrate_site.py::promote_catalog_metadata`: 1 track → `model: song`, `release_type: single`; 2+ tracks → `model: album`, `release_type: ep` if ≤6 tracks else `album` |
| `song`/`tracks[].isrc` | track `external_ids.isrc` |
| `song`/`tracks[].duration` | track `duration_ms` formatted `"m:ss"` (no existing convention in the repo — this importer establishes it) |
| `song`/`tracks[].explicit` | track `explicit` |
| `song`/`tracks[].preview_audio` | track `preview_url` (frequently `null` — Spotify has scaled back 30s previews; not guaranteed) |
| `catalog_number`, `publisher`, `credits.*`, `summary`, `description`, `links.apple_music`/`bandcamp`/`soundcloud`/`youtube_music`, `seo.*` | left null/blank — **manual fill from Landr/Amuse and label copy**, called out explicitly in `notes` |

### Dedup against the existing 32 releases

Before emitting a release candidate, check `content/releases/*` for a match,
in order: UPC equality, then track ISRC equality, then normalized
title+artist_id. On match:

- Do **not** create a duplicate candidate.
- Emit a `review_status: matched_existing` entry with `existing_path` and a
  `proposed_patch` containing only fields that are currently null on the
  existing record (e.g. backfill a missing `isrc`/`upc`/`release_date`).
- Never auto-write the patch — applying it is a manual/agent review step,
  same as everything else under `import-review/`. This avoids clobbering any
  hand-edited WXR-migrated content.

Unmatched candidates are new-release candidates, ready for cover download and
field completion before promotion.

### Assets (cover art)

Spotify serves recompressed cover art, not your original master art from
Landr/Amuse — prefer the original file at promotion time if you still have
it. For convenience, `--download-covers` fetches the remote image URLs into
`content/import-review/spotify-assets/{artist_id}/{release_slug}/cover.jpg`
and records `url`, `path`, `bytes`, `sha256`, `review_status: needs_review` —
same shape as `candidate_assets()` in `import_site.py`. Without the flag, the
candidate YAML just carries the remote URL for manual download.

## Output

```text
content/import-review/spotify-artists.yaml      # candidates + matched-existing notes
content/import-review/spotify-releases.yaml     # candidates + matched_existing patches
content/import-review/spotify-assets.yaml        # cover-art candidates (--download-covers)
reports/import/{timestamp}-spotify.json          # machine-readable run report
```

Kept separate from the WXR-era `content/import-review/{artists,releases,assets}.yaml`
so the two import sources never overwrite each other on a re-run.

## CLI

```bash
scripts/mrp import-spotify --roster content/import-review/spotify-roster.yaml --json
scripts/mrp import-spotify --roster content/import-review/spotify-roster.yaml --download-covers --json
```

Wired into `mrp/cli/main.py` next to `import-site`, same `--json`/`--dry-run`
global flags.

## Promotion

Stays manual/agent-assisted, matching how WXR candidates are promoted today —
there is no automatic "promote" command in the repo, only the in-place
backfill logic inside `migrate-site`. For this feature: review the candidate
files, then either hand-author the `content/artists/*.yaml` /
`content/releases/*.yaml` records from the reviewed candidates, or run
`scripts/mrp release create` for brand-new releases and fold in the Spotify
fields afterward. A standalone `promote-spotify` command is a reasonable v0.3
follow-up once the manual flow has been exercised a few times, not built now.

## Tests

`tests/test_import_spotify.py`, mocking `requests` (no live network calls in
CI), covering: roster parsing (existing vs. new artist), slug derivation,
track-count → `model`/`release_type` mapping, partial-date handling, and the
UPC/ISRC dedup match against a fixture release.

## Decisions

1. Use `requests`, not stdlib `urllib.request`.
2. In scope: backfill missing `isrc`/`upc`/`release_date` on the existing 32
   releases for the 4 known artists via the `matched_existing` dedup path —
   not deferred.
3. New-artist `bio_short`/`bio_long`/`type`/non-Spotify links are drafted
   collaboratively during review (source material from you, draft copy from
   me, final edit/approval from you) rather than purely manual.
