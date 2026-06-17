# Agent Usage

Use the repo-local wrapper from `/home/mrose/mrp`:

```bash
scripts/mrp --help
```

Prefer JSON output for automation:

```bash
scripts/mrp inspect --json
scripts/mrp validate --json
scripts/mrp status --release circuiting --json
```

## Safe Release Workflow

1. Create or edit content.
2. Validate content.
3. Build the static site.
4. Stage locally.
5. Verify staging.
6. Approve the release/build.
7. Publish to local production.
8. Verify production.
9. Check status.

Commands:

```bash
scripts/mrp release create --artist pcbender --title "Signal Path" --type single --json
scripts/mrp validate --release signal-path --json
scripts/mrp build --release signal-path --json
scripts/mrp stage --target local-staging --json
scripts/mrp verify --target staging --release signal-path --json
scripts/mrp approve --release signal-path --json
scripts/mrp publish --release signal-path --json
scripts/mrp verify --target production --release signal-path --json
scripts/mrp status --release signal-path --json
```

## Safety Rules

- Treat `/home/mrose/website-migration` as read-only source input.
- Do not implement WooCommerce, cart, checkout, account, or payment behavior in
  v0.1.
- Do not add remote deployment credentials to git.
- Do not bypass `.allow-deploy` marker checks.
- Use `--dry-run` for deployment planning when reviewing target changes.
- Use `--yes` only after reviewing rollback candidate output.

## Reports

Major commands write machine-readable reports:

- validation: `reports/validation/`
- build: `reports/build/`
- deployment and publish: `reports/deployment/`
- verification: `reports/verification/`
- approval: `reports/approval/`
- rollback: `reports/rollback/`

Agents should read these JSON files instead of scraping human text output.
