# MRP Repository Cleanup and Architecture Reset Plan

## Objective

Fix the Maricopa Release Publisher repo so it has a clean separation between:

1. MRP source code
2. Canonical content
3. Astro website source
4. Generated build artifacts
5. Migration/import staging artifacts
6. Graphify output

The current repo has generated site output inside trackable folders. Graphify
does not support ignore folders, so ignored-but-present generated HTML can still
be indexed. That makes the repo noisy, slow, and structurally wrong.

This sprint is not about making the migrated site beautiful. This sprint is
about making the repository architecture correct and hard to regress.

## Core Rule

Generated HTML is never canonical source.

The source of truth must be:

* MRP code
* Astro source code
* content files such as Markdown, YAML, JSON, or MDX
* source assets
* migration scripts
* tests
* docs

The generated website must be disposable.

If deleting a generated output folder breaks the repository, the repo is wrong.

## Final Rule

Graphify has no ignore feature, so the repository itself must be clean.

Generated sites do not belong in Git.

Generated sites do not belong under the repo.

Generated sites belong in:

```text
~/astro-sites/maricoparecords/
```

MRP produces content and builds sites.

Astro renders the site.

Git stores source.

Graphify indexes source.

---

# Target Repository Shape

Refactor toward this structure:

```text
.
├── AGENTS.md
├── README.md
├── .gitignore
├── content/
│   ├── artists/
│   ├── releases/
│   ├── pages/
│   └── data/
├── assets/
│   ├── source/
│   │   ├── audio/
│   │   ├── covers/
│   │   ├── images/
│   │   └── video/
│   └── processed/
├── migration/
│   ├── input/
│   ├── staging/
│   ├── normalized/
│   └── reports/
├── mrp/
│   └── ...
├── scripts/
│   └── ...
├── site/
│   ├── astro.config.*
│   ├── package.json
│   ├── src/
│   │   ├── components/
│   │   ├── content/
│   │   ├── layouts/
│   │   ├── lib/
│   │   └── pages/
│   └── public/
├── tests/
└── docs/
```

Important:

* `site/` is the Astro source application.
* `site/dist/` is accidental local output and must not be tracked.
* `site/.astro/` is accidental local output and must not be tracked.
* `site/node_modules/` is dependency output and must not be tracked.
* `builds/` is deprecated and must not be tracked.
* `graphify-out/` is generated Graphify output and must not be tracked.
* migration staging output is either ignored or intentionally limited to
  selected review artifacts.
* canonical content lives in `content/` and/or `site/src/content/`, but not as
  generated HTML.

The repo should not contain:

```text
builds/
graphify-out/
site/dist/
generated staging site
generated production site
generated HTML archives
WordPress static mirror output
```

---

# What Must Not Be Tracked

These folders must not be tracked by Git:

```text
builds/
builds/**
graphify-out/
graphify-out/**
site/dist/
site/.astro/
site/node_modules/
node_modules/
.tmp/
.cache/
```

If any of these are currently tracked, remove them from the Git index without
deleting local working copies unless the user explicitly approves deletion.

Use:

```bash
git rm -r --cached builds graphify-out site/dist site/.astro site/node_modules node_modules 2>/dev/null || true
```

Do not use destructive `rm -rf` until the new ignore rules are committed and
the user has confirmed whether old local build archives can be deleted or moved.

---

# Required .gitignore

Create or update `.gitignore` at repo root:

```gitignore
# Dependency folders
node_modules/
site/node_modules/
.venv/
__pycache__/
*.pyc

# Astro accidental local generated output
site/dist/
site/.astro/

# Deprecated generated output locations
builds/
graphify-out/

# Logs/cache/temp
*.log
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.tmp/
.cache/

# Generated reports
reports/**/*.json
reports/**/*.secret
!reports/**/
!reports/**/.gitkeep

# OS/editor junk
.DS_Store
Thumbs.db
.vscode/
.idea/

# Environment/secrets
.env
.env.*
!.env.example
deploy/targets.local.yaml
```

Do not add `.graphifyignore`.

Do not add Graphify exclude flags.

Do not rely on `.gitignore` to protect Graphify. The real protection is keeping
generated output outside the repo.

---

# Build Output Policy

MRP must never write staging, production, preview, archive, or Graphify output
under the repository root.

Use this external output root by default:

```bash
~/astro-sites/maricoparecords
```

