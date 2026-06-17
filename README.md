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
scripts/mrp release create --artist pcbender --title "Signal Path" --type single --json
scripts/mrp migrate-site --source /home/mrose/website-migration --dry-run --json
scripts/mrp status --release circuiting --json
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
after explicit `--yes` confirmation. Status reports release content state,
latest validation/build/deployment/verification/approval/publish/rollback
records, and rollback availability.

`release create` writes a draft YAML manifest under `content/releases/`, creates
the matching `assets/releases/{slug}/` folder, and refuses to overwrite an
existing release.

`migrate-site --dry-run` plans the v0.1.1 full-site staging migration from the
read-only `~/website-migration` source without writing content records or assets.
The staging RSS feed includes current release entries and migrated blog/news
posts; migrated static pages are listed in the sitemap but are not feed items.

MRP v0.1 is local-only. Remote SSH, rsync, and SFTP deployment are deferred as a
v0.2 candidate in [docs/REMOTE-DEPLOYMENT-v0.2.md](docs/REMOTE-DEPLOYMENT-v0.2.md).

## Docs

- [Content model](docs/CONTENT-MODEL.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Agent usage](docs/AGENT-USAGE.md)
- [Remote deployment v0.2 candidate](docs/REMOTE-DEPLOYMENT-v0.2.md)
- [MRP v0.1.1 full site staging plan](docs/MRP-v0.1.1-FULL-SITE-STAGING-PLAN.md)
- [MRP v0.1.1 migration review](docs/MRP-v0.1.1-REVIEW.md)
- [MRP v0.1.2 WXR static clone plan](docs/MRP-v0.1.2-WXR-STATIC-CLONE-PLAN.md)

## End-to-End Test

Run the v0.1 local flow regression:

```bash
python3 -m pytest tests/test_e2e_v01.py
```
