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
```

The MRP v0.1 CLI currently provides command routing and placeholder command
handlers. Implemented commands will keep the same entry point and global flags:

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
