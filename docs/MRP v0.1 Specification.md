# Maricopa Release Publisher — MRP v0.1 Specification

## Purpose

Maricopa Release Publisher, abbreviated **MRP**, is a local, agent-friendly publishing system for Maricopa Records.

MRP is not a traditional CMS. It is a structured release-publishing pipeline that turns artist, song, album, asset, and metadata records into a static website, verifies the result, stages it for review, and promotes it to production only after passing explicit checks.

The primary user is an AI/human development workflow running inside WSL2. The system must be usable by CP or another agent without requiring a web admin UI.

---

# 1. Problem Statement

Maricopa Records releases songs, albums, videos, lyrics, cover art, streaming links, and related promotional content on an ongoing basis.

The website needs to be updated repeatedly and safely, but a normal CMS adds the wrong complexity:

* database-backed live editing
* authentication and users
* plugin/security maintenance
* browser-based admin UI
* fragile manual publishing steps
* hard-to-verify production state

The required system is simpler:

> Given a structured description of a new release, MRP should update the website, stage it, verify it, and publish it safely with minimal or no human intervention.

MRP must support both human commands and agentic automation.

---

# 2. Core Principle

The source of truth is structured content in the repository.

The website is generated from that content.

Production is never edited directly.

```text
release manifest + assets
        ↓
MRP validation
        ↓
static site build
        ↓
staging deployment
        ↓
verification report
        ↓
approval / auto-approval gate
        ↓
production deployment
        ↓
rollback snapshot
```

---

# 3. Goals

## 3.1 Functional Goals

MRP shall:

1. Store artist, release, song, asset, and site metadata in structured files.
2. Generate static website pages from that content.
3. Provide a local CLI suitable for humans and AI agents.
4. Support staging deployment before production deployment.
5. Verify generated and deployed pages before promotion.
6. Require explicit approval or passing policy before production.
7. Support rollback to the previous known-good production build.
8. Preserve and reuse imported Maricopa Records website assets/content.
9. Support downstream automation hooks for later workflows.
10. Avoid requiring WordPress, ProcessWire, or another live CMS.

## 3.2 Non-Goals for v0.1

MRP v0.1 shall not require:

1. A browser-based admin UI.
2. User login/authentication.
3. A production database.
4. A dynamic application server.
5. GitHub as the mandatory publishing middleman.
6. Fully automated ingestion from streaming services.
7. Complex editorial workflows.
8. Multi-user permissions.
9. Payment, licensing, or e-commerce logic.

---

# 4. Recommended Technology Shape

The preferred stack is:

```text
Static site generator: Astro
Content format: YAML or JSON
MRP CLI: Python or Node
Deployment: local copy for v0.1; rsync or SFTP later
Contact form: tiny PHP endpoint
```

For this repository, CP should create a clean Astro-based site shell in
`/home/mrose/mrp`. The source files in `~/website-migration` are source inputs,
not the target implementation repository.

The initial source of truth is a combination of the WordPress WXR export and the
captured downloaded assets:

* WXR content is authoritative for imported content records.
* Downloaded assets under `~/website-migration` may be referenced and reused.
* Large imported assets should not be copied into this repository by default.
* MRP v0.1 should build a simple redesigned site, not reproduce the full export.

---

# 5. Repository Layout

Target layout:

```text
repo/
  MRP-SPEC-v0.1.md

  mrp/
    cli/
    core/
    deploy/
    verify/
    schemas/
    templates/
    hooks/

  site/
    src/
      pages/
      layouts/
      components/
      content/
    public/
      assets/
    package.json
    astro.config.mjs

  content/
    site.yaml
    artists/
      pcbender.yaml
      stab.yaml
      4castle.yaml
      lingua-aeternum.yaml
    releases/
      triati.yaml
      aletheion.yaml
    assets/
      manifest.yaml

  assets/
    source/
      covers/
      audio/
      video/
      images/
    processed/

  builds/
    staging/
    production/
    archive/

  deploy/
    targets.yaml
    .allow-deploy.example

  reports/
    validation/
    build/
    verification/
    deployment/
    approval/
    rollback/
    import/

  scripts/
    mrp
```

