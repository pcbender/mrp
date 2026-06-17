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

## MRP Project Guardrails

- The implementation repository is `/home/mrose/mrp`.
- Treat `~/website-migration` as read-only source input and asset cache.
- Follow `docs/MRP v0.1 Specification.md` as the product contract.
- v0.1 is a simple redesigned Astro site, not a full WordPress export clone.
- Keep v0.1 deployment local-only until local staging, local production,
  verification, approval, publish, and rollback work end to end.
- Do not copy large imported media into this repository unless the assignment
  explicitly says to.
- Do not implement WooCommerce, payment, account, cart, checkout, or WordPress
  admin behavior for v0.1.
