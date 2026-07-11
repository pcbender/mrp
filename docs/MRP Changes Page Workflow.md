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

The message stays editable and appears near the final approval action, because
no commit is created until staging and production have been verified.

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

Only after both staging and production are deployed and explicitly verified does
the final action become available. It confirms the releases remain eligible,
creates the Git commit with the reviewed message, pushes to the configured repo,
and records the verified production state as the approved repository state.

Button label: **Approve, Commit, and Push**. Git records completed, verified
publishing events rather than every corrective iteration.

## v1 design decisions (2026-07-11)

* **Whole-tree deploy** — the site build is whole-tree (Astro rebuilds all of
  `content/`), so v1 does not do true per-file exclusion. The eligibility check
  is a **hard gate**: if any pending managed change belongs to an ineligible
  release, publishing is blocked until it is made eligible or discarded.
  (Isolated per-selection builds via a temp worktree are a possible v2.)
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
* **Phase 3 (planned)** — Push to Production + Verify + Approve, Commit, and Push.