The exact layout may be adjusted, but the separation should remain:

* `content/` = source content
* `assets/` = repo-local source/processed media for new releases
* `site/` = static website implementation
* `mrp/` = publisher logic
* `builds/` = generated artifacts
* `reports/` = machine-readable reports
* `deploy/` = deployment configuration
* `~/website-migration` = read-only imported website source and asset cache

---

# 6. Content Model

## 6.1 Site Metadata

Example: `content/site.yaml`

```yaml
site:
  name: Maricopa Records
  tagline: Moving Music Forward
  secondary_tagline: If You Feel, It's Real
  canonical_url: https://www.maricoparecords.com
  default_artist: PCBender
  label_name: Maricopa Records
  publisher_name: Maricopa Publishing
  contact_email: contact@maricoparecords.com
  timezone: America/Phoenix
```

## 6.2 Artist Record

Example: `content/artists/pcbender.yaml`

```yaml
artist:
  id: pcbender
  name: PCBender
  sort_name: PCBender
  type: solo
  label: Maricopa Records
  default_publisher: Maricopa Publishing
  bio_short: ""
  bio_long: ""
  image: assets/artists/pcbender/profile.jpg
  links:
    website:
    spotify:
    apple_music:
    youtube:
    bandcamp:
    instagram:
  visibility: public
```

Required fields:

```text
artist.id
artist.name
artist.visibility
```

## 6.3 Release Record

MRP uses two release content models in v0.1:

* `song`: one song/single. This is also published as an album object by Spotify
  and similar services, but MRP treats it as the single-song model.
* `album`: a multi-track release. `release.release_type` distinguishes `ep`
  from `album`; an EP normally contains 2 to 6 songs.

Example album/EP record: `content/releases/triati.yaml`

```yaml
release:
  id: triati
  slug: triati
  title: Triaτί
  artist_id: pcbender
  release_type: album
  status: draft
  release_date: 2026-06-21
  label: Maricopa Records
  publisher: Maricopa Publishing
  upc:
  catalog_number:
  cover_image: assets/releases/triati/cover.jpg
  hero_image:
  summary: ""
  description: ""
  credits:
    primary_artist: PCBender
    songwriter: Michael Anthony Rose
    producer:
    mastering:
  links:
    spotify:
    apple_music:
    youtube_music:
    bandcamp:
    soundcloud:
    landing_page:
  seo:
    title: Triaτί by PCBender
    description: New album from PCBender on Maricopa Records.
  tracks:
    - number: 0
      title: Apa
      slug: apa
      isrc:
      duration:
      explicit: false
      preview_audio:
      lyrics_excerpt:
    - number: 1
      title: Aiteō
      slug: aiteo
      isrc:
      duration:
      explicit: false
      preview_audio:
      lyrics_excerpt:
```

Example song/single record: `content/releases/circuiting.yaml`

```yaml
release:
  id: circuiting
  slug: circuiting
  title: Circuiting
  artist_id: pcbender
  model: song
  release_type: single
  status: draft
  release_date:
  label: Maricopa Records
  publisher: Maricopa Publishing
  cover_image: assets/releases/circuiting/cover.jpg
  summary: ""
  description: ""
  credits:
    primary_artist: PCBender
    songwriter: Michael Anthony Rose
  links:
    spotify:
    apple_music:
    youtube_music:
    landing_page:
  seo:
    title: Circuiting by PCBender
    description: Circuiting by PCBender on Maricopa Records.
  song:
    title: Circuiting
    slug: circuiting
    isrc:
    duration:
    explicit: false
    preview_audio:
    lyrics_excerpt:
```

Required fields for publishable releases:

```text
release.id
release.slug
release.title
release.artist_id
release.model
release.release_type
release.status
release.release_date
release.cover_image
release.seo.title
release.seo.description
```

Valid release model/type combinations:

```text
model=song, release_type=single
model=album, release_type=ep
model=album, release_type=album
```

## 6.4 Release Status Values

Valid values:

```text
draft
staged
verified
approved
live
failed
archived
```

Meaning:

* `draft`: content exists but is not publishable
* `staged`: deployed to staging
* `verified`: staging passed automated checks
* `approved`: allowed to publish to production
* `live`: deployed to production
* `failed`: attempted operation failed
* `archived`: intentionally retired or hidden from primary listings

Release status is persisted in the content record. Commands that change publish
state, such as `stage`, `approve`, `publish`, and `rollback`, should mutate the
structured content record only after their required checks pass.

## 6.5 Asset Manifest

Example: `content/assets/manifest.yaml`

```yaml
assets:
  - id: triati-cover
    path: assets/releases/triati/cover.jpg
    type: image
    usage:
      - release_cover
      - social_preview
    required: true
    alt: Triaτί album cover by PCBender
```

---

# 7. Generated Pages

MRP/site build should generate at minimum:

```text
/
/artists/
/artists/{artist-slug}/
/releases/
/releases/{release-slug}/
/contact/
/about-us/
/catalog/
/sitemap.xml
/feed.xml or /rss.xml
```

The contact page should include a simple PHP form submission endpoint. It should
not require WordPress, WooCommerce, a database, or a dynamic application server.

Homepage requirements:

* show latest release
* show featured artists
* show recent releases
* preserve Maricopa Records branding
* include contact path or email link

Release page requirements:

* title
* artist
* release type
* cover image
* release date
* description/summary
* track list
* streaming links when available
* label/publisher/credits
* SEO metadata
* social preview image

Artist page requirements:

* artist name
* image if available
* short bio
* release list
* external links

---

# 8. MRP CLI

The CLI executable should be callable as:

```bash
mrp <command> [options]
```

A repo-local wrapper may be placed at:

```bash
scripts/mrp
```

or installed as:

```bash
mrp
```

## 8.1 Required CLI Commands

### `mrp init`

Initialize MRP structure in an existing imported site repository.

```bash
mrp init
```

Expected behavior:

* create required directories if missing
* create default config files
* create example deploy target file
* create initial reports directory
* do not overwrite existing files unless `--force` is provided

---

### `mrp inspect`

Inspect current repository state.

```bash
mrp inspect
```

Outputs:

* detected site framework
* content record count
* artist count
* release count
* asset count
* known deployment targets
* warnings about missing config/assets

Support JSON:

```bash
mrp inspect --json
```

---

### `mrp validate`

Validate content and asset references.

```bash
mrp validate
mrp validate --release triati
mrp validate --json
```

Validation must check:

* required fields
* valid YAML/JSON syntax
* duplicate IDs/slugs
* missing referenced artist IDs
* missing asset files
* invalid release status
* invalid dates
* broken internal content references
* missing SEO fields for publishable releases

Output report:

```text
reports/validation/{timestamp}.json
```

---

### `mrp build`

Build the static website.

```bash
mrp build
mrp build --release triati
```

Expected behavior:

* validate before building unless `--skip-validate`
* run the static site build
* place output in deterministic build directory
* write build manifest

Output:

```text
builds/staging/{build-id}/
reports/build/{build-id}.json
```

---

### `mrp stage`

Deploy a build to staging.

```bash
mrp stage
mrp stage --build {build-id}
mrp stage --target dreamhost-staging
```

Expected behavior:

* refuse to deploy if build is invalid
* verify target contains `.allow-deploy`
* deploy via configured adapter
* write deployment report
* update release status to `staged` only if deployment succeeds

---

### `mrp verify`

Verify staging or production.

```bash
mrp verify --target staging
mrp verify --target production
mrp verify --release triati
mrp verify --json
```

Verification must check:

* expected URLs return success
* homepage loads
* release page loads
* artist page loads
* sitemap exists
* RSS/feed exists if enabled
* internal links resolve
* required images exist
* no obvious placeholder values remain
* canonical URLs are correct for target
* production safety marker was not violated

Output:

```text
reports/verification/{timestamp}.json
```

---

### `mrp approve`

Mark a verified release/build as approved.

```bash
mrp approve --release triati
mrp approve --build {build-id}
```

Approval rules:

* may only approve if latest verification passed
* approval should write an approval record
* approval may be human-issued or policy-issued

Approval record:

