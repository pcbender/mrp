# Agent Guidelines

## Working in this repo

- Use the repo-local CLI wrapper: `scripts/mrp` (Linux/WSL2) or
  `.\scripts\mrp.ps1` / `.\scripts\mrp.cmd` (Windows). Prefer `--json` output
  and read the JSON reports under `reports/` instead of scraping text output.
- This working directory is shared with the user's own concurrent
  terminal/editor activity. Re-check `git branch --show-current` immediately
  before committing, and avoid having content files open for editing while a
  live enrichment run is in progress.
- Before content or migration work, read `docs/CONTENT-PIPELINE.md` — the
  WordPress migration is complete and frozen.

## Graphify

This project keeps a knowledge graph at `graphify-out/` (see CLAUDE.md for
the query-first rules). Graphify output is generated, not canonical source:

- Do not commit `graphify-out/`, generated site output, `site/dist/`,
  `site/.astro/`, dependency folders, or local build archives.
- After modifying code, run `graphify update .` to keep the graph current.

## Repository boundaries

- MRP code lives under `mrp/`; Astro source lives under `site/`; canonical
  content lives under `content/`.
- `content/` is the publishing source of truth. `content/clone/` and
  `content/import-review/` are frozen migration output — read-only.
- `builds/`, `graphify-out/`, `site/dist/`, `site/.astro/`, and
  `$MRP_SITE_OUT_ROOT/*` are generated/disposable. Do not edit them as source
  and do not commit them.
- Generated site output must live outside the repository: default
  `~/astro-sites/maricoparecords`, or set `MRP_SITE_OUT_ROOT`. Never point it
  at `/home/mrose/mrp` or any child path.

## Safety rules

- No credentials in git. `ODESLI_API_KEY`, `GOOGLE_SERVICE_API_KEY`,
  `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`, and the SSH deploy settings
  all load from the environment or the untracked `.env` at the repo root.
- Do not bypass `.allow-deploy` marker checks on deploy targets.
- Use `--dry-run` when reviewing deployment target changes; use `--yes` only
  after reviewing rollback candidate output.
- Treat `/home/mrose/website-migration` as read-only source input.
- No WooCommerce/cart/checkout/account/payment behavior.

<!-- canto-agent-instructions:start -->
## Canto Agent Instructions

This repository is Canto-enabled. Before working, read
`.canto/agents/shared.md`. Developer sessions supervising governed work must
also read `.canto/agents/orchestrator.md`; delegated Worker sessions must also
read `.canto/agents/executor.md`. The filenames retain internal compatibility
terms while the manuals define the public roles.

Do not bypass Canto assignment, Guardrail, review, Result, Approval, or Apply
rules.
<!-- canto-agent-instructions:end -->
