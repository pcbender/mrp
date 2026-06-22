## Graphify

Graphify output is generated and must not be treated as canonical source.

When the user types `/graphify`, invoke the `skill` tool with `skill: "graphify"` before doing anything else.

Rules:
- Graphify has no supported ignore-folder mechanism for this repo, so generated site output must live outside the repository tree.
- Do not rely on tracked `graphify-out/` files for navigation. If Graphify output exists locally, it is disposable.
- Do not commit `graphify-out/`, generated site output, `site/dist/`, `site/.astro/`, dependency folders, or local build archives.
- Prefer direct source inspection with `rg`, targeted file reads, and project docs unless the user explicitly asks for `/graphify`.
- If Graphify is run, verify it does not create tracked output before committing.

## Repository Boundaries

- MRP code lives under `mrp/`; Astro source lives under `site/`; canonical content lives under `content/`.
- `content/` is the publishing source of truth, except for explicitly temporary staging/audit subtrees such as `content/clone/`.
- `content/clone/` is the temporary v0.1.2 WXR static clone surface. It may contain WordPress HTML/classes while the semantic migration is in progress, but it is not the final content model.
- Future WordPress migration output must be normalized into the same canonical metadata and asset format used for newly created artists and releases.
- `migration/staging/`, if present, is audit/staging data and is not final canonical content unless a packet explicitly promotes it.
- `builds/`, `graphify-out/`, `site/dist/`, `site/.astro/`, and `$MRP_SITE_OUT_ROOT/*` are generated/disposable output. Do not edit them as source and do not commit them.

## Canto Agent Instructions

This repository is Canto-enabled. Before working, read
`.canto/agents/shared.md`. Developer sessions supervising governed work must
also read `.canto/agents/orchestrator.md`; delegated Worker sessions must also
read `.canto/agents/executor.md`. The filenames retain internal compatibility
terms while the manuals define the public roles.

Do not bypass Canto assignment, Guardrail, review, Result, Approval, or Apply
rules.
<!-- canto-agent-instructions:end -->

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