```text
reports/approval/{release-id}-{timestamp}.json
```

---

### `mrp publish`

Promote verified/approved build to production.

```bash
mrp publish --release triati
mrp publish --build {build-id}
mrp publish --auto-approve
```

Expected behavior:

* refuse if validation failed
* refuse if staging verification failed
* refuse if not approved unless `--auto-approve` policy passes
* archive current production state if possible
* deploy to production target
* verify production
* update release status to `live` only after production verification succeeds

---

### `mrp rollback`

Rollback production to previous known-good build.

```bash
mrp rollback
mrp rollback --to {build-id}
```

Expected behavior:

* list rollback candidate if no target provided
* require explicit confirmation unless `--yes`
* verify target contains `.allow-deploy`
* restore archived build
* verify production after rollback
* write rollback report

---

### `mrp release create`

Create a new release manifest from a template.

```bash
mrp release create --artist pcbender --title "Triaτί" --type album
```

Expected behavior:

* generate slug
* create release YAML
* create asset directory
* create placeholder fields
* do not overwrite existing release

---

### `mrp status`

Show release/publishing status.

```bash
mrp status
mrp status --release triati
mrp status --json
```

Should report:

* content status
* validation status
* latest build
* staging deployment status
* latest verification result
* approval status
* production/live status
* rollback availability

---

# 9. Deploy Targets

Example: `deploy/targets.yaml`

```yaml
targets:
  local-staging:
    type: local
    path: builds/local-staging
    require_marker: true

  local-production:
    type: local
    path: builds/local-production
    require_marker: true
```

MRP v0.1 deploys only to local staging and local production targets. Remote
DreamHost-style rsync/SFTP deployment is deferred until after the local flow is
working end to end.

No secrets should be committed.

Credentials should be provided by:

```text
local ignored config
agent runtime
```

Add to `.gitignore`:

```text
deploy/targets.local.yaml
.env
.env.*
```

---

# 10. Safety Requirements

## 10.1 Deploy Marker

Every deploy target must contain:

```text
.allow-deploy
```

MRP must refuse deployment if the marker is absent.

Marker content example:

```text
MARICOPA_RECORDS_DEPLOY_TARGET=staging
```

For production:

```text
MARICOPA_RECORDS_DEPLOY_TARGET=production
```

MRP must verify that the marker target matches the intended target.

## 10.2 No Blind Delete

For future remote adapters, if using `rsync --delete`, MRP must:

1. verify marker exists
2. verify destination path is not empty root or home
3. verify path contains expected domain name or configured safe path
4. perform dry-run first unless disabled
5. write deploy plan to report before executing

## 10.3 Production Archive

Before production deployment, MRP should archive the current production build if possible.

Minimum acceptable archive:

```text
builds/archive/production-{timestamp}/
```

Better archive:

```text
remote snapshot pulled back before deploy
```

## 10.4 Machine-Readable Reports

Every major operation must write JSON:

```text
reports/validation/
reports/build/
reports/deployment/
reports/verification/
reports/approval/
reports/rollback/
reports/import/
```

Agents must be able to parse success/failure without scraping terminal prose.

---

# 11. Verification Policy

A build may be considered verified only if:

```text
content validation passed
static build passed
staging deployment passed
required staging URLs passed
required assets exist
required metadata exists
internal link check passed
sitemap generated
no missing release cover
no missing artist reference
no unresolved placeholder tokens
```

Forbidden placeholder patterns:

```text
TODO
TBD
FIXME
lorem ipsum
example.com
INSERT_
PLACEHOLDER
```

Allow override only through explicit config:

```yaml
verification:
  allow_placeholders:
    - "TBD streaming links"
```

---

# 12. Auto-Approval Policy

MRP may support `--auto-approve`.

Auto-approval is allowed only when:

1. release status is `verified`
2. all required checks passed
3. no high-severity warnings exist
4. deployment target is production
5. production marker is valid
6. rollback candidate exists or production archive succeeded
7. release record allows auto-publish

Example release setting:

```yaml
release:
  status: verified
  automation:
    allow_auto_publish: true
```

Default should be:

