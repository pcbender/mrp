# Deployment

MRP v0.1 deploys only to local filesystem targets. Remote SSH, rsync, and SFTP
deployment are deferred to v0.2.

## Targets

Committed targets live in `deploy/targets.yaml`:

```yaml
targets:
  local-staging:
    type: local
    environment: staging
    path: builds/local-staging
    require_marker: true

  local-production:
    type: local
    environment: production
    path: builds/local-production
    require_marker: true
```

Local overrides may be placed in ignored `deploy/targets.local.yaml`.

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

- `builds/staging/{build-id}/`
- `builds/local-staging/`
- `builds/local-production/`
- `reports/*/*.json`

## Rollback

Rollback requires explicit confirmation:

```bash
scripts/mrp rollback --to <build-id> --yes --json
```

Without `--to`, MRP selects the latest `builds/archive/production-*` candidate.
Rollback validates the production marker, restores files, verifies production,
and writes `reports/rollback/{timestamp}.json`.
