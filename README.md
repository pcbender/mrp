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
`build`, and `stage`. The build command validates content, runs the Astro
static site build, copies output to `builds/staging/{build-id}/`, and writes a
JSON report under `reports/build/`. The stage command deploys a build to a
configured local target after verifying the target contains `.allow-deploy`.
