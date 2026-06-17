# MRP Implementation Plan

Generated for work packet MRP-001.

## Decision Summary

- Implementation repository: `/home/mrose/mrp`.
- Imported source repository/cache: `/home/mrose/website-migration`.
- Static site framework: Astro.
- Initial site scope: simple redesigned Maricopa Records release site, not a full
  WordPress clone.
- Initial deployment scope: local staging and local production only.
- Source content authority: WordPress WXR export first, normalized/captured
  artifacts as supporting evidence.
- Large imported assets: referenced from `/home/mrose/website-migration` unless
  a later packet explicitly copies curated files.

## Current Repository Structure

The `/home/mrose/mrp` repository is currently a specification and governance
shell:

- `README.md`: placeholder repository README.
- `AGENTS.md`: graphify instructions and Canto instruction pointer.
- `docs/MRP v0.1 Specification.md`: product and packet specification.
- `.canto/`: Canto repo identity, delegation policy, Worker policy, and agent
  instructions.
- `.codex/hooks.json`: local Codex hook configuration.

There is no current MRP implementation tree, no Astro site, no content records,
no deploy configuration, no build output, and no test suite in this repository.

## Imported Source Inventory

The source files live under `/home/mrose/website-migration` and must be treated
as read-only input for v0.1 work.

Primary source files and artifacts:

- `Assets/maricoparecords.WordPress.2026-06-17.xml`: authoritative WordPress WXR
  content export.
- `import-artifacts/maricoparecords/IMPORT_REPORT.md`: import/capture summary.
- `import-artifacts/maricoparecords/defined-skills/raw/source-inventory.json`:
  normalized source inventory artifact.
- `import-artifacts/maricoparecords/defined-skills/raw/normalized-wordpress-content.json`:
  normalized WXR content artifact.
- `import-artifacts/maricoparecords/live-capture/capture-manifest.json`: live
  page and asset capture manifest.
- `import-artifacts/maricoparecords/live-capture/raw/`: captured page and asset
  files referenced by the manifest.

The import report records:

- 375 WXR items total.
- 255 published items.
- 3 draft items.
- 117 inherited attachment items.
- 54 WordPress pages.
- 117 WordPress attachment records.
- 136 feedback records.
- 8 product records.
- 52 live pages captured.
- 664 live asset records.
- 715 raw files on disk.
- Approximately 432 MB of raw captured files.
- 0 fetch failures.
- 497 external references, mainly Spotify, Apple Music, and YouTube Music.

## Imported Content Shape

The captured site contains the material needed for a simple v0.1 site:

- Homepage content.
- Artist index and artist pages.
- Artist pages for PCBender, STAB, 4Castle, and Lingua Aeternum.
- Song/release-like pages under artist paths.
- Contact and about pages.
- Licensing/custom-song pages.
- Blog posts about AI/music.
- Streaming links to external services.
- Images and other site media in the live capture.

The imported source also contains content outside v0.1 scope:

- WooCommerce products.
- Cart, checkout, account, and payment-related pages.
- Feedback/form submission records.
- WordPress theme/plugin/global-style records.
- Navigation and reusable block implementation details.

Those out-of-scope records should be inventory data only; they should not become
v0.1 features.

## Chosen Site Framework

Use Astro under `site/`.

Rationale:

- The spec explicitly approves Astro when no working static framework exists.
- The current MRP repo has no existing site implementation to preserve.
- Astro can generate the required static homepage, artist pages, release pages,
  catalog, sitemap, feed, and static assets without a runtime server.
- Astro keeps the PHP contact endpoint isolated from the static site build.

Recommended initial shape:

```text
site/
  src/
    pages/
    layouts/
    components/
  public/
    assets/
  package.json
  astro.config.mjs
```

## Content Migration Approach

Use an additive, reviewable import flow:

1. Read the WXR export as the authoritative source for imported text/content.
2. Use normalized WordPress artifacts to avoid reparsing where practical.
3. Use the live capture manifest to map page URLs to downloaded assets.
4. Generate draft review records under `content/import-review/`.
5. Promote curated records into final `content/artists/`,
   `content/releases/`, and `content/assets/manifest.yaml` in later packets.
6. Keep large media in `/home/mrose/website-migration` unless a later packet
   chooses curated copies for the site.

For release content:

- Artist pages become artist records.
- One-song release pages become `model: song`, `release_type: single`.
- Multi-track releases become `model: album`, with `release_type: ep` or
  `release_type: album`.
- Streaming links remain external URL fields.
- Missing dates, ISRCs, durations, UPCs, and catalog numbers should remain blank
  or draft until reviewed.

## Proposed v0.1 Build Sequence

Follow the packet order in the specification:

1. MRP-002: create baseline directories and starter `content/site.yaml`.
2. MRP-003: define schemas for site, artist, release, and asset manifest.
3. MRP-004: add CLI skeleton.
4. MRP-005 and MRP-006: make inspect/validate useful before import.
5. MRP-007: import normalization into review records.
6. MRP-008 and MRP-009: Astro shell and generated pages.
7. MRP-010 through MRP-015: build, local deploy, verify, approve, publish, and
   rollback.
8. MRP-017 through MRP-020: release creation, status, docs, and end-to-end test.

MRP-016 remote deployment remains deferred until after v0.1 local publishing is
working end to end.

## Detected Constraints

- Do not mutate `/home/mrose/website-migration`.
- Do not copy the full 432 MB capture into this repo.
- Do not implement WordPress, WooCommerce, payments, accounts, cart, checkout,
  or WordPress admin behavior.
- Keep deployment local-only for v0.1.
- Production-like local targets must require `.allow-deploy`.
- Major commands must write machine-readable JSON reports.
- Publish-state commands must mutate structured content only after checks pass.
- Canto delegation is enabled, but Worker command/file-path restrictions may
  require careful assignment wording and allowlisted survey commands.

## Risks

- The WXR contains page content, theme/plugin artifacts, product records, and
  feedback records mixed together; import heuristics must avoid overpromoting
  irrelevant WordPress records.
- Some release metadata may be missing or only present inside rendered HTML,
  requiring manual review before publishable records are complete.
- Large assets are external to this repo, so build code needs stable references
  or a curated copy step before the site can be fully portable.
- The source site has song pages under artist paths; MRP will need a stable URL
  decision for generated release pages and any compatibility redirects.
- The PHP contact endpoint must be deployed carefully so it does not turn the
  project into a dynamic application server.
- Canto Workers failed initial MRP-001 attempts because of command/path
  enforcement; future delegated packets should avoid absolute `read_file` paths
  and include explicit allowed commands.

## Assumptions

- `/home/mrose/mrp` remains the canonical implementation repository.
- `/home/mrose/website-migration` remains available locally during v0.1 import
  and build work.
- Astro is acceptable as a new site shell.
- The initial v0.1 site can be curated from existing artists and releases rather
  than exhaustively importing every WordPress page.
- Local production is a filesystem target, not a remote host.
- Remote DreamHost deployment, social automation, enrichment, and catalog APIs
  are post-v0.1 work.

## MRP-001 Acceptance Check

- Chosen framework: Astro.
- Source asset/content directories identified.
- Migration approach documented.
- Risks and assumptions documented.
- No imported source files are modified.