```yaml
allow_auto_publish: false
```

---

# 13. Downstream Hooks

MRP should reserve a hook system for later workflows.

Example:

```yaml
hooks:
  after_stage:
    - scripts/hooks/generate-social-preview.sh
  after_publish:
    - scripts/hooks/ping-search-engines.sh
    - scripts/hooks/create-release-summary.sh
```

v0.1 hook requirements:

* hooks are optional
* hooks are disabled by default
* hooks must be explicitly enabled
* hook output must be logged
* hook failure should block publish only if marked required

Example:

```yaml
hooks:
  after_publish:
    - name: notify
      command: scripts/hooks/notify.sh
      required: false
```

---

# 14. Agentic Operation Requirements

MRP must be friendly to CP/agent use.

Commands should support:

```bash
--json
--dry-run
--yes
--release
--build
--target
--no-color
```

Commands must:

* avoid interactive prompts unless necessary
* provide deterministic output
* write structured reports
* return meaningful exit codes
* fail closed on deploy/publish uncertainty

Exit code convention:

```text
0 success
1 validation/build/verification failure
2 configuration error
3 unsafe operation refused
4 deployment failure
5 unexpected runtime error
```

---

# 15. Initial Import Requirements

The source import files live in `~/website-migration`. MRP itself is implemented
in `/home/mrose/mrp`.

MRP should include an import normalization step.

Command:

```bash
mrp import-site
```

Expected behavior:

* scan WXR content, normalized import artifacts, captured HTML, and captured assets
* identify pages, images, audio, and metadata
* treat WXR content as authoritative when sources disagree
* map assets from `~/website-migration` without copying large media into this repo
* generate starter artist/release records when obvious
* generate a simple curated v0.1 site, not a full clone of the WordPress export
* exclude WooCommerce products, cart, checkout, account pages, and payment logic
* exclude imported form submissions and feedback records
* produce an import report
* do not delete original imported source

Output:

```text
reports/import/{timestamp}.json
content/import-review/
```

This step does not need to be perfect. It should create a usable inventory and allow CP/human review.

---

# 16. Acceptance Definition for MRP v0.1

MRP v0.1 is complete when:

1. `mrp init` initializes the repo safely.
2. At least one existing artist record exists.
3. At least one existing release record exists.
4. `mrp validate` produces a JSON validation report.
5. `mrp build` generates a static website.
6. Homepage, artist page, and release page render correctly.
7. `mrp stage` deploys to a local staging target.
8. `mrp verify --target staging` passes.
9. `mrp approve` records approval.
10. `mrp publish` deploys to a local production target.
11. `mrp rollback` restores the previous production build.
12. All major commands support `--json`.
13. Unsafe deploy targets are refused.
14. Basic documentation exists in `README.md`.

---

# 17. Work Packets

## MRP-001 — Repository Survey and Implementation Plan

### Objective

Inspect the imported Maricopa Records repository and produce a concrete implementation plan.

### Tasks

1. Identify current repo structure.
2. Identify imported assets and content.
3. Identify whether a static site framework already exists.
4. Recommend whether to preserve existing framework or create Astro shell.
5. Document detected constraints.
6. Create `docs/MRP-IMPLEMENTATION-PLAN.md`.

### Acceptance Criteria

* Plan names the chosen site framework.
* Plan identifies source asset directories.
* Plan identifies content migration approach.
* Plan lists risks and assumptions.
* No destructive changes are made.

---

## MRP-002 — Create MRP Directory Structure

### Objective

Add the baseline MRP structure without changing the live site.

### Tasks

1. Create `mrp/`, `content/`, `assets/`, `deploy/`, `reports/`, and `builds/` as needed.
2. Add `.gitkeep` files where useful.
3. Add `.gitignore` entries for local secrets and generated reports/builds if appropriate.
4. Add `deploy/.allow-deploy.example`.
5. Add starter `content/site.yaml`.

### Acceptance Criteria

* Directory structure exists.
* No imported source files are deleted.
* Secrets are not committed.
* `content/site.yaml` validates as YAML.

---

## MRP-003 — Define Content Schemas

### Objective

