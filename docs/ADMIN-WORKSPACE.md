# Admin Workspace

The admin web UI is the primary way releases are worked from draft to live.
It is a local FastAPI + Jinja2 + HTMX app (no build step) started with:

```bash
scripts/mrp admin serve
# → http://127.0.0.1:8000
```

Python changes require a server restart; templates live-reload.

## Release workspace

Each release gets a workspace at `/releases/{slug}/{stage}` with a persistent
header (cover, title, artist, status badge) and stage tabs:

| Stage | Purpose |
|---|---|
| `intake` | Read-only provenance (Spotify link, UPC, dates, YAML path) |
| `details` | Release metadata, credits, SEO. Artist ID changes are gated with a confirm panel and migrate all downstream artifacts |
| `links` | Per-platform link board + enrichment jobs (Odesli, LANDR, Apple Music, YouTube); platforms can be marked not-expected (`automation.links_na`) |
| `tracks` | Track matrix + per-track editor (lyrics, style, hints, master path, per-track links) |
| `critic` | AI review pipeline with per-track saved settings (`track.critic`: model/persona/target/tier); review → approve → writeback |
| `sampler` | Play the master in-browser, mark start/end, cut a −14 LUFS preview snippet via ffmpeg |
| `promoter` | Regenerates the artist's promo blurb and bios from recent releases + reviews; human review marks `bio_auto_generated: false`; builds static and optional Nim-animated promo shorts |
| `publish` | build → stage → verify → approve → publish controls |
| `monitoring` | Thin stub (roadmap item) |

## Job mechanism

Long-running steps run as background jobs: `POST /releases/{slug}/ws/{step}`
launches a thread, state persists in SQLite at `~/.mrp/admin.db` keyed
`{slug}/{step}`, and an HTMX fragment polls until done. Completed jobs fire a
`releaseSaved` HX-Trigger (promoter steps also fire `promoterSaved`) so the
header, tabs, and stage panels refresh live.

All YAML IO goes through `load_structured_record` / `serialize_structured_record`.
Saves are slice-saves: each stage patches only the keys it owns, so concurrent
edits to other sections survive.

## Artifact keying

Every downstream artifact is keyed `{artist_id}--{track_slug}`:

- critic records: `app/critic/out/{key}.json` (album pass: `album--{artist_id}--{release_slug}`)
- published reviews: `site/src/content/reviews/{key}.md` (frontmatter `track_id`)
- preview snippets: `site/public/samples/{key}.mp3` (referenced by `preview_audio` in the release YAML)

Because of this, changing a release's `artist_id` on the Details stage
triggers a confirmation workflow that renames/re-keys all of these
(`artist_artifact_moves` / `migrate_artist_artifacts` in `mrp/admin/workspace.py`).

Artist records live at `content/artists/{id}.yaml`; resolve them only via
`artist_record_path()` in `mrp/admin/workspace.py`.

## Critic pipeline

Three passes: per-track review → album pass → contextual reviews. Prompts
include the style prompt, raw lyrics (Suno-style tags are production
directions, not lyrics), and `hints` (human ground truth — trust these over
audio-tagging output). Reviews land as `pending`; writeback only writes
reviews with status `approved` or `publishable`. Critic and promoter
binaries are invoked via absolute paths under `app/critic/.venv/bin/` —
they are not on PATH.

Every critic pass is point-in-time scoped to the target `release_date`.
Same-artist catalog records dated after that cutoff (and undated records) are
excluded. The mutable artist bio is also excluded because the current schema
does not retain dated bio revisions; the critic receives a deterministic
oldest-first catalog timeline through the target release instead. For releases
before the target, that timeline uses the written critic summary when the
matching critic record is `approved` or `publishable`; otherwise it falls back
to the canonical release summary/description. Run Critic oldest-to-newest and
approve plus write back each release before starting the next one to build a
natural, evolving critical voice without leaking future catalog knowledge.
Releases sharing a date use slug order as the deterministic chronology tie-break.

## Status ladder

Release status advances forward-only with the publish steps
(`_advance_release_status` in `mrp/admin/pipeline.py`):
build → `staged`, verify → `verified`, approve → `approved`, publish → `live`.
Drafts are excluded from site builds. Deployment targets and credentials are
documented in [Site_Deployment.md](Site_Deployment.md).

## Nim animated promo shorts

The Promoter stage keeps the static ffmpeg promo video as the default, local
path. The optional Animated cover video job uses Nim only for a silent vertical
visual bed from the release cover, then ffmpeg loops/trims that visual and muxes
the selected sampler snippet audio onto it. EPs and albums persist one shared
selection at `release.promoter.promo_track_slug`; both the static video short
and animated cover use that track. A missing selection visibly defaults to
track 1, while a stale slug or missing selected-track snippet fails rather than
silently switching audio.

Nim's programmable surface is its MCP server (`https://mcp.nim.video/mcp`).
The admin talks to it directly as an MCP client: OAuth endpoints are
discovered from the server's `.well-known` metadata and the admin registers
itself via dynamic client registration, so there is **no client id or secret
to configure**. Clicking Connect Nim on the Promoter tab sends the browser
through Nim's consent page and back to the admin's loopback callback
(for example `http://127.0.0.1:8000/nim/oauth/callback`).

State lives outside git in `~/.mrp` (shared by both checkouts):
`nim-client.json` (the dynamic client registration, covers ports 8000 and
8001) and `nim-token.json` (the access token, chmod 600). Nim does not issue
refresh tokens — when the token expires, failed jobs show a Connect Nim
button and reconnecting is one click.

Optional overrides: `NIM_MCP_URL` (alternate MCP server) and
`NIM_REDIRECT_URI` (fixed callback when the admin is not on a loopback
origin). Generation uses Seedance 2 Fast (image-to-video, 9:16, 720p, 5 s —
150 Nim credits per render).
