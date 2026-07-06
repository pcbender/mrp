# Maricopa Release Publisher

Maricopa Release Publisher (MRP) is the local publishing system for the
Maricopa Records static site (maricoparecords.com). Canonical content lives
as YAML in `content/`, the site is built with Astro from `site/`, and
releases are worked from draft to live through a local admin web UI backed
by the MRP CLI.

## Quick start

Install Python dependencies once per environment:

```bash
python3 -m pip install -r requirements.txt
```

Start the admin UI (the primary way to work a release):

```bash
scripts/mrp admin serve
# → http://127.0.0.1:8000
```

The workspace walks each release through intake → details → links → tracks →
critic → sampler → promoter → publish. See
[docs/ADMIN-WORKSPACE.md](docs/ADMIN-WORKSPACE.md).

## CLI

Everything the admin UI does is also scriptable via the repo-local wrapper.
Prefer `--json` for automation; reports land under `reports/`.

```bash
scripts/mrp --help
scripts/mrp validate --json
scripts/mrp build --json
scripts/mrp stage --target remote-staging --json
scripts/mrp verify --target staging --json
scripts/mrp approve --release <slug> --json
scripts/mrp publish --target remote-production --json
scripts/mrp status --release <slug> --json
scripts/mrp release create --artist pcbender --title "Signal Path" --type single --json
```

Streaming-link enrichment (all additive — never overwrite a set value):

- `enrich-links` — Odesli (api.song.link), release + per-track; `ODESLI_API_KEY`
  raises the rate limit from 10 to 60 req/min
- `enrich-apple-music` — free iTunes lookup API, keyed off each artist's
  `links.apple_music` artist page
- `enrich-youtube` — YouTube Data API v3 (`GOOGLE_SERVICE_API_KEY`), keyed off
  each artist's `links.youtube` channel

On Windows use `.\scripts\mrp.ps1` or `.\scripts\mrp.cmd`; tracked text files
are LF-normalized via `.gitattributes` so the checkout moves between
WSL2/Linux and Windows without churn.

## Repository layout & policy

- `mrp/` — MRP CLI and admin app (Python). `site/` — Astro site source.
  `content/` — canonical content (source of truth).
- New artists → `content/artists/{slug}.yaml`; new releases →
  `content/releases/{slug}.yaml`. These are the only schemas for new work.
- The WordPress migration is **complete and closed**. Its tools and the
  `content/clone/` / `content/import-review/` trees are frozen — see
  [docs/CONTENT-PIPELINE.md](docs/CONTENT-PIPELINE.md) before touching
  anything migration-related.
- Generated output is disposable and lives outside the repo under
  `MRP_SITE_OUT_ROOT` (default `~/astro-sites/maricoparecords`). Never commit
  `builds/`, `site/dist/`, `site/.astro/`, or `graphify-out/`.
- Credentials (`ODESLI_API_KEY`, `GOOGLE_SERVICE_API_KEY`, SSH deploy keys,
  etc.) live in an untracked `.env` at the repo root — never in git.

## Docs

- [Admin workspace](docs/ADMIN-WORKSPACE.md) — the release UI, jobs, artifact keying
- [Site deployment](docs/Site_Deployment.md) — targets, credentials, build/stage/publish workflow
- [Content model](docs/CONTENT-MODEL.md) — artist/release YAML schemas
- [Content pipeline](docs/CONTENT-PIPELINE.md) — history, frozen migration tiers, forward strategy
- [Admin milestones](<docs/MRP Admin Milestones.md>) — the roadmap

## Tests

```bash
python3 -m pytest
```

`tests/test_e2e_v01.py` covers the core CLI flow end-to-end.