Create machine-readable schemas for site, artist, release, and asset records.

### Tasks

1. Add schema files under `mrp/schemas/`.
2. Define required fields.
3. Define status enum.
4. Define allowed release types.
5. Define validation error format.
6. Add sample valid records.

### Acceptance Criteria

* Schemas exist for site, artist, release, and asset manifest.
* Invalid sample records fail validation.
* Valid sample records pass validation.
* Validation errors include file path, field, severity, and message.

---

## MRP-004 — Implement MRP CLI Skeleton

### Objective

Create the base CLI with command routing.

### Tasks

1. Choose Python or Node implementation.
2. Add executable entry point.
3. Implement command parser.
4. Add global flags:

   * `--json`
   * `--dry-run`
   * `--no-color`
   * `--repo`
5. Implement placeholder commands:

   * `init`
   * `inspect`
   * `validate`
   * `build`
   * `stage`
   * `verify`
   * `approve`
   * `publish`
   * `rollback`
   * `status`

### Acceptance Criteria

* CLI runs from repo root.
* Unknown commands fail cleanly.
* `--json` returns valid JSON for implemented commands.
* Exit codes follow the spec.
* README includes basic CLI usage.

---

## MRP-005 — Implement `mrp inspect`

### Objective

Allow CP to understand repo state programmatically.

### Tasks

1. Detect content directories.
2. Count artists/releases/assets.
3. Detect site framework if possible.
4. Detect deploy config presence.
5. Detect latest reports.
6. Support JSON output.

### Acceptance Criteria

* `mrp inspect` prints useful human output.
* `mrp inspect --json` returns valid JSON.
* Missing optional components are warnings, not crashes.

---

## MRP-006 — Implement Content Validation

### Objective

Validate site, artist, release, and asset records.

### Tasks

1. Parse YAML/JSON content files.
2. Validate required fields.
3. Validate duplicate IDs/slugs.
4. Validate artist references.
5. Validate asset paths.
6. Validate release status.
7. Validate publishable SEO fields.
8. Write JSON validation report.

### Acceptance Criteria

* `mrp validate` works.
* `mrp validate --release <id>` works.
* Missing cover image fails for publishable release.
* Missing artist reference fails.
* Report written to `reports/validation/`.
* JSON output is parseable.

---

## MRP-007 — Normalize Existing Imported Content

### Objective

Inventory imported Maricopa Records content and generate starter records.

### Tasks

1. Implement `mrp import-site`.
2. Scan imported HTML/content/assets.
3. Identify likely artist pages, release pages, images, and media.
4. Generate draft YAML records under `content/import-review/`.
5. Copy or map assets without deleting originals.
6. Write import report.

### Acceptance Criteria

* Import command does not destroy source files.
* Import report lists discovered pages/assets.
* At least one artist/release candidate is generated if content supports it.
* Ambiguous data is marked for review, not guessed as final.

---

## MRP-008 — Create Site Shell

### Objective

Establish the static site foundation.

### Tasks

1. If no suitable framework exists, create Astro site under `site/`.
2. Add layouts:

   * base layout
   * homepage layout
   * artist layout
   * release layout
3. Add components:

   * header
   * footer
   * release card
   * artist card
   * streaming links
   * SEO head
4. Preserve existing visual identity where practical.

### Acceptance Criteria

* Site builds locally.
* Homepage renders.
* Layout does not require server-side runtime.
* Imported assets can be referenced from the site.

---

## MRP-009 — Generate Pages from Content

### Objective

Connect structured content to static page generation.

### Tasks

1. Load artist records.
2. Load release records.
3. Generate artist index.
4. Generate artist detail pages.
5. Generate release index.
6. Generate release detail pages.
7. Generate homepage latest-release block.
8. Generate sitemap.
9. Generate RSS/feed if practical.

### Acceptance Criteria

* Artist pages are generated from content files.
* Release pages are generated from content files.
* Missing draft releases are hidden unless preview mode is enabled.
* Homepage reflects latest public release.
* Sitemap exists.

---

## MRP-010 — Implement `mrp build`

### Objective

Provide one command to validate and build the site.

### Tasks