Resolved paths:

```text
~/astro-sites/maricoparecords/staging
~/astro-sites/maricoparecords/prod
~/astro-sites/maricoparecords/preview
~/astro-sites/maricoparecords/deploy
~/astro-sites/maricoparecords/archive
```

The repository contains source only.

The external site output folder contains disposable/generated websites.

## Required Environment Variable

Add support for:

```bash
MRP_SITE_OUT_ROOT="$HOME/astro-sites/maricoparecords"
```

Default behavior if the variable is unset:

```bash
MRP_SITE_OUT_ROOT="${HOME}/astro-sites/maricoparecords"
```

MRP must resolve this to an absolute path.

MRP must reject any output directory that is inside the Git repository.

## Output Directory Contract

MRP build targets:

```text
target=preview  -> $MRP_SITE_OUT_ROOT/preview
target=staging  -> $MRP_SITE_OUT_ROOT/staging
target=prod     -> $MRP_SITE_OUT_ROOT/prod
```

Deploy packages:

```text
$MRP_SITE_OUT_ROOT/deploy/maricopa-site-staging-YYYYMMDDTHHMMSSZ.tar.gz
$MRP_SITE_OUT_ROOT/deploy/maricopa-site-prod-YYYYMMDDTHHMMSSZ.tar.gz
```

Optional archives:

```text
$MRP_SITE_OUT_ROOT/archive/staging-YYYYMMDDTHHMMSSZ/
$MRP_SITE_OUT_ROOT/archive/prod-YYYYMMDDTHHMMSSZ/
```

No generated build output belongs in:

```text
./builds/
./site/dist/
./graphify-out/
./reports/generated-site/
```

## Astro Build Implementation

Astro should build to the external output folder.

Example command from the repo root:

```bash
cd site
npm run build -- --outDir "$MRP_SITE_OUT_ROOT/staging"
```

For production:

```bash
cd site
npm run build -- --outDir "$MRP_SITE_OUT_ROOT/prod"
```

If MRP invokes Astro directly, use equivalent behavior:

```bash
npx astro build --outDir "$MRP_SITE_OUT_ROOT/staging"
npx astro build --outDir "$MRP_SITE_OUT_ROOT/prod"
```

The important rule is that `outDir` must resolve outside the repo.

## Safety Guard

Before deleting, cleaning, or writing a target directory, MRP must verify that
the target path is outside the repo.

Pseudo-code:

```ts
import path from "node:path";

function assertOutsideRepo(repoRoot: string, targetDir: string) {
  const repo = path.resolve(repoRoot);
  const target = path.resolve(targetDir);

  if (target === repo || target.startsWith(repo + path.sep)) {
    throw new Error(
      `Refusing to write generated site inside repository: ${target}`
    );
  }
}
```

Also verify that the target is under the allowed external root:

```ts
function assertUnderSiteOutRoot(siteOutRoot: string, targetDir: string) {
  const root = path.resolve(siteOutRoot);
  const target = path.resolve(targetDir);

  if (target !== root && !target.startsWith(root + path.sep)) {
    throw new Error(
      `Refusing to write outside configured site output root: ${target}`
    );
  }
}
```

Before `rm -rf`, both guards must pass.

---

# Architecture Decision

MRP is not the website.

MRP is the release/content publisher and migration/import tool.

Astro is the website builder.

The repo may contain both tools, but they must remain separated:

```text
mrp/       = MRP application code
content/   = canonical content and catalog data
site/      = Astro source app
builds/    = deprecated generated output location, ignored and removed
```

MRP should write canonical content files, not generated HTML.

Examples:

```text
content/artists/lingua-aeternum.md
content/artists/4castle.md
content/releases/tria-ti.md
content/releases/on-the-advent-of-a-dream.md
content/pages/about.md
content/data/redirects.json
```

Astro should read those files and build the site.

## Import Success Rule

The WordPress import is not the long-term content model. It is an input source
that must be normalized into the same canonical metadata and asset format used
for future Maricopa publishing work.

After the migration, adding a new artist or release should mean creating the
same kind of metadata record and providing the same kind of source assets that
the WordPress import emits.

Target migration flow:

```text
WordPress export/capture
  -> migration staging/audit records
  -> normalized semantic content
  -> canonical MRP content records
  -> Astro site build
```

Target future publishing flow:

