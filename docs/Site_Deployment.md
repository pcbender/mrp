# Site Deployment

## Repo context

This repository has two distinct parts:

- **Frozen import layer** — tools that migrated the old WordPress site into
  Astro (`migrate-site`, `import-site`, `clone-*`, `wxr.py`). These are done
  and must not be modified. Their output lives in `content/clone/` and
  `content/import-review/`.

- **Active publishing layer** — the ongoing Maricopa Records Publishing
  Management (MRP) app. New artists, releases, and content live in
  `content/artists/`, `content/releases/`, `content/pages/`, `content/posts/`.
  The MRP CLI (`scripts/mrp`) drives all build and deploy operations.

---

## Prerequisites

**Python dependencies** (once per environment):

```bash
python3 -m pip install -r requirements.txt
```

**Credentials** — all sensitive values live in `.env` at the repo root.
The MRP CLI loads `.env` automatically; no `source` or export is needed.
Required keys for deployment:

| Key | Purpose |
|-----|---------|
| `STAGING_SSH_USERNAME` | DreamHost SSH user + host (e.g. `user@host.dreamhost.com`) |
| `STAGING_DEPLOY_PATH` | Remote path for staging (e.g. `~/staging.maricoparecords.com/`) |
| `STAGING_SSH_KEY` | Path to SSH private key (e.g. `~/.ssh/dh_ed25519`) |
| `PROD_USERNAME` | DreamHost SSH user + host for production |
| `PROD_DEPLOY_PATH` | Remote path for production |
| `PROD_SSH_KEY` | Path to SSH private key for production |

**Remote `.allow-deploy` markers** — every remote target must contain a
`.allow-deploy` file. MRP SSHes to verify it before rsyncing.

Staging marker content:
```
MARICOPA_RECORDS_DEPLOY_TARGET=staging
```

Production marker content:
```
MARICOPA_RECORDS_DEPLOY_TARGET=production
```

---

## Deploy targets

Targets are defined in `deploy/targets.yaml`. All four are implemented
and operational:

| Target | Type | Destination |
|--------|------|-------------|
| `local-staging` | local copy | `~/astro-sites/maricoparecords/staging/` |
| `local-production` | local copy | `~/astro-sites/maricoparecords/prod/` |
| `remote-staging` | rsync over SSH | `~/staging.maricoparecords.com/` on DreamHost |
| `remote-production` | rsync over SSH | `~/maricoparecords.com/` on DreamHost |

`MRP_SITE_OUT_ROOT` controls the base path for local targets (default:
`~/astro-sites/maricoparecords`). It must be outside the repository.

Build artifacts are written to:
```
$MRP_SITE_OUT_ROOT/builds/staging/{build-id}/
```

---

## Standard workflow

### Build and push to remote staging (most common)

```bash
scripts/mrp validate --json
scripts/mrp build --json
scripts/mrp stage --target remote-staging --json
```

`validate` checks all content against the schemas. `build` runs the Astro
static build and writes a timestamped build directory under
`$MRP_SITE_OUT_ROOT/builds/staging/`. `stage --target remote-staging` rsyncs
that build to DreamHost via SSH using credentials from `.env`, verifying the
remote `.allow-deploy` marker first.

### Stage locally instead of remote

```bash
scripts/mrp stage --target local-staging --json
```

Copies the latest build into `~/astro-sites/maricoparecords/staging/`.
Requires a local `.allow-deploy` marker in that directory.

### Dry run (check what would transfer without writing)

```bash
scripts/mrp stage --target remote-staging --dry-run --json
```

### Full production promotion (after staging review)

```bash
scripts/mrp verify --target staging --json
scripts/mrp approve --release <slug> --json
scripts/mrp publish --release <slug> --json
scripts/mrp verify --target production --json
scripts/mrp status --release <slug> --json
```

### Rollback production

```bash
scripts/mrp rollback --to <build-id> --yes --json
```

Omit `--to` to restore the latest archived production build.

---

## Reports

All commands write machine-readable JSON reports:

| Command | Report location |
|---------|----------------|
| `validate` | `reports/validation/` |
| `build` | `reports/build/` |
| `stage` | `reports/deployment/` |
| `verify` | `reports/verification/` |
| `approve` | `reports/approval/` |
| `publish` | `reports/publish/` |
| `rollback` | `reports/rollback/` |

Report files and build output directories are git-ignored.
