# Maricopa Release Publisher

Maricopa Release Publisher, abbreviated MRP, is a local release-publishing
pipeline for the Maricopa Records static site.

## CLI

Install Python dependencies once per environment:

```bash
python3 -m pip install -r requirements.txt
```

On Windows, the same dependency file works from PowerShell:

```powershell
python -m pip install -r requirements.txt
```

Run the repo-local wrapper from the repository root:

```bash
scripts/mrp --help
scripts/mrp inspect
scripts/mrp inspect --json
scripts/mrp validate --json
scripts/mrp build --json
scripts/mrp stage --target local-staging --json
scripts/mrp verify --target staging --json
scripts/mrp approve --release circuiting --json
scripts/mrp publish --release circuiting --json
scripts/mrp rollback --to <build-id> --yes --json
scripts/mrp release create --artist pcbender --title "Signal Path" --type single --json
scripts/mrp migrate-site --source /home/mrose/website-migration --dry-run --json
scripts/mrp import-spotify --roster content/import-review/spotify-roster.yaml --json
scripts/mrp status --release circuiting --json
```

On Windows, use the matching launcher from PowerShell or cmd:

```powershell
.\scripts\mrp.ps1 --help
.\scripts\mrp.cmd validate --json
```

This repository keeps tracked text files normalized as LF so the same checkout
can move between WSL2/Linux and Windows without line-ending churn. Windows-only
launchers are stored with CRLF endings.

The MRP v0.1 CLI keeps the same entry point and global flags across commands:

```text
--json
--dry-run
--no-color
--repo
```

Registered command groups:

```text
init
inspect
validate
build
stage
verify
approve
publish
rollback
status
release create
import-site
import-spotify
```

Implemented commands currently include `inspect`, `validate`, `import-site`,
`import-spotify`, `build`, `stage`, `verify`, `approve`, `publish`, `rollback`,
and `status`. The
build command validates content, runs the Astro static site build into
`$MRP_SITE_OUT_ROOT/builds/staging/{build-id}/`, and writes a JSON report under
`reports/build/`. `MRP_SITE_OUT_ROOT` defaults to
`~/astro-sites/maricoparecords` and must be outside the repository. The stage
command deploys a build to a configured local target after verifying the target
contains `.allow-deploy`. The verify command checks a deployed local target for
required pages, assets, sitemap/feed files, internal links, and placeholder
tokens. The approve command records approval only after verification passes. The
publish command promotes an approved build to local production, verifies
production, and marks the release live after verification succeeds. Rollback
restores local production from an archive or specified staging build after
explicit `--yes` confirmation. Status reports release content state, latest
validation/build/deployment/verification/approval/publish/rollback records, and
rollback availability.

`release create` writes a draft YAML manifest under `content/releases/`, creates
the matching `assets/releases/{slug}/` folder, and refuses to overwrite an
existing release.

`migrate-site --dry-run` plans the v0.1.1 full-site staging migration from the
read-only `~/website-migration` source without writing content records or assets.
The staging RSS feed includes current release entries and migrated blog/news
posts; migrated static pages are listed in the sitemap but are not feed items.

`import-spotify` reads a roster of Spotify artist links from
`content/import-review/spotify-roster.yaml` and writes artist/release/asset
candidates under `content/import-review/spotify-*.yaml` plus a JSON report
under `reports/import/`. It never writes to `content/artists/` or
`content/releases/` directly; new releases that match an existing record by
UPC, ISRC, or title get a `matched_existing` patch proposal instead of a
duplicate. Requires `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in the
environment. See
[docs/SPOTIFY-CATALOG-IMPORT-v0.2.md](docs/SPOTIFY-CATALOG-IMPORT-v0.2.md).

`enrich-links` backfills non-Spotify streaming links (Apple Music, YouTube,
YouTube Music, Tidal, Deezer, Amazon Music, SoundCloud) on existing releases
in `content/releases/` via the Odesli (api.song.link) API, keyed off each
release's `links.spotify`. It only fills in currently-null fields, never
overwrites a set value. Odesli rate-limits anonymous requests to 10/min;
setting `ODESLI_API_KEY` in the environment or `.env` raises that to 60/min
and lowers the default delay between requests accordingly.

`enrich-apple-music` backfills Apple Music links on releases and tracks using
Apple's free, keyless iTunes lookup API. It starts from each artist's
`links.apple_music` artist-page URL in `content/artists/`, matches that
artist's Apple albums to our releases by (normalized) title, and additively
fills `links.apple_music` on the release and, for multi-track releases, on
each matching track. Odesli generally lacks Apple Music/YouTube coverage for
this catalog, so this command exists alongside `enrich-links` rather than
replacing it; releases with no title match are reported as
`unmatched_release_paths` for manual follow-up.

`enrich-youtube` backfills YouTube and YouTube Music links the same way,
using the YouTube Data API v3 (`GOOGLE_SERVICE_API_KEY` in the environment
or `.env`). It starts from each artist's `links.youtube` channel URL,
fetches that channel's uploads playlist once, and matches videos to
releases and tracks by normalized title -- one playlist fetch per artist
covers every track, no per-release API calls. Both `links.youtube` and
`links.youtube_music` are filled from the same matched video ID, since an
artist's own channel uploads are the same underlying video on both
surfaces. Additive only, same as the other enrich-* commands.

MRP v0.1 is local-only. Remote SSH, rsync, and SFTP deployment are deferred as a
v0.2 candidate in [docs/REMOTE-DEPLOYMENT-v0.2.md](docs/REMOTE-DEPLOYMENT-v0.2.md).

## Repository Policy

MRP is the release/content publisher and migration tool; Astro is the website
builder. Git stores source, canonical content, tests, and docs. Generated site
output is disposable and must live outside the repository under
`MRP_SITE_OUT_ROOT`.

Canonical content lives in `content/` and is the format used for both imported
WordPress content after normalization and future manually added artists,
releases, pages, and posts. Temporary staging or audit records are allowed only
when explicitly labeled, such as `content/clone/` during the v0.1.2 WXR clone
transition. Raw or semi-raw migration staging data belongs under
`migration/staging/` if that pipeline is added, and is not final canonical
content unless explicitly promoted.

Do not commit or hand-edit generated HTML under `builds/`, `graphify-out/`,
`site/dist/`, `site/.astro/`, or `$MRP_SITE_OUT_ROOT/*`.

## Docs

- [Content model](docs/CONTENT-MODEL.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Agent usage](docs/AGENT-USAGE.md)
- [Remote deployment v0.2 candidate](docs/REMOTE-DEPLOYMENT-v0.2.md)
- [Spotify catalog import v0.2 candidate](docs/SPOTIFY-CATALOG-IMPORT-v0.2.md)
- [MRP v0.1.1 full site staging plan](docs/MRP-v0.1.1-FULL-SITE-STAGING-PLAN.md)
- [MRP v0.1.1 migration review](docs/MRP-v0.1.1-REVIEW.md)
- [MRP v0.1.2 WXR static clone plan](docs/MRP-v0.1.2-WXR-STATIC-CLONE-PLAN.md)
- [MRP v0.1.2 WXR static clone review](docs/MRP-v0.1.2-REVIEW.md)

## End-to-End Test

Run the v0.1 local flow regression:

```bash
python3 -m pytest tests/test_e2e_v01.py
```

Run the v0.1.2 WXR static clone regression:

```bash
python3 -m pytest tests/test_e2e_v012.py
```