```text
new artist/release metadata + assets
  -> canonical MRP content records
  -> Astro site build
```

The migration is complete only when imported artists, releases, pages, posts,
and assets can be maintained through the same canonical format used for newly
created artists and releases.

---

# Content Model

Define canonical content collections for:

```text
artists
releases
pages
posts
```

Artist content example:

```md
---
id: lingua-aeternum
type: artist
slug: lingua-aeternum
title: Lingua Aeternum
status: draft
path: /artists/lingua-aeternum/
image: /images/artists/lingua-aeternum/profile.png

seo:
  title: Lingua Aeternum
  description: Lingua Aeternum on Maricopa Records.

legacy:
  source: wordpress
  source_url: https://www.maricoparecords.com/artists/lingua-aeternum/
  wordpress_id: "1204"

socials:
  spotify: ""
  apple_music: ""
  youtube: ""

sections:
  - type: artist_releases
    heading: Releases
    sort: newest_first
---

Artist bio body goes here in Markdown.
```

Release content example:

```md
---
id: tria-ti
type: release
slug: tria-ti
title: Triaτί
artist: lingua-aeternum
releaseType: album
releaseDate: 2026-06-20
status: published
path: /releases/tria-ti/
coverImage: /images/releases/tria-ti/cover.jpg

seo:
  title: Triaτί | Maricopa Records
  description: Triaτί by Lingua Aeternum.

legacy:
  source: wordpress
  source_url: ""
  wordpress_id: ""
---

Release description, story, credits, lyrics notes, etc.
```

Critical rule:

An artist page does not contain a hard-coded list of releases.

A release points to its artist.

Astro queries releases by artist and sorts newest first.

---

# Astro Component Model

Replace migrated WordPress components with native Astro components.

Required components:

```text
site/src/components/ReleaseCarousel.astro
site/src/components/ArtistCarousel.astro
site/src/components/ArtistReleaseList.astro
site/src/components/ReleaseGrid.astro
site/src/components/SocialLinks.astro
```

Required catalog helper:

```text
site/src/lib/catalog.ts
```

`catalog.ts` owns the sorting and filtering rules:

```ts
import { getCollection } from "astro:content";

export async function getPublishedReleases() {
  const releases = await getCollection("releases", ({ data }) => {
    return data.status === "published";
  });

  return releases.sort(
    (a, b) =>
      new Date(b.data.releaseDate).getTime() -
      new Date(a.data.releaseDate).getTime()
  );
}

export async function getActiveArtists() {
  const artists = await getCollection("artists", ({ data }) => {
    return data.status !== "archived";
  });

  return artists.sort((a, b) =>
    String(a.data.title).localeCompare(String(b.data.title))
  );
}

export async function getReleasesByArtist(artistSlug: string) {
  const releases = await getPublishedReleases();
  return releases.filter((release) => release.data.artist === artistSlug);
}
```

Homepage:

```astro
---
import ReleaseCarousel from "../components/ReleaseCarousel.astro";
import ArtistCarousel from "../components/ArtistCarousel.astro";
import { getPublishedReleases, getActiveArtists } from "../lib/catalog";

const releases = await getPublishedReleases();
const artists = await getActiveArtists();
---

<ReleaseCarousel releases={releases} />
<ArtistCarousel artists={artists} />
```

Artist page:

```astro
---
import { getCollection } from "astro:content";
import ArtistReleaseList from "../../components/ArtistReleaseList.astro";
import { getReleasesByArtist } from "../../lib/catalog";

export async function getStaticPaths() {
  const artists = await getCollection("artists");

  return artists.map((artist) => ({
    params: { slug: artist.data.slug },
    props: { artist },
  }));
}

const { artist } = Astro.props;
const releases = await getReleasesByArtist(artist.data.slug);
---

<h1>{artist.data.title}</h1>
<Content />
<ArtistReleaseList releases={releases} />
```

Release page:

```astro
---
import { getCollection } from "astro:content";

export async function getStaticPaths() {
  const releases = await getCollection("releases");

  return releases.map((release) => ({
    params: { slug: release.data.slug },
    props: { release },
  }));
}

const { release } = Astro.props;
---

<h1>{release.data.title}</h1>
<img src={release.data.coverImage} alt={`${release.data.title} cover`} />
<Content />
```

---

# WordPress Migration Policy

Do not preserve WordPress blocks as final canonical content.

