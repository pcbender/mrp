## Two sites — know which one you're touching

This repo contains **two** distinct web applications over the same `content/`
YAML tier. Don't confuse them:

- **Public site** — the Astro static site in `site/`. It reads `content/`
  and builds the public `maricoparecords.com` (artist pages, release/song
  landings, catalog, migrated/clone pages). Build/stage with
  `scripts/mrp build` then `scripts/mrp stage --target remote-staging`
  (never raw rsync). Files: `site/src/**`, loaders in `site/src/lib/`.
- **Admin site** — a FastAPI + Jinja2 app in `mrp/admin/`, launched with
  `scripts/mrp admin serve` (defaults to `127.0.0.1:8000`; use `--port` for
  a second instance, e.g. dev-testing on `:8001`). It is the internal
  management console: create/edit **artists**, **releases**, and **posts**;
  run the promoter/critic/sampler **workspace** pipeline; view the
  **metrics** dashboard; generate media via **Nim**; and commit content to
  `origin/main` through the **Changes** page (no PR). It edits the same
  `content/` YAML the public site renders. Routes live in
  `mrp/admin/routes/`, templates in `mrp/admin/templates/`.

Both sites validate against `mrp/schemas/*.schema.json`. A schema/content
change usually needs to be reflected in **both** the admin editor
(`mrp/admin/routes/` + templates) and the public renderer (`site/src/`).
Known gap: the admin artist editor does not yet expose the band `members`
field — members are edited as YAML directly for now, but saving an artist in
the admin preserves an existing `members` block (it only rewrites known
scalar fields + links).

## Content pipeline — read this first

The WordPress migration is **complete and closed**. There are two frozen legacy
tiers (WP clone HTML passthrough, WP-to-structured Markdown) and one active
tier (structured YAML catalog). Full details in `docs/CONTENT-PIPELINE.md`.

**Rules for agents:**

- New artists → `content/artists/{slug}.yaml` (artist schema)
- New releases → `content/releases/{slug}.yaml` (release schema)
- These are the only schemas that matter for new work
- Do not create new clone records (`content/clone/`)
- Do not extend or fix the frozen migration/import CLI tools:
  `migrate-site`, `import-site`, `import-spotify`, `promote-spotify`,
  `clone-*`, `wxr.py`
- Do not add new content to `content/import-review/`
- `CloneLayout.astro` and the WP stylesheets in `site/public/assets/wp/`
  serve live legacy pages — leave them alone unless explicitly asked to
  replace a specific clone page with a native Astro page
- Artists, releases, and posts are created/edited through the **admin site**
  (`mrp/admin/`, see "Two sites" above) or by editing the `content/` YAML
  directly. The admin artist form does not yet cover every field (e.g. band
  `members`); edit those in YAML.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