1. Run validation before build.
2. Call static site generator.
3. Copy output to `builds/staging/{build-id}/`.
4. Write build manifest.
5. Support `--release`.
6. Support `--skip-validate`.

### Acceptance Criteria

* `mrp build` creates a build directory.
* Build ID is deterministic enough to trace.
* Failed validation blocks build by default.
* Build report is written.
* Exit code is correct.

---

## MRP-011 — Add Local Deployment Adapter

### Objective

Support safe local staging/production deploys before remote deployment.

### Tasks

1. Implement deploy target config parser.
2. Implement local copy adapter.
3. Require `.allow-deploy` marker.
4. Refuse unsafe target paths.
5. Write deployment report.
6. Support dry-run.

### Acceptance Criteria

* `mrp stage --target local-staging` works.
* Missing marker blocks deployment.
* Deployment report is written.
* Dry-run shows intended changes without copying.

---

## MRP-012 — Implement Staging Verification

### Objective

Verify generated/deployed site before approval.

### Tasks

1. Implement `mrp verify --target staging`.
2. Support local filesystem verification.
3. Check required files.
4. Check generated release pages.
5. Check generated artist pages.
6. Check sitemap.
7. Scan for placeholder tokens.
8. Write verification report.

### Acceptance Criteria

* Verification passes on valid staged build.
* Missing release page fails verification.
* Missing cover image fails verification.
* Placeholder token fails or warns according to severity.
* JSON report is written.

---

## MRP-013 — Implement Approval Records

### Objective

Allow verified builds/releases to be approved.

### Tasks

1. Implement `mrp approve`.
2. Require latest verification success.
3. Write approval JSON.
4. Track release/build approval status.
5. Support `--json`.

### Acceptance Criteria

* Unverified release cannot be approved.
* Verified release can be approved.
* Approval record includes timestamp, release ID, build ID, and mode.
* Approval can be read by `mrp status`.

---

## MRP-014 — Implement Production Publish

### Objective

Promote approved builds to production safely.

### Tasks

1. Implement `mrp publish`.
2. Require approved or valid auto-approval.
3. Archive current production target if possible.
4. Deploy to production target.
5. Verify production after deploy.
6. Mark release live only after verification passes.
7. Write publish report.

### Acceptance Criteria

* Publish refuses unapproved build.
* Publish refuses missing production marker.
* Publish writes archive or records why archive was unavailable.
* Production verification runs automatically.
* Release status updates only after successful verification.

---

## MRP-015 — Implement Rollback

### Objective

Restore previous production build.

### Tasks

1. Track production deployment history.
2. Implement rollback candidate listing.
3. Implement rollback to previous build.
4. Require marker validation.
5. Verify production after rollback.
6. Write rollback report.

### Acceptance Criteria

* `mrp rollback` restores previous production build locally.
* `mrp rollback --to <build-id>` works if build exists.
* Unsafe rollback target is refused.
* Verification runs after rollback.

---

## MRP-016 — Deferred Remote Deployment Adapter

### Objective

Reserve the post-v0.1 work required to support DreamHost-style SSH/rsync
deployment after local staging, local production, verification, and rollback are
working end to end.

### Tasks

1. Do not implement rsync/SFTP deployment in v0.1.
2. Keep deploy configuration shaped so a future remote adapter can be added.
3. Document remote deployment as a v0.2 candidate.
4. Preserve marker validation requirements for future remote targets.

### Acceptance Criteria

* v0.1 remains local-only.
* Remote deployment requirements are documented but not required for v0.1 acceptance.
* Local deploy code does not assume remote credentials or network access.

---

## MRP-017 — Add Release Creation Command

### Objective

Make adding new songs/albums fast and agent-friendly.

### Tasks

1. Implement `mrp release create`.
2. Generate slug from title.
3. Create release YAML.
4. Create asset folder.
5. Add template track structure for album/EP.
6. Refuse overwrite.

### Acceptance Criteria

* New release manifest is created.
* Required placeholder fields are clearly marked.
* Generated file passes draft validation.
* Existing release is not overwritten.

---

## MRP-018 — Add Status Command

### Objective