WordPress artifacts must be classified:

```text
WordPress page title       -> content title
WordPress slug/path        -> slug/path
WordPress body text        -> Markdown body
WordPress image            -> image field or Markdown image
WordPress SEO fields       -> seo object
WordPress child pages      -> relationship fields
WordPress shortcode        -> semantic section
WordPress carousel block   -> Astro component
WordPress Stackable HTML   -> migration staging only
WordPress plugin CSS       -> discard unless deliberately reimplemented
WordPress theme CSS        -> discard unless deliberately reimplemented
```

Shortcode examples:

```text
[child_pages thumbs="true"]
```

Should become:

```yaml
sections:
  - type: artist_releases
    heading: Releases
    sort: newest_first
```

A WordPress carousel of releases should become:

```yaml
sections:
  - type: latest_releases
    heading: Latest Releases
    limit: 12
```

A WordPress artist slider should become:

```yaml
sections:
  - type: artist_carousel
    heading: Artists
```

The final Astro page renders those sections with native Astro components.

## Temporary Clone Exception

The existing v0.1.2 WXR static clone under `content/clone/` is a temporary
staging/audit surface, not the final canonical content model.

Until the semantic migration replaces it:

* `content/clone/` may contain WordPress block HTML, Stackable classes, and
  WordPress asset references.
* hygiene tests must not treat `content/clone/` as final canonical content.
* cleanup packets may move clone-generated site output outside the repo, but
  should not delete clone records unless a later packet explicitly retires the
  clone flow.

After semantic content is emitted and accepted, `content/clone/` should be
retired or moved under migration staging.

---

# MRP Pipeline

Implement the pipeline as separate commands or clearly separated internal
stages.

## Stage 1: Capture

Input:

```text
migration/input/wordpress-export.xml
migration/input/media/
```

Output:

```text
migration/staging/*.yaml
migration/reports/capture-report.json
```

Purpose:

* Preserve raw WordPress source
* Preserve source URL
* Preserve WordPress ID
* Preserve raw block HTML only for audit/debug
* No generated website output

## Stage 2: Normalize

Input:

```text
migration/staging/*.yaml
```

Output:

```text
migration/normalized/*.json
migration/reports/normalize-report.json
```

Purpose:

* Extract semantic fields
* Extract body Markdown
* Extract images
* Extract social links
* Convert shortcodes into semantic section declarations
* Identify unresolved WordPress artifacts

## Stage 3: Emit Content

Input:

```text
migration/normalized/*.json
```

Output:

```text
content/artists/*.md
content/releases/*.md
content/pages/*.md
content/posts/*.md
content/data/redirects.json
assets/processed/...
migration/reports/emit-report.json
```

Purpose:

* Write canonical content files
* No generated HTML
* No `dist`
* No archive snapshots

## Stage 4: Preview

Input:

```text
content/
site/
```

Output:

```text
$MRP_SITE_OUT_ROOT/preview/
```

Purpose:

* Run Astro build or dev preview
* Generated HTML goes only outside the repo
* Never commit preview output

## Stage 5: Deploy Package

Input:

```text
$MRP_SITE_OUT_ROOT/preview/
```

Output:

```text
$MRP_SITE_OUT_ROOT/deploy/maricopa-site-YYYYMMDDTHHMMSSZ.tar.gz
```

Purpose:

* Create deployable artifact
* Artifact remains outside the repo
* Deploy process uploads it to staging/production

---

# CLI Contract

MRP should support commands roughly like:

```bash
mrp import capture --input migration/input/wordpress-export.xml
mrp import normalize
mrp import emit
mrp preview
mrp build --target staging
mrp build --target prod
mrp deploy --target staging
mrp deploy --target prod
mrp clean-output --target staging
mrp clean-output --target prod
```

Expected behavior:

```bash
mrp build --target staging
```

writes to:

```text
~/astro-sites/maricoparecords/staging
```

```bash
mrp build --target prod
```

writes to:

```text
~/astro-sites/maricoparecords/prod
```

```bash
mrp preview
```

may either run Astro dev server without writing a static site, or build to:

```text
~/astro-sites/maricoparecords/preview
```

`mrp clean-output` should remove only generated output under
`$MRP_SITE_OUT_ROOT`. It must not delete canonical content, source assets,
docs, scripts, tests, or MRP code. It must refuse targets inside the repo.

