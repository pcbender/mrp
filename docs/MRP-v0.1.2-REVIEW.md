# MRP v0.1.2 WXR Static Clone Review

This review note covers the WordPress-export-driven static Astro clone built
from the read-only source at `/home/mrose/website-migration`.

## Regenerate Clone

From the repository root:

```bash
scripts/mrp --json clone-site --source /home/mrose/website-migration --regenerate
scripts/mrp --json clone-assets --source /home/mrose/website-migration
scripts/mrp --json clone-head --source /home/mrose/website-migration
scripts/mrp --json clone-rewrites
scripts/mrp --json validate
scripts/mrp --json build
scripts/mrp --json stage --target local-staging --build <build-id>
scripts/mrp --json verify --target local-staging
scripts/mrp --json clone-compare --target local-staging --source /home/mrose/website-migration
python3 -m pytest tests/test_e2e_v012.py
```

The E2E test writes `reports/migration/v012-wxr-static-clone-e2e.json`. JSON
reports and build outputs are intentionally ignored by git.

## Source References

- WXR export: `/home/mrose/website-migration/Assets/maricoparecords.WordPress.2026-06-17.xml`
- Captured pages: `/home/mrose/website-migration/import-artifacts/maricoparecords/live-capture/raw/pages/www.maricoparecords.com/`
- Captured assets: `/home/mrose/website-migration/import-artifacts/maricoparecords/live-capture/raw/assets/www.maricoparecords.com/`

## Current Clone Output

- Clone content: 47 WXR page records and 3 WXR post records under
  `content/clone/`.
- Rendered clone surface: 50 clone routes verified in `builds/local-staging/`.
- Mirrored WordPress assets: 559 records under
  `content/clone/assets/manifest.yaml` and `/assets/wp/`.
- Rendered asset refs: 1030 `/assets/wp/` references checked in staged HTML.
- Rewrite review: 0 unresolved local URLs; external provider links are
  intentionally preserved.
- Comparison review: 5 representative routes compared against the live capture,
  with 4 passing and 3 warnings scoped to the homepage shell.
- Exclusions: `/cart/`, `/checkout/`, `/my-account/`, `/account/`,
  `/payment/`, and `/shop/` are not rendered.

## Known Gaps

- The homepage route still renders the v0.1 shell rather than a full WordPress
  clone. `clone-compare` reports homepage warnings for headings, WordPress asset
  references, and major WordPress/Stackable container class overlap when
  comparing against `raw/pages/www.maricoparecords.com/index.html`.
- `clone-rewrites` currently reports 133 review-only missing head dependencies
  from captured inline CSS and shared WordPress head fragments. These are not
  rendered as broken `/assets/wp/` references in the staged site; strict
  verification passes with 0 errors.
- `clone-assets` reports 108 review-only missing source references from the raw
  capture, mostly wildcard plugin paths and head/runtime dependencies that were
  not captured as concrete files. The rendered clone still verifies all mirrored
  asset references.
- WooCommerce runtime dependencies and commerce paths are intentionally excluded
  from the clone. Inert WooCommerce names may remain in copied source fragments
  where they help CSS behavior or review traceability.
- Legacy v0.1.1 migrated content still includes `content/pages/trashed-2.yaml`
  and can render `/trashed-2/`. The WXR clone excludes `__trashed-2` because it
  is a trash route, so its four previously missing media references are no
  longer part of `content/clone/assets/manifest.yaml`.
- Visual comparison is currently DOM/text/asset-class based. No Playwright
  screenshot approval flow is part of v0.1.2.

## Manual Review Checklist

- Open `builds/local-staging/index.html` and confirm the existing v0.1 homepage
  still loads.
- Review representative clone routes:
  - `/artists/pcbender/`
  - `/artists/pcbender/circuiting/`
  - `/licensing-custom-songs/music-licensing/`
  - `/2025/02/26/the-future-of-ai-in-music/`
  - `/contact/`
- Confirm PCBender bio text includes `mystique` and the Circuiting page includes
  `Circuiting is not just an album`.
- Confirm internal Maricopa links resolve as local paths and streaming/provider
  links still point to external services.
- Confirm rendered WordPress media and dependencies load from `/assets/wp/`.
- Compare `reports/migration/v012-wxr-static-clone-e2e.json` against the latest
  clone-site, clone-assets, clone-head, clone-rewrites, validation, build,
  deployment, verification, and clone-compare reports.

## Post-v0.1.2 Follow-up

- Decide whether the homepage should become a WXR clone route or remain the
  native MRP shell.
- Decide whether to fetch or permanently ignore the review-only missing
  WordPress head dependencies.
- Retire or reconcile the older v0.1.1 migrated content records once the WXR
  clone is accepted as the staging source of truth.
- Add screenshot-based visual comparison if human review needs tighter parity
  with the captured WordPress pages.
