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

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, invoke the `skill` tool with `skill: "graphify"` before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