---

# Immediate Cleanup Work Packets

## CP-MRP-001 - Stop Tracking Generated Output

Tasks:

1. Add/update `.gitignore`.
2. Remove generated output from Git index:

   ```bash
   git rm -r --cached builds graphify-out site/dist site/.astro site/node_modules node_modules 2>/dev/null || true
   ```
3. Update `AGENTS.md` so agents no longer rely on tracked `graphify-out/`
   files as source-of-truth navigation.
4. Confirm with:

   ```bash
   git status --short
   git status --ignored
   ```
5. Do not physically delete user files yet.

Acceptance criteria:

* `git status --ignored` shows `builds/`, `graphify-out/`, `site/dist/`, and
  dependency folders as ignored.
* The commit contains ignore/config changes, AGENTS guidance updates, and index
  removals only.
* No canonical source files are deleted.
* No `.graphifyignore` or Graphify exclude flags are added.

---

## CP-MRP-002 - Move Build Output Outside the Repo

Tasks:

1. Add `MRP_SITE_OUT_ROOT`, defaulting to
   `$HOME/astro-sites/maricoparecords`.
2. Change MRP build/preview/stage/deploy code that writes to `builds/` or
   `site/dist/` so generated output goes to:

   ```text
   $MRP_SITE_OUT_ROOT/preview/
   $MRP_SITE_OUT_ROOT/staging/
   $MRP_SITE_OUT_ROOT/prod/
   $MRP_SITE_OUT_ROOT/deploy/
   $MRP_SITE_OUT_ROOT/archive/
   ```
3. Add path guards that refuse any generated output target inside the repo.
4. Keep `builds/` ignored and deprecated.
5. Update deployment docs and tests from `builds/local-*` to the external
   output contract.

Acceptance criteria:

* No command writes generated HTML under the repo.
* Preview/build output can be deleted and regenerated from source.
* Tests verify output is outside the repo.
* Tests verify repo-internal output roots are rejected.

---

## CP-MRP-003 - Move or Archive Old Local Output

Tasks:

1. Ask the user whether old local `builds/` output should be moved or deleted.
2. If approved, move old build archives outside the repo:

   ```bash
   mkdir -p "$HOME/astro-sites/maricoparecords/archive/imported-from-repo"

   mv builds/archive "$HOME/astro-sites/maricoparecords/archive/imported-from-repo/" 2>/dev/null || true
   mv builds/local-staging "$HOME/astro-sites/maricoparecords/staging" 2>/dev/null || true
   mv builds/local-production "$HOME/astro-sites/maricoparecords/prod" 2>/dev/null || true
   ```
3. Remove empty deprecated folders only if safe:

   ```bash
   rmdir builds 2>/dev/null || true
   ```

Acceptance criteria:

* No generated website output remains under the repo.
* User-approved historical output is preserved under
  `$HOME/astro-sites/maricoparecords/`.
* No canonical source files are moved or deleted.

---

## CP-MRP-004 - Declare Canonical Content Boundary

Tasks:

1. Document that `content/` is canonical content except for explicit temporary
   staging/audit subtrees such as `content/clone/`.
2. Document that `migration/staging/` is not canonical final content unless
   explicitly promoted.
3. Document that `site/dist/`, `builds/`, `graphify-out/`, and
   `$MRP_SITE_OUT_ROOT/*` are disposable/generated.
4. Add a repo policy section to `README.md` and `AGENTS.md`.

Acceptance criteria:

* README explains the architecture in plain English.
* AGENTS.md tells Codex/CP not to edit generated HTML.
* There is a clear "Do not commit generated site output" rule.
* The temporary role of `content/clone/` is explicitly documented.

---

## CP-MRP-005 - Convert WordPress Blocks to Semantic Sections

Tasks:

1. Add normalizer logic for common WordPress artifacts:

   * Stackable text blocks -> Markdown paragraphs/headings/lists
   * Stackable image blocks -> image fields or Markdown images
   * social button blocks -> `socials`
   * `[child_pages thumbs="true"]` -> `sections: [{ type: artist_releases }]`
   * release carousel blocks -> `sections: [{ type: latest_releases }]`
   * artist carousel blocks -> `sections: [{ type: artist_carousel }]`
2. Keep raw HTML only in `migration/staging/` or temporary clone/audit records.
3. Emit clean Markdown/YAML/JSON as final content.

