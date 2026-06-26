# Content Pipeline History & Strategy

## Background

Maricopa Records ran a WordPress site (maricoparecords.com) that had not been
updated in over a year. The site was crawled, exported to WXR format, and a
migration pipeline was written to bring that content into this Astro-based repo.
Simultaneously, Spotify's API was used to build structured metadata for releases
and artists that existed on streaming platforms but were missing or incomplete on
the WP site. Lyrics were attached to tracks by reading from Google Docs.

That migration is **complete and closed**. No further migration work is planned.

---

## The Three Content Tiers (historical)

### Tier 1 — WP Clone (frozen, read-only)

- **Source:** WXR crawl → `mrp/core/migrate_site.py`
- **Output:** `content/clone/pages/` and `content/clone/posts/` (47 pages, 3 posts)
- **Schema:** `clone-record` — stores raw `content_html` from WP verbatim
- **Serving:** `site/src/pages/[...slug].astro` → `CloneLayout.astro`, with WP
  stylesheets injected from `site/public/assets/wp/`
- **Status:** Frozen. These pages serve the migrated WP content as-is. No new
  clone records will be created. The serving infrastructure stays in place until
  these pages are eventually replaced by native Astro pages.

### Tier 2 — WP-to-structured (frozen, read-only)

- **Source:** Same WXR crawl, converted to Markdown/structured format
- **Output:** `content/pages/` and `content/posts/` (page schema with
  `content_markdown`)
- **Serving:** `site/src/pages/[...slug].astro` → `BaseLayout.astro`
- **Status:** Frozen. These are WP pages that were converted to native Astro
  rendering rather than raw HTML passthrough. No new records will be created
  this way.

### Tier 3 — Structured catalog (active, ongoing)

- **Source:** Spotify API import + manual curation
- **Output:** `content/releases/*.yaml`, `content/artists/*.yaml`
- **Schema:** `release` and `artist` schemas (see `mrp/schemas/`)
- **Serving:** `releases/[slug].astro`, `artists/[slug].astro`,
  `releases/[slug]/[track].astro`
- **Status:** This is the live, active pipeline. All new content goes here.

---

## Forward Strategy

**One source of truth. One schema.**

A greenfield Astro site would have a single structured content model from day
one. That is the target state for this repo. Going forward:

- All new artists are created as `content/artists/{slug}.yaml`
- All new releases are created as `content/releases/{slug}.yaml`
- The `release` and `artist` schemas are the only schemas that matter for new
  work
- A thin CMS UI will be built to create and edit artists and releases without
  touching YAML files directly
- The WP clone content (Tiers 1 and 2) is legacy. Those pages will eventually
  be replaced by native Astro pages, at which point `content/clone/`,
  `CloneLayout.astro`, and the WP stylesheets can be removed

---

## What Is Frozen / No Longer Maintained

The following CLI commands and source modules exist but are **complete and
frozen**. Do not extend them, do not fix non-critical bugs in them, do not
write new code that depends on them:

| CLI command | Module | Purpose |
|---|---|---|
| `migrate-site` | `mrp/core/migrate_site.py` | WXR → clone/structured records |
| `import-site` | `mrp/core/import_site.py` | Live WP site scrape |
| `import-spotify` | `mrp/core/import_spotify.py` | Spotify API → import-review staging |
| `promote-spotify` | `mrp/core/promote_spotify.py` | Promote staged Spotify records to content/ |
| `clone-*` | `mrp/core/clone_*.py` | WP asset/head/rewrite cloning utilities |
| *(WXR parsing)* | `mrp/core/wxr.py` | WP XML format parsing |

The `content/import-review/` directory holds staging artifacts from the Spotify
import. It is also frozen — no new candidates will be added there.

---

## What Remains Active

Everything in the structured catalog pipeline is active and should be maintained:

- `content/releases/`, `content/artists/`, `content/site.yaml`
- `mrp/schemas/release.schema.json`, `mrp/schemas/artist.schema.json`
- `mrp/cli/main.py` and all enrichment commands (`enrich-youtube`,
  `enrich-apple-music`, `enrich-links`)
- `mrp/core/release.py` (release creation)
- `site/src/pages/releases/`, `site/src/pages/artists/`
- The build, stage, verify, publish, and deploy pipeline

The clone serving layer (`CloneLayout.astro`, `[...slug].astro`, WP
stylesheets) is also active in the sense that it serves live pages — but it
should not receive new feature work.
