# MRP v0.1.1 Full Site Staging Migration Plan

## Objective

MRP v0.1.1 creates a local staging version of the public Maricopa Records
website from `/home/mrose/website-migration` data and assets.

This is a migration/staging utility increment, not a change to the ongoing MRP
release-publishing model. The output should feed the existing MRP validation,
build, stage, and verify commands.

## Product Boundary

In scope:

- Public website pages from the WordPress/WXR export.
- Public artist pages.
- Public release/song/album pages.
- Public blog/news-style posts from the export.
- Public media needed by the migrated pages.
- Normalized equivalents of old public URLs.
- Local staging only.
- Machine-readable migration reports.

Out of scope:

- WordPress runtime behavior.
- WordPress admin behavior.
- WooCommerce products, cart, checkout, accounts, payments, and order history.
- Feedback/form submission history.
- Remote DreamHost deployment.
- Replacing the normal `release create`, `publish`, or rollback workflows.
- Copying the entire 432 MB capture without curation.
- Contact form submission handling changes.
- Historical contact/feedback submission migration.

## Source Authority

Use `/home/mrose/website-migration` as read-only source input.

Primary authority:

- `Assets/maricoparecords.WordPress.2026-06-17.xml`

Supporting artifacts:

- `import-artifacts/maricoparecords/IMPORT_REPORT.md`
- `import-artifacts/maricoparecords/defined-skills/raw/source-inventory.json`
- `import-artifacts/maricoparecords/defined-skills/raw/normalized-wordpress-content.json`
- `import-artifacts/maricoparecords/live-capture/capture-manifest.json`
- `import-artifacts/maricoparecords/live-capture/raw/`

Rule: never mutate `/home/mrose/website-migration`.

## CLI Shape

Add a thin one-off command rather than deeply integrating this into core MRP
publishing:

```bash
scripts/mrp migrate-site --source /home/mrose/website-migration --json
scripts/mrp migrate-site --source /home/mrose/website-migration --dry-run --json
```

The command should:

- Read migration source data.
- Generate/promote staging content and curated assets.
- Write reports under `reports/migration/` or `reports/import/`.
- Leave normal publishing commands unchanged.
- Allow the existing flow to run afterward:

```bash
scripts/mrp validate --json
scripts/mrp build --json
scripts/mrp stage --target local-staging --json
scripts/mrp verify --target staging --json
```

## Proposed Output Shape

Keep migrated output ordinary MRP/site input:

```text
content/
  artists/
  releases/
  pages/
  posts/
  redirects.yaml
  assets/manifest.yaml
site/public/assets/migrated/
reports/migration/
```

New content types such as `pages/`, `posts/`, and `redirects.yaml` are limited
to full-site staging support. The ongoing release-publishing workflow should
continue to use `artists/`, `releases/`, and current build/deploy commands.

## Settled Design Decisions

- Public pages and blog/news posts will be migrated as static HTML fragments
  rendered inside Astro layouts.
- Old WordPress URLs should be normalized into the staging URL structure.
  Redirect metadata may be generated only where needed for verification or
  review, but the primary output is normalized routes.
- Migrated media should be copied into `site/public/assets/migrated/`.
- Blog/news content is in scope for v0.1.1.
- Historical feedback/contact submissions are excluded.
- Contact form submission behavior is out of scope for v0.1.1. A contact page
  may be migrated as static page content, but PHP form handling should not be
  changed in this increment.

## Acceptance Criteria

- `scripts/mrp migrate-site --dry-run --json` reports intended records/assets
  without mutating repo content.
- `scripts/mrp migrate-site --json` generates staging content/assets and a
  migration report.
- WooCommerce, account, checkout, cart, payment, and feedback records are
  excluded from rendered output.
- Existing v0.1 release-publishing tests still pass.
- `scripts/mrp validate --json` passes after migration.
- `scripts/mrp build --json` passes after migration.
- `scripts/mrp stage --target local-staging --json` passes.
- `scripts/mrp verify --target staging --json` passes.
- Staging verification covers migrated public pages, migrated blog/news posts,
  migrated assets, internal links, sitemap/feed, missing placeholders, and
  normalized old URL coverage.

## Work Packets

### MRP-101 - Migration Inventory Refresh

Objective: create an authoritative public-site inventory for v0.1.1.

Tasks:

1. Read WXR, normalized content, source inventory, import report, and capture
   manifest from `/home/mrose/website-migration`.
2. Classify records as public page, artist, release, blog/news post, attachment,
   normalized URL, excluded commerce, excluded feedback, or unsupported.
3. Write `reports/migration/{timestamp}-inventory.json`.
4. Do not write content records yet.

Acceptance:

- Inventory report counts match known source totals or explains deltas.
- Commerce/account/checkout/cart/payment/feedback exclusions are explicit.
- Source files are not modified.

### MRP-102 - Migration Schemas And Content Directories