Give CP a single command to understand publish state.

### Tasks

1. Implement `mrp status`.
2. Show release state.
3. Show latest validation/build/stage/verify/approval/publish reports.
4. Support release filtering.
5. Support JSON output.

### Acceptance Criteria

* `mrp status` is useful to a human.
* `mrp status --json` is useful to an agent.
* Unknown release fails cleanly.

---

## MRP-019 — Documentation Pass

### Objective

Make the system usable by CP and Michael.

### Tasks

1. Add `README.md`.
2. Add `docs/CONTENT-MODEL.md`.
3. Add `docs/DEPLOYMENT.md`.
4. Add `docs/AGENT-USAGE.md`.
5. Include happy-path workflow.
6. Include rollback workflow.
7. Include adding-new-release workflow.

### Acceptance Criteria

* Docs explain local staging.
* Docs explain production publish.
* Docs explain required deploy markers.
* Docs include example release YAML.
* Docs include safe command examples.

---

## MRP-020 — End-to-End v0.1 Test

### Objective

Prove the full MRP flow.

### Tasks

1. Create or select one test release.
2. Validate content.
3. Build static site.
4. Stage locally.
5. Verify staging.
6. Approve build.
7. Publish locally.
8. Verify production.
9. Rollback.
10. Verify rollback.

### Acceptance Criteria

The following sequence succeeds:

```bash
mrp inspect
mrp validate
mrp build
mrp stage --target local-staging
mrp verify --target staging
mrp approve --release TEST_RELEASE
mrp publish --release TEST_RELEASE --target local-production
mrp verify --target production
mrp rollback --yes
```

Final report should summarize:

```text
validation: passed
build: passed
stage: passed
staging verification: passed
approval: recorded
publish: passed
production verification: passed
rollback: passed
```

---

# 18. Suggested Build Order

Recommended CP sequence:

```text
MRP-001  Survey and plan
MRP-002  Directory structure
MRP-003  Schemas
MRP-004  CLI skeleton
MRP-005  Inspect
MRP-006  Validate
MRP-007  Import normalization
MRP-008  Site shell
MRP-009  Page generation
MRP-010  Build
MRP-011  Local deploy
MRP-012  Verify
MRP-013  Approve
MRP-014  Publish
MRP-015  Rollback
MRP-017  Release create
MRP-018  Status
MRP-019  Docs
MRP-020  End-to-end test
```

MRP-016 remote deployment is deferred until after v0.1 local publishing works.

Stop after each packet and report:

```text
Packet completed
Files changed
Commands run
Tests run
Known issues
Next recommended packet
```

---

# 19. CP Operating Instructions

CP should follow these rules:

1. Do not delete imported website assets/content unless explicitly instructed.
2. Prefer additive migration over destructive rewrite.
3. Keep production deployment disabled until local staging/publish works.
4. Never deploy to a path without `.allow-deploy`.
5. Keep commands agent-friendly and scriptable.
6. Prefer simple, boring implementation over clever abstraction.
7. Keep all reports machine-readable.
8. Do not require GitHub Actions for v0.1.
9. Do not require a web admin UI.
10. Optimize for safe repeatable release publishing.
11. Use Canto delegation for bounded work packets where practical.
12. Keep `/home/mrose/mrp` as the implementation repository.
13. Treat `~/website-migration` as read-only source input and asset cache.

---

# 20. v0.2 Candidates

After v0.1 works, consider:

1. Remote DreamHost staging/production deployment.
2. Social post generation.
3. Streaming-link enrichment.
4. YouTube/video embed enrichment.
5. LANDR/Amuse metadata import.
6. Open Graph image generation.
7. JSON feed for agents.
8. Public catalog API.
9. Integration with Canto as a reusable capability.

---

# 21. Final v0.1 Definition

MRP v0.1 is successful when Michael can give CP a new release manifest and assets, then CP can run:

```bash
mrp validate
mrp build
mrp stage
mrp verify --target staging
mrp approve --release RELEASE_ID
mrp publish --release RELEASE_ID
```

and the Maricopa Records website is updated safely, visibly, and reversibly without requiring a traditional CMS admin interface.
