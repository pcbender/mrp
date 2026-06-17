# Remote Deployment v0.2 Candidate

MRP v0.1 is intentionally local-only. The implemented deployment adapters cover:

- `local-staging`
- `local-production`

DreamHost-style SSH, rsync, and SFTP deployment are deferred until after the
local build, staging, verification, approval, publish, and rollback flow is
stable.

Future remote deployment must preserve the same safety model:

- Require a remote `.allow-deploy` marker before writing files.
- Verify the marker environment matches the intended target.
- Refuse root, home, empty, or ambiguous destination paths.
- Write a machine-readable deployment plan before copying.
- Support dry-run before destructive remote sync behavior.
- Keep credentials out of git and load them only from ignored local config or
  agent/runtime secret providers.
- Archive or snapshot production before replacing it.
- Verify the remote target after deployment and before marking a release live.

The current `deploy/targets.yaml` shape reserves `type` for future adapters, but
v0.1 accepts only `type: local`.
