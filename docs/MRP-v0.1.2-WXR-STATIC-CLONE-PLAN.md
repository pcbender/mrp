# MRP v0.1.2 WXR Static Clone Plan

## Objective

MRP v0.1.2 replaces the simplified v0.1.1 staging renderer with a WordPress
export and capture driven Astro static clone of the public Maricopa Records
site.

The source of truth for content is the WordPress WXR export:

`/home/mrose/website-migration/Assets/maricoparecords.WordPress.2026-06-17.xml`

The source of truth for static asset bytes is the live capture:

`/home/mrose/website-migration/import-artifacts/maricoparecords/live-capture/raw/assets/www.maricoparecords.com/`

Captured raw pages remain supporting evidence for route coverage, `<head>`
dependencies, page-level behavior, and visual comparison:

`/home/mrose/website-migration/import-artifacts/maricoparecords/live-capture/raw/pages/www.maricoparecords.com/`

## Non-Goals

- Do not redesign the site during this tranche.
- Do not make WordPress, PHP, MySQL, or WooCommerce runtime dependencies.
- Do not turn this into the long-term MRP publishing model.
- Do not hand-convert every WordPress block into native Astro components.
- Do not mutate the source export or live-capture artifact directories.

## Desired Result

The Astro site should look and behave like a static version of the current
WordPress public site from a content standpoint. WordPress/Stackable/Cryout
markup, classes, inline styles, media references, artist pages, release pages,
blog posts, pages, and relevant controls should be retained when they serve a
clear purpose, such as styling hooks, layout behavior, embedded SVG controls,
asset references, or review traceability. Nonfunctional WordPress scaffolding
can be simplified or omitted when doing so does not change the rendered content
or user-facing behavior.

## Source Precedence

1. WXR `content:encoded` is authoritative for page/post/body content.
2. WXR item metadata is authoritative for title, slug, type, status, dates,
   terms, and canonical link where present.
3. Live-capture page HTML is authoritative for captured route coverage and
   rendered `<head>` dependencies.
4. Live-capture `raw/assets/www.maricoparecords.com/wp-content` and
   `wp-includes` are authoritative for local asset bytes.
5. Existing v0.1 MRP release/artist content is preserved only where it does not
   conflict with the static clone objective.

## Architecture

Add a WXR-driven static clone pipeline alongside the existing MRP publishing
pipeline:

- Parse the WXR export into normalized clone records.
- Preserve `content:encoded` HTML as the primary render fragment.
- Copy captured WordPress assets into `site/public/assets/wp/`.
- Rewrite WordPress-local URLs to static local asset and route paths.
- Render clone pages through Astro routes using a minimal shell that carries the
  captured WordPress content and required styling/behavior hooks rather than the
  v0.1 design.
- Verify rendered route and asset coverage against WXR and live-capture
  manifests.

## Open Decisions

- Whether clone routes should replace the v0.1 homepage and navigation by
  default, or live under a selectable clone mode during review.
- Whether to copy all captured `wp-content` and `wp-includes` assets, or only
  referenced assets plus dependency closure from captured pages.
- Whether contact form behavior remains a static/PHP shim or is excluded from
  static clone verification.
- Whether dated blog aliases should be emitted as duplicate static pages or as
  redirect metadata for future deployment.

## Work Packets

### MRP-111 - WXR Parser And Inventory

Objective: parse the WordPress export directly and report clone inventory.

Tasks:

1. Add a WXR parser using namespace-aware XML parsing.
2. Extract item metadata: title, link, guid, post type, status, post name,
   dates, parent, menu order, terms, postmeta, attachment URL, excerpt, and
   `content:encoded`.
3. Preserve CDATA HTML without lossy normalization.
4. Classify clone records: public page, artist page, release page, blog/news
   post, attachment, menu item, excluded commerce, excluded feedback, and
   unsupported.
5. Write an inventory report comparing WXR records to live-capture pages and
   assets.

Acceptance:

- PCBender artist content includes the `mystique` paragraph from WXR.
- Inventory counts WXR records and captured routes.
- Excluded WooCommerce/feedback records are explicit.
- Parser is covered by tests using representative WXR fixtures.

### MRP-112 - Clone Content Model

Objective: store WXR-derived clone records without forcing them into the MRP
artist/release publishing schema.

Tasks:

1. Add `content/clone/pages/`, `content/clone/posts/`,
   `content/clone/assets/`, and related schemas.
2. Store route, title, source IDs, source link, post type, post status,
   canonical path, aliases, and raw `content_html`.
3. Keep current MRP `content/artists` and `content/releases` separate from clone
   records.
4. Add validation for clone records and clone asset manifest.

Acceptance:

- WXR clone records validate independently.
- Existing v0.1 MRP content validation remains compatible.
- Clone records can represent artist, release, blog, and static pages with the
  same underlying schema.

### MRP-113 - Generate Clone Records From WXR

Objective: generate static clone content records from the WXR export.

Tasks:

1. Extend or add CLI support for a WXR clone generation mode.
2. Generate clone page/post records from WXR `content:encoded`.
3. Derive canonical paths from WXR links and post names.
4. Generate aliases from captured raw page paths and dated post URLs.
5. Preserve existing generated records unless explicitly regenerated.
6. Report records created, skipped, overwritten, and requiring review.

Acceptance:

- PCBender, 4Castle, Lingua Aeternum, release pages, blog posts, and static
  pages are generated from WXR content.
- Generated content includes WXR-derived content HTML and retains
  Stackable/Gutenberg markers only where they are useful for styling, behavior,
  debugging, or review traceability.