Objective: add minimal staging-only schemas and directories for full-site pages.

Tasks:

1. Add schemas for migrated static page/post records if needed.
2. Add `content/pages/`, `content/posts/`, and `content/redirects.yaml`
   placeholders if approved.
3. Update validation to include new records without weakening release schemas.
4. Add fixtures and tests.

Acceptance:

- Existing v0.1 schemas and tests still pass.
- New page/post fixtures validate.
- Invalid page/post records fail cleanly.

### MRP-103 - Implement `mrp migrate-site --dry-run`

Objective: expose the one-off migration as a CLI planning command.

Tasks:

1. Register `migrate-site`.
2. Support `--source`, `--dry-run`, and `--json`.
3. Reuse the inventory classifier from MRP-101.
4. Report planned record and asset writes.
5. Refuse missing or invalid source paths.

Acceptance:

- Dry-run writes only a report.
- JSON output is useful to agents.
- Missing source fails with a configuration exit.

### MRP-104 - Generate Migrated Content Records

Objective: write public pages, posts, artists, releases, and redirects into repo
content.

Tasks:

1. Convert public WXR pages into static page/post fragment records.
2. Promote artist records for all public artists.
3. Promote release records for public song/album pages.
4. Generate normalized route records for old public URLs, with redirect metadata
   only where needed.
5. Preserve source provenance in generated records.
6. Keep ambiguous records in review status.

Acceptance:

- Generated records are deterministic.
- Running migration twice does not duplicate records.
- Existing curated `circuiting` record is not overwritten without an explicit
  mutation rule.
- Migration report lists created, updated, skipped, and review-needed records.

### MRP-105 - Curated Asset Copy

Objective: copy only assets required by rendered migrated pages and blog/news
posts.

Tasks:

1. Map WXR attachment URLs and captured page assets to local files.
2. Copy needed media into `site/public/assets/migrated/`.
3. Update `content/assets/manifest.yaml`.
4. Detect missing, duplicate, oversized, and unsupported assets.
5. Avoid copying the full raw capture.

Acceptance:

- Required rendered assets exist under `site/public/assets/migrated/`.
- Asset manifest validates.
- Missing assets are reported with source URL and page reference.
- Full capture is not copied wholesale.

### MRP-106 - Astro Rendering For Migrated Pages

Objective: render migrated public pages and blog/news posts through the existing
Astro site.

Tasks:

1. Add static fragment page/post loaders.
2. Add dynamic routes for migrated pages/posts.
3. Add navigation/index pages needed for the full staging site.
4. Preserve current artist/release pages.
5. Generate sitemap/feed entries for migrated content.

Acceptance:

- `npm run build` renders migrated page/post routes.
- Existing v0.1 pages still render.
- Sitemap includes migrated public URLs.
- Feed behavior is documented and tested.

### MRP-107 - Compatibility URLs And Link Rewrites

Objective: normalize old public URLs for local staging.

Tasks:

1. Normalize internal links from WordPress/captured content.
2. Generate normalized routes, plus redirect metadata only where needed for
   verification or review.
3. Rewrite media references to staged assets.
4. Preserve external links to Spotify, Apple Music, YouTube Music, and similar
   services.

Acceptance:

- Internal link verification passes for migrated pages.
- Old public URLs have normalized route coverage or explicit review metadata.
- External links are not rewritten into broken local paths.

### MRP-108 - Migration-Aware Verification

Objective: extend staging verification for the migrated full-site surface.

Tasks:

1. Verify every migrated public page and blog/news route exists.
2. Verify every required migrated asset exists.
3. Verify internal links across migrated pages.
4. Verify no forbidden placeholders remain.
5. Verify excluded record categories are not rendered.
6. Write a migration verification section in the report.

Acceptance:

- Missing migrated page or post fails verification.
- Missing migrated asset fails verification.
- Rendered WooCommerce/cart/checkout/account/payment pages fail verification.
- Verification remains compatible with v0.1 release-only workflows.

### MRP-109 - Full Site Staging E2E Test

Objective: prove the one-off migration works with the existing local pipeline.

Tasks:

1. Run migration against `/home/mrose/website-migration`.
2. Validate.
3. Build.
4. Stage to `local-staging`.
5. Verify staging.
6. Write an E2E migration report.

Acceptance:

- Full-site staging E2E passes locally.
- Report summarizes migrated pages, artists, releases, posts, assets, redirects,
  exclusions, warnings, and failures.
- Existing v0.1 E2E still passes.

### MRP-110 - Review And Cleanup

Objective: prepare v0.1.1 output for human review.

Tasks:

1. Add review docs for migrated content and known gaps.
2. Add commands for regenerating the staging migration.
3. Document manual review checklist.
4. Document what remains post-v0.1.1.

Acceptance:

- Reviewer can reproduce migration and staging commands from docs.
- Known gaps are listed with source references.
- Worktree contains no generated reports/builds intended to stay ignored.
