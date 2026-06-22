# Canto Shared Agent Instructions

- Canto is globally installed; do not install Canto into this repository.
- Durable state, credentials, Results, and Workspaces live under `~/.canto`.
- Repository-local Canto intent and Guardrails live under `.canto/`.
- Delegated Worker activity happens only in Canto-managed Git worktrees.
- Canonical repository changes require Developer review and acceptance before
  Canto may Apply the exact accepted Result.
- Do not commit or push unless the human explicitly instructs you to do so.
- Do not access secrets, credential vault files, or paths denied by Guardrails.
- Sparse checkout limits context but is not a security boundary.
- Use `canto memory resolve` for unknown project references before guessing.
- Use a scoped `canto memory context-pack` when the assignment permits memory.
- Workers may propose memory but cannot approve durable memory.