- The command is idempotent.

### MRP-114 - WordPress Asset Mirror

Objective: mirror required captured WordPress assets into Astro public assets.

Tasks:

1. Build a URL-to-file map from
   `live-capture/raw/assets/www.maricoparecords.com/`.
2. Copy required `wp-content` and `wp-includes` assets into
   `site/public/assets/wp/`.
3. Include images, CSS, JS, fonts, theme assets, plugin assets, and WordPress
   include assets referenced by WXR content or captured pages.
4. Preserve relative path structure under `wp-content` and `wp-includes`.
5. Report copied, missing, unsupported, duplicate, and oversized assets.

Acceptance:

- `/wp-content/...` and `/wp-includes/...` references have local asset
  equivalents.
- Asset copy does not depend on network access.
- Missing assets are reported with source URL and referencing page.
- Current v0.1 assets remain available.

### MRP-115 - Head Dependency Extraction

Objective: preserve the WordPress page styling and controls needed by captured
content without treating every WordPress implementation detail as mandatory.

Tasks:

1. Parse captured raw page `<head>` sections.
2. Extract local stylesheet, script, preload, font, and inline style
   dependencies.
3. Identify shared global dependencies versus page-specific dependencies.
4. Rewrite dependency URLs to `site/public/assets/wp/`.
5. Generate a clone head manifest consumed by Astro.

Acceptance:

- Stackable/Cryout/WordPress block styling loads locally.
- Captured plugin/theme CSS and JS references are represented.
- External analytics and tracking scripts are excluded or explicitly marked for
  review.

### MRP-116 - Astro Clone Renderer

Objective: render WXR clone records through Astro while preserving the
WordPress-derived content, styling hooks, and controls that matter to the
static result.

Tasks:

1. Add Astro clone layout with captured head dependencies.
2. Add dynamic clone routes based on generated clone records.
3. Render `content_html` after URL rewriting and optional cleanup.
4. Retain WordPress classes, inline styles, SVG controls, Stackable markup, and
   block comments where they affect styling, behavior, or reviewability.
5. Prune nonfunctional WordPress scaffolding when it is safe and covered by
   tests or review fixtures.
6. Add clone navigation and index behavior based on WXR/captured menus where
   possible.

Acceptance:

- Rendered PCBender page includes the WXR bio text and controls.
- Artist, release, blog, and static pages render from WXR clone records.
- The clone route output is visually much closer to captured WordPress pages
  than the v0.1.1 simplified design.

### MRP-117 - URL And Asset Rewrites

Objective: rewrite WordPress-local URLs for static hosting.

Tasks:

1. Rewrite `https://www.maricoparecords.com/...` internal links to local clone
   routes.
2. Rewrite `/wp-content/...` and `/wp-includes/...` to `/assets/wp/...`.
3. Rewrite `srcset`, CSS `url(...)`, inline style URLs, script URLs, link URLs,
   and image URLs.
4. Preserve external links to Spotify, Apple Music, YouTube Music, Bandcamp,
   SoundCloud, email, telephone, and other offsite providers.
5. Emit explicit review metadata for unresolved local URLs.

Acceptance:

- Internal link verification passes across clone pages.
- WordPress asset URLs resolve locally.
- External streaming links are not rewritten.
- Unresolved local URLs are listed in a report.

### MRP-118 - Clone Verification

Objective: verify the static clone surface against WXR and live capture.

Tasks:

1. Verify every included WXR public route renders.
2. Verify captured public routes have rendered route coverage or review
   metadata.
3. Verify required WordPress assets exist under `site/public/assets/wp/`.
4. Verify no excluded WooCommerce/cart/checkout/account/payment pages render.
5. Verify no broken internal links remain.
6. Verify representative known content markers, including PCBender `mystique`.
7. Write a clone verification section in the report.

Acceptance:

- Missing clone page fails verification.
- Missing clone asset fails verification.
- Known WXR content markers are present in rendered HTML.
- Existing v0.1 release-only verification remains compatible.

### MRP-119 - Visual And DOM Comparison

Objective: compare rendered clone pages against captured raw pages.

Tasks:

1. Add a small set of representative comparison fixtures.
2. Compare route list, title, key headings, content markers, asset references,
   and major DOM containers.
3. Optionally add Playwright screenshots for human visual review if local
   browser tooling is available.
4. Produce a review report with pass/fail/warn details.

Acceptance:

- Representative pages show matching content markers and major DOM structures.
- Visual review can be run locally.
- Differences are documented rather than hidden.

### MRP-120 - Clone E2E And Review Docs

Objective: prove and document the corrected WXR static clone workflow.

Tasks:

1. Add an E2E test that runs WXR clone generation, asset mirror, build, stage,
   and verify.
2. Write a clone E2E report summarizing pages, posts, artists, releases,
   assets, aliases, exclusions, unresolved URLs, warnings, and failures.
3. Update review docs with exact regeneration commands.
4. Document known gaps and post-clone cleanup work.

Acceptance:

- Full clone E2E passes locally.
- Reviewer can reproduce the clone with documented commands.
- Known gaps are listed with WXR or live-capture source references.
- Existing v0.1 and v0.1.1 tests remain compatible or are explicitly updated.

## Suggested Review Order

1. Approve source precedence and non-goals.
2. Decide copy-all versus referenced-only asset mirror for `wp-content` and
   `wp-includes`.
3. Decide route mode: replace staging output by default versus clone mode during
   review.
4. Approve MRP-111 through MRP-120 packet boundaries.
