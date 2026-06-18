## Graphify

Graphify output is generated and must not be treated as canonical source.

When the user types `/graphify`, invoke the `skill` tool with `skill: "graphify"` before doing anything else.

Rules:
- Graphify has no supported ignore-folder mechanism for this repo, so generated site output must live outside the repository tree.
- Do not rely on tracked `graphify-out/` files for navigation. If Graphify output exists locally, it is disposable.
- Do not commit `graphify-out/`, generated site output, `site/dist/`, `site/.astro/`, dependency folders, or local build archives.
- Prefer direct source inspection with `rg`, targeted file reads, and project docs unless the user explicitly asks for `/graphify`.
- If Graphify is run, verify it does not create tracked output before committing.

## Canto Agent Instructions

This repository is Canto-enabled. Before working, read
`.canto/agents/shared.md`. Developer sessions supervising governed work must
also read `.canto/agents/orchestrator.md`; delegated Worker sessions must also
read `.canto/agents/executor.md`. The filenames retain internal compatibility
terms while the manuals define the public roles.

Do not bypass Canto assignment, Guardrail, review, Result, Approval, or Apply
rules.
<!-- canto-agent-instructions:end -->
