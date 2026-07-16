# MRP Changes Page Workflow

The **Changes** page should function as a controlled publishing workflow rather
than simply a Git commit utility. This doc is the canonical spec; it is being
built in phases (see *Implementation status* at the bottom).

## Navigation indicator

The **Changes** navigation link should display an indicator whenever Git
detects managed changes (content/ and assets/ pathspecs). Treatments include a
count badge such as `Changes (4)`. The indicator disappears when the managed
working tree is clean.

## Publishing eligibility

A release must have a status of at least **approved** or **live** before any
files associated with that release are eligible to be published.

Changes associated with releases that have not reached an eligible status
should:

* Be clearly identified as ineligible.
* Be excluded from staging and production deployment by default.
* Explain which release status is preventing publication.
* Prevent the publishing workflow from continuing when the selected changes
  depend on an ineligible release.

This eligibility check occurs before the **Push to Staging** step. Non-release
content (artists, posts, pages) and unattributable assets are always eligible.

Eligibility gates **publishing only** — committing to Git is always allowed
(Phase 4). Draft work commits freely; the public site build excludes releases
whose status is not public, so committed drafts do not render. Committing (or
discarding) an ineligible pending change is also how it stops blocking the
publish ladder for everything else.

## Changes page workflow

### 1. Review changes

Display all Git-detected managed changes. The user can review changed files,
select/exclude individual changes, view the diff, see which releases / artists /
tracks / reviews are affected, and see whether each affected release is eligible.

### 2. Generate the commit message

Generate a default commit message from the actual content being changed rather
than a canned string. Examples:

* `Update You Don't Say by pcbender`
* `Update Burn Me and The Hardest Gift by STAB`
* `Publish A Good Day to Be`
* `Update 3 releases and 1 artist profile`

The message stays editable and appears with the **Commit** action, which is
available whenever there are pending changes (validation-gated).

### 3. Push to staging

Deploy the selected, eligible working changes to the staging site **without**
first committing them to Git. Show the deployment result, errors/warnings, a
link to the staging site, and links to affected pages where determinable.
Require an explicit **Verify Staging** action before production becomes
available. Corrections can be made in the editors and redeployed to staging
without creating Git commits. Any content change after verification invalidates
it and requires staging to be redeployed and re-verified.

### 4. Push to production

After staging is verified, deploy the same verified changes to production. Show
the result, errors/warnings, and links to affected production pages. Require an
explicit **Verify Production** action. Any content change after production
deployment invalidates the staging and production verification state.

### 5. Approve, Commit, and Push

Committing is **independent of the publish ladder** (Phase 4 — this supersedes
the original commit-last design). The **Approve, Commit & Push** action is
available whenever there are pending managed changes: it validates the
repository, commits the changes to `main` with the reviewed message, and
pushes. No deploy or verification is required first, and drafts commit freely.

Because the workflow signature is content-based (invariant across commits),
committing does **not** invalidate a staged/verified deploy, and the ladder can
publish a clean tree (commit first, then publish — the recommended order, so
production only serves committed content). If the push fails, the commit is
safe locally and the page shows an unpushed-commits indicator with a **Push to
origin** retry button.

## v1 design decisions (2026-07-11)

* **Whole-tree deploy** — the site build is whole-tree (Astro rebuilds all of
  `content/`), so v1 does not do true per-file exclusion. The eligibility check
  is a **hard gate on publishing**: if any pending managed change belongs to an
  ineligible release, staging/production is blocked until it is made eligible,
  committed, or discarded. (Isolated per-selection builds via a temp worktree
  are a possible v2.) Caveat: releases in mid-pipeline statuses (`staged`,
  `verified`) *do* render in builds — a whole-tree deploy while one is
  committed mid-workspace-pipeline publishes its page early. This pre-dates
  Phase 4 (committed content was never gated) and is accepted for v1.
* **Selection** in v1 scopes the Git commit and what the gate reports; deploy
  publishes the working tree.
* **Production via `publish()`** — reuses the existing production path (marker
  safety, approval report, rollback). Staging uses `stage_build(remote-staging)`.
* **The release-centric workspace Build/Publish ladder is unchanged** — it works
  well for shipping a brand-new release and is not touched by this workflow.

## Implementation status

* **Phase 1 (done 2026-07-11)** — nav indicator (`/changes/badge`), affected-
  entity + eligibility display, and generated commit message. No deploy changes.
  Code: `mrp/admin/changes_meta.py`, `mrp/admin/routes/changes.py`,
  `mrp/admin/templates/changes/_panel.html`, `_base.html` nav.
* **Phase 2 (done 2026-07-11)** — a **Publish** section on the Changes page:
  **Push to Staging** builds the whole site and rsyncs the working tree to the
  `remote-staging` target via a background job (poll UI), gated so it refuses
  when any pending change is ineligible. **Verify Staging** records the
  verification against a working-tree signature; any later edit invalidates
  staging + verification (a "staging is out of date" nudge). Affected public
  pages are linked. State persists in `~/.mrp/changes-workflow.json` keyed by
  repo root. Staging URL from `MRP_STAGING_URL`. Code:
  `mrp/admin/publish_state.py`, `routes/changes.py`,
  `templates/changes/_stage_status.html` + `_stage_job.html`.
* **Phase 3 (done 2026-07-11)** — the publish surface is now a three-rung
  **ladder** (staging → production → commit) rendered in `#publish-ladder`:
  **Push to Production** promotes the *same staged+verified build* to the
  `remote-production` target and runs `verify_target` (marker + content) as a
  safety net; **Verify Production** is the human sign-off. The final
  **Approve, Commit, and Push** rung unlocks only when both staging and
  production are verified against the current signature — it validates,
  commits the whole verified working tree to `main` with the reviewed
  message, pushes, and clears workflow state. Any edit invalidates the whole
  ladder (signature drift). Production URL from `MRP_PRODUCTION_URL`. We reuse
  `publish()`'s safety helpers (marker check via `stage_build`, `verify_target`)
  rather than `publish()` itself, since it is release-centric; release status
  is left untouched. Note: the archive/rollback snapshot in `publish()` is a
  local-production feature and is **not** wired for the remote rsync path.
  Code: `mrp/admin/publish_state.py`, `routes/changes.py`,
  `templates/changes/_publish_ladder.html` (replaces the Phase-2 stage
  partials).
* **Phase 4 (done 2026-07-16)** — **commit decoupled from the ladder.** The
  original commit-last design tied saving work to git to a full
  build/stage/verify/production/verify pass, which (a) made draft content
  uncommittable (the eligibility gate blocked rung 1, the ladder blocked
  rung 3), (b) let one draft block committing everything else, and (c) put
  uncommitted content live on production before git recorded it. Now:
  **Commit** is its own section, available whenever changes exist
  (validation-gated only); the ladder is two rungs (staging → production) and
  gates only on eligibility of *pending* changes; the workflow signature is
  content-state based (`git ls-files -s` blobs overlaid with working-tree
  hashes), so committing never invalidates a verified deploy and a clean tree
  can be published (commit-first is the recommended order); a failed push
  leaves an unpushed-commits banner with a **Push to origin** retry
  (`/changes/push`, `gitops.push_main`). Code: `publish_state.py`,
  `gitops.py`, `routes/changes.py`, `templates/changes/_panel.html`,
  `_publish_ladder.html`.
