# MRP v0.1.1 Migration Review

This review note covers the one-off full-site staging migration from the
read-only source at `/home/mrose/website-migration`.

## Regenerate Staging

From the repository root:

```bash
scripts/mrp --json migrate-site --source /home/mrose/website-migration
scripts/mrp --json validate
scripts/mrp --json build
scripts/mrp --json stage --target local-staging
scripts/mrp --json verify --target staging
python3 -m pytest tests/test_e2e_v011.py
```

The E2E test writes `reports/migration/v011-full-site-e2e.json`. JSON reports
and build outputs are intentionally ignored by git.

## Current Staging Output

- Pages: 47 content records, with rendered routes for records that contain
  migrated HTML fragments.
- Posts: 3 blog/news records, including dated compatibility aliases from
  `content/redirects.yaml`.
- Artists: 4 artist records. Only public v0.1 artists render through the
  existing artist route; migrated artist pages render through compatibility
  paths when they have HTML.
- Releases: 32 release records after duplicate/curated-record preservation.
- Assets: 37 copied referenced media files under `site/public/assets/migrated/`.
- Redirects: 52 captured public URL records in `content/redirects.yaml`.
- Exclusions: WooCommerce/product and feedback/contact-form export records are
  not rendered as content records.

## Known Gaps

- `content/pages/trashed-2.yaml` references four source media URLs that were not
  present in the capture manifest: `CFM_Revised_Transparent.png`,
  `sponsor1.jpg`, `vendor.jpg`, and `volunteer.jpg`.
- `content/pages/artists.yaml` includes a WooCommerce placeholder image URL in
  source HTML. It is reported as unsupported and excluded from migrated asset
  copy.
- Several copied PNG release images are over 5 MB. The migration report lists
  them under `assets.oversized`; these are acceptable for staging but should be
  optimized before production use.
- Generated artist and release YAML records are draft-quality metadata. Titles,
  artist sort names, credits, streaming links, ISRC/UPC/catalog fields, and
  cover assignments still need editorial review.
- Static pages with empty migrated HTML are retained as content records for
  review but are not part of the rendered migrated surface.

## Manual Review Checklist

- Open `builds/local-staging/index.html` and confirm the v0.1 homepage still
  loads.
- Review representative migrated routes:
  - `/artists/pcbender/circuiting/`
  - `/artists/4castle/distance-not-safety/`
  - `/licensing-custom-songs/music-licensing/`
  - `/the-future-of-ai-in-music/`
  - `/2025/02/26/the-future-of-ai-in-music/`
- Confirm internal Maricopa links use local paths and streaming links still
  point to external providers.
- Confirm migrated images load from `/assets/migrated/` instead of WordPress
  upload URLs.
- Confirm `/cart/`, `/checkout/`, `/my-account/`, `/account/`, `/payment/`, and
  `/shop/` are not rendered.
- Compare `reports/migration/v011-full-site-e2e.json` against the latest
  `migrate-site`, validation, build, deployment, and verification reports.

## Post-v0.1.1 Follow-up

- Decide whether migrated draft artists and releases should become canonical
  MRP records or remain one-off staging content.
- Optimize oversized copied media and replace missing `trashed-2` assets if that
  page remains in scope.
- Convert high-value WordPress fragments into native Astro components where
  long-term maintenance matters.
- Add editorial metadata for release models, release types, cover images,
  credits, and streaming links.
- Decide whether compatibility aliases should become deploy-time redirects in a
  future remote deployment packet.