Acceptance criteria:

* Final canonical content files do not contain `wp-block`, `stk-`, `wp:`,
  Stackable class names, or WordPress plugin CSS references.
* Any unresolved WordPress artifact is reported in
  `migration/reports/unresolved-artifacts.json`.
* Generated Astro site can render the page from clean content.
* Hygiene tests exclude temporary clone/audit records until those records are
  retired.

---

## CP-MRP-006 - Build Astro Components from Content Queries

Tasks:

1. Add or verify Astro content collections:

   ```text
   artists
   releases
   pages
   posts
   ```
2. Add `site/src/lib/catalog.ts`.
3. Add:

   ```text
   ReleaseCarousel.astro
   ArtistCarousel.astro
   ArtistReleaseList.astro
   ReleaseGrid.astro
   SocialLinks.astro
   ```
4. Ensure releases are sorted newest first by `releaseDate`.
5. Ensure artist pages dynamically list releases by artist slug.

Acceptance criteria:

* Adding a new release content file automatically updates:

  * homepage latest release carousel
  * artist page release list
  * release index/grid
* No hand-edited HTML is needed.
* Sorting is deterministic and covered by tests.

---

## CP-MRP-007 - Add Regression Tests for Repo Hygiene

Tasks:

Add tests that fail if:

1. generated/dependency paths are tracked.
2. generated website output exists under the repo.
3. MRP build output targets a repo-internal directory.
4. final canonical content files contain forbidden WordPress residues:

   * `wp-block`
   * `<!-- wp:`
   * `stk-`
   * `/wp-content/plugins/`
   * `/wp-content/themes/`

Possible tracked-path script:

```bash
#!/usr/bin/env bash
set -euo pipefail

FORBIDDEN_TRACKED_PATHS='^(builds/|graphify-out/|site/dist/|site/.astro/|node_modules/|site/node_modules/)'

if git ls-files | grep -E "$FORBIDDEN_TRACKED_PATHS"; then
  echo "ERROR: generated or dependency paths are tracked"
  exit 1
fi
```

Possible canonical-content residue script:

```bash
#!/usr/bin/env bash
set -euo pipefail

grep -R --include='*.md' --include='*.yaml' --include='*.yml' --include='*.json' \
  --exclude-dir=clone \
  -E 'wp-block|<!-- wp:|stk-|/wp-content/plugins/|/wp-content/themes/' \
  content site/src/content && {
    echo "ERROR: final canonical content contains WordPress residue"
    exit 1
  }
```

External-output test:

```bash
mrp build --target staging

test -d "$HOME/astro-sites/maricoparecords/staging"

if test -d "./builds/local-staging" || test -d "./site/dist"; then
  echo "ERROR: build wrote output inside repo"
  exit 1
fi
```

Internal-output rejection test:

```bash
MRP_SITE_OUT_ROOT="$PWD/builds" mrp build --target staging && {
  echo "ERROR: MRP allowed output inside repo"
  exit 1
}
```

Acceptance criteria:

* Hygiene test passes.
* Test is included in normal test command.
* Future regressions fail loudly.

---

# Do Not Do

Do not:

* commit generated `index.html` files as canonical source
* commit `builds/archive/production-*`
* put generated site output anywhere under the repo
* preserve Stackable/WordPress block HTML as final canonical content
* keep WordPress plugin/theme CSS as the new design system
* hand-edit files under build output
* treat local preview output as source
* mix migration staging files with final content files
* rely on Graphify ignore rules, `.graphifyignore`, or exclude flags

---

# Definition of Done

This sprint is complete when:

1. No generated website output exists under the repo.
2. `builds/` is untracked and deprecated.
3. `graphify-out/` is untracked and removed or moved outside the repo.
4. MRP writes staging output to `~/astro-sites/maricoparecords/staging`.
5. MRP writes production output to `~/astro-sites/maricoparecords/prod`.
6. MRP refuses to write generated output inside the repo.
7. Graphify can index the whole repository without encountering generated HTML
   site output.
8. Git contains source, content, tests, docs, and Astro source only.
9. Canonical content is Markdown/YAML/JSON, not generated HTML.
10. WordPress block/plugin/theme residue is kept only in migration staging,
    temporary clone/audit records, or reports.
11. Astro renders dynamic components from content queries.
12. README and AGENTS.md clearly document the boundaries.
