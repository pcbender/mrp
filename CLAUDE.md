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
- The CMS UI for creating/editing artists and releases does not exist yet;
  content is currently edited as YAML files directly

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
