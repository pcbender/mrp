# Deployment

MRP v0.1 deploys only to local filesystem targets. Remote SSH, rsync, and SFTP
deployment are deferred to v0.2.

Generated site output is written outside the repository. Set
`MRP_SITE_OUT_ROOT` to override the default:

```bash
export MRP_SITE_OUT_ROOT="$HOME/astro-sites/maricoparecords"
```

If unset, MRP uses `~/astro-sites/maricoparecords`. MRP refuses output roots
inside the Git repository.

## Targets

Committed targets live in `deploy/targets.yaml`:

```yaml
targets:
  local-staging:
    type: local
    environment: staging
    path: staging
    require_marker: true

  local-production:
    type: local
    environment: production
    path: prod
    require_marker: true
```

Relative target paths are resolved under `MRP_SITE_OUT_ROOT`, so the default
targets resolve to:

- `~/astro-sites/maricoparecords/staging`
- `~/astro-sites/maricoparecords/prod`

Local overrides may be placed in ignored `deploy/targets.local.yaml`, but MRP
still rejects targets inside the repository.

## Required Markers

Every deploy target must contain `.allow-deploy`.

Staging marker:

```text
MARICOPA_RECORDS_DEPLOY_TARGET=staging
```

Production marker:

```text
MARICOPA_RECORDS_DEPLOY_TARGET=production
```

MRP refuses deployment, publish, and rollback when the marker is missing or does
not match the target environment.

## Happy Path

```bash
scripts/mrp validate --json
scripts/mrp build --json
scripts/mrp stage --target local-staging --json
scripts/mrp verify --target staging --json
scripts/mrp approve --release circuiting --json
scripts/mrp publish --release circuiting --json
scripts/mrp verify --target production --json
scripts/mrp status --release circuiting --json
```

Generated artifacts and reports are ignored by git:

- `$MRP_SITE_OUT_ROOT/builds/staging/{build-id}/`
- `$MRP_SITE_OUT_ROOT/staging/`
- `$MRP_SITE_OUT_ROOT/prod/`
- `$MRP_SITE_OUT_ROOT/archive/`
- `reports/*/*.json`

## Rollback

Rollback requires explicit confirmation:

```bash
scripts/mrp rollback --to <build-id> --yes --json
```

Without `--to`, MRP selects the latest
`$MRP_SITE_OUT_ROOT/archive/production-*` candidate. Rollback validates the
production marker, restores files, verifies production, and writes
`reports/rollback/{timestamp}.json`.
