# Maricopa Release Publisher

Maricopa Release Publisher, abbreviated MRP, is a local release-publishing
pipeline for the Maricopa Records static site.

## CLI

Run the repo-local wrapper from the repository root:

```bash
scripts/mrp --help
scripts/mrp inspect
scripts/mrp inspect --json
scripts/mrp validate --json
scripts/mrp build --json
scripts/mrp stage --target local-staging --json
scripts/mrp verify --target staging --json
scripts/mrp approve --release circuiting --json
scripts/mrp publish --release circuiting --json
scripts/mrp rollback --to <build-id> --yes --json
scripts/mrp status --json
```

The MRP v0.1 CLI keeps the same entry point and global flags across commands:

```text
--json
--dry-run
--no-color
--repo
```

Registered command groups:

```text
init
inspect
validate
build
stage
verify
approve
publish
rollback
status
release create
import-site
```

Implemented commands currently include `inspect`, `validate`, `import-site`,
`build`, `stage`, `verify`, `approve`, `publish`, `rollback`, and `status`. The
build command validates content, runs the Astro static site build, copies output to
`builds/staging/{build-id}/`, and writes a JSON report under `reports/build/`.
The stage command deploys a build to a configured local target after verifying
the target contains `.allow-deploy`. The verify command checks a deployed local
target for required pages, assets, sitemap/feed files, internal links, and
placeholder tokens. The approve command records approval only after verification
passes. The publish command promotes an approved build to local production,
verifies production, and marks the release live after verification succeeds.
Rollback restores local production from an archive or specified staging build
after explicit `--yes` confirmation. Status reports the latest
build/deployment/verification/approval records.
