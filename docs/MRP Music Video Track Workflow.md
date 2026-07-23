# MRP Music Video Track Workflow

Milestone 3 connects one MRP release track to the headless renderer without
copying private production paths into versioned project files.

## Commands

Install the optional renderer environment from `requirements-video.txt`. Add
`requirements-video-align.txt` only when new OpenAI transcription is required.
Admin video jobs prefer the repository `.venv` interpreter when it exists and
otherwise use the admin server interpreter. Set `MRP_VIDEO_PYTHON` to an
explicit interpreter when the locked video environment lives elsewhere.

```bash
scripts/mrp video track prepare RELEASE [--track TRACK] --json
scripts/mrp video track preflight RELEASE [--track TRACK] --json
scripts/mrp video track analyze RELEASE [--track TRACK] --json
scripts/mrp video track align RELEASE [--track TRACK] --json
scripts/mrp video track preview RELEASE [--track TRACK] --time 30 --json
scripts/mrp video track render RELEASE [--track TRACK] --draft --from 30 --to 45 --json
scripts/mrp video track render RELEASE [--track TRACK] --dry-run --json
```

`RELEASE` is the slug below `content/releases/`. A single has exactly one song,
so `--track` is optional and must match that song if supplied. An EP or album
requires `--track`.

In the admin track workspace, **Import legacy master** explicitly selects an
older `automation.master_path` for the track; the legacy path is never presented
as though it were already saved. **Import from path...** scans one local stem
directory for WAV, MP3, FLAC, AIFF, or M4A files, derives stable IDs and initial
semantic roles from their filenames, and adds editable rows. Directory import
does not modify release YAML until **Save assets** is clicked.

`prepare` validates the exact local assets before linking the track to its
project. On first success it adds this optional track state:

```yaml
music_video:
  project: assets/source/video/{artist-id}--{track-slug}/project.yaml
  status: draft
```

Existing status and public-media fields are preserved.

## Versioned source

The stable key is `{artist-id}--{track-slug}`. Git owns:

```text
assets/source/video/{track-key}/project.yaml
assets/source/video/{track-key}/lyrics.aligned.yaml
```

The aligned file appears after a successful `track align`. The project stores
renderer settings, visual configuration, contract versions, source renderer
revision, and a release/track reference. Adapter-owned paths use symbolic
values such as `@mrp/master`, `@mrp/stems/vocals`, `@mrp/lyrics`, and
`@mrp/cover`. Consequently, the tracked project never duplicates `master_path`
or stem paths from release YAML.

Running `prepare` again refreshes adapter-owned title, role, and symbolic-path
fields while preserving reviewed renderer, timing, text, card, and visual
settings. `--force` deliberately resets the tracked project to adapter
defaults.

## Generated workspace

The adapter resolves symbolic inputs into a renderer-compatible relative-path
manifest below the ignored processed tree:

```text
assets/processed/video/{track-key}/
  analysis/
    project.runtime.yaml
    lyrics.yaml
    cache/
    stems/{role}-{input-hash}.wav
  previews/
  renders/
  logs/preflight.json
  logs/artifacts.json
```

The generated manifest may resolve outside the repository to operator-owned
audio, but it remains ignored and is never an Astro input. Structured lyrics
are materialized from the track's canonical lyrics fields; bracketed section
directives become section metadata rather than displayed lyric cues.

## Semantic stem aggregation

Only enabled stems participate. Stable stem IDs are sorted before processing,
so release-row order cannot change the result.

- One stem for a semantic role is passed through directly.
- Multiple stems for one role are decoded to mono at the master sample rate,
  fitted to the master timeline, and combined with an arithmetic mean.
- `other` joins `instruments`; this gives otherwise unclassified musical stems
  the renderer's instruments controls.
- The aggregate filename hashes the algorithm, role, master timing, stable stem
  IDs, and source hashes.
- The master is never treated as a stem. Missing roles retain the renderer's
  established master-derived fallback controls.

Preflight rejects missing or undecodable inputs and stem durations outside the
project tolerance instead of hiding a mismatch through padding.

## Hashes, preflight, and stale artifacts

Every preparation hashes the tracked project plus the master, enabled stems,
structured lyrics, optional aligned lyrics, cover, and font. Their normalized
combination is the input fingerprint.

`logs/preflight.json` records the fingerprint, input hashes, duration checks,
role membership, MRP-owned artifact paths, and any stale artifacts. Successful
analysis, alignment, preview, and render operations append or replace their
entry in `logs/artifacts.json` with the fingerprint they used.

An artifact is stale when its recorded fingerprint differs from the current
fingerprint. Stale artifacts remain available for diagnosis and comparison;
the adapter reports them and never silently deletes or approves them.

## Admin timing editor

The per-track Video page links to
`/releases/{release}/tracks/{track}/video/timing`. Alignment runs in the same
isolated process-job system as analysis and rendering. It uses the structured
track lyrics and vocals stem, writes the versioned `lyrics.aligned.yaml`, and
reuses cached transcription unless the operator deliberately retranscribes.

The editor streams the private track master through an admin-only route and
adds a synchronized scrubber, playhead capture, and range playback. Operators
can edit every section and lyric-cue start/end value and record review state
without changing canonical lyric text, section identity, confidence, match
status, or alignment provenance. Saves are atomic and reject invalid ordering,
overlap, out-of-section lines, nonpositive windows, and timing beyond the known
master duration.

If automatic alignment collapses a recognized lyric to a nonpositive window,
the aligner preserves it as a non-overlapping provisional cue instead of
aborting the whole alignment. The cue receives an editable timing window,
`status: unmatched`, and zero confidence, and the aligner writes the complete
file with a manual-review warning. The Timing editor can then correct and
explicitly review the cue.

`reviewed` is optional on existing aligned sections and lines. A newly aligned
file therefore remains backward compatible. Uncertain and unmatched cues count
as pending until explicitly reviewed; once none remain, saving advances a draft
track's `music_video.status` to `timed`. Bracketed structure directives are
section metadata and the shared renderer contract rejects them as displayed
lyric cues.

The editor labels a reviewed uncertain or unmatched cue as `manual`, while the
stored match status and confidence continue to record the aligner's original
result. Rejected saves display their validation details in the editor and do
not partially persist timing changes before release validation succeeds.

## Admin actor and scene-casting editor

After reviewed timing advances a track to `timed`, the per-track Video page
links to `/releases/{release}/tracks/{track}/video/casting`. Every aligned
section is a stable scene. Actor resolution order is an exact-scene actor cast,
then a case-insensitive section-type actor cast. Projects that have not adopted
actors continue through the original exact composition, section-type
composition, deterministic auto cast, and global-layer fallback in that order.

Actor Library and Actor Designer are track-level surfaces above the scene
workspace. The library browses identities pinned to the current project and
reusable definitions under `assets/source/video/actors/`. Importing creates a
project-owned snapshot, records the library content revision, and assigns the
new track actor a musical character. Updating a library identity never changes
a project until the operator imports it again. Actor Designer gives the actor a
name, a stable track-wide “reacts to” character such as bass, and a live
spirogram preview, with topology and component behavior under advanced
controls. An actor may contain multiple visual components.

Two library actor ids are reserved for branding and auto-imported into a
track's roster **when its project is first created** (the initial `prepare`,
or a `--force` rebuild): `maricopa-records` (the label mark) and
`artist-{artist_id}` (the release artist's name mark, e.g.
`artist-michael-anthony-rose`). Each is snapshotted and revision-pinned exactly
like a manual import. Missing branding actors are skipped, so `prepare` never
fails when they do not exist yet. Auto-import runs only on fresh creation — a
later deletion from the roster sticks, and re-preparing an existing project
does not re-add it.

Scene Casting assigns those actors to all sections of a type or to one exact
scene. Per-appearance direction controls position, scale, opacity, visibility,
foreground/background layer, hue, and additional rotation, but cannot change
the actor's musical character. The existing whole-scene response is retained
under advanced controls. “Create recommended actors” materializes the
deterministic cast as editable track actors; “Adopt current look” converts the
currently resolved legacy composition. Actor identity, track character, and
scene direction compile into the renderer's unchanged trace composition
contract.

Track actors save through `/video/actors`, independently of section identity or
casting scope. Scene casts save through `/video/casting`. Both validate the
complete shared actor and project contracts and atomically replace the
versioned `project.yaml`. The previous preflight becomes `stale`, so no preview
or render made from the former project is treated as current. Generated files
are retained for comparison and remain below `assets/processed/video/`.

Selected-time frames and one-frame-per-section contact sheets run through the
same isolated process-job system as analysis and alignment. Preview artifacts
record the input fingerprint and are served only through the admin route. A
successful preview of the current cast advances `cast` to `previewed`; changing
the cast returns the track to `cast` and requires fresh preflight/rendering.

## Admin draft, full-render, and approval workflow

After casting, the per-track Video page links to
`/releases/{release}/tracks/{track}/video/rendering`. A draft job accepts either
a timed section range or custom start/end values. Every job gets its own ignored
`renders/drafts/{job-id}.mp4` plus adjacent `.render.json`; the history keeps
current and stale iterations available for private comparison. Discard removes
only the selected draft and its manifest from the generated workspace.

Full output uses a two-step gate. `render_plan` prepares the exact current
inputs and reports the fingerprint, duration, frame count, dimensions, frame
rate, card inclusion, and raw streamed work estimate. The subsequent full job
receives that fingerprint and aborts before encoding if a fresh prepare resolves
different inputs. One full render may run per track, and the persistent worker
continues to expose progress, heartbeat, cancellation, and interruption state.

Successful full jobs live under `renders/full/{job-id}.mp4`. The renderer first
encodes to temporary paths, verifies streams, codecs, pixel format, duration,
frame rate, dimensions, frame count, audio properties, and fast-start metadata
with FFprobe, writes the render manifest, and only then publishes both files.
Cancellation or failure leaves no published partial output.

Human approval is server-enforced. It rechecks the current versioned project,
aligned timing, master and enabled-stem hashes, the artifact fingerprint,
full-versus-draft flags, verification state, and MP4 SHA-256. The ignored local
approval record preserves the project hash, all preflight input hashes, manifest
hash, and output hash; the release YAML advances only the selected track to
`music_video.status: approved`. Stale renders remain visible but cannot be
approved. Publication to a stable public MP4 is deliberately deferred to
Milestone 8.

## Public-media publication and Opt In

Approval and public display are deliberately separate. The rendering workspace
requires the operator to check an initially unchecked **Opt In** box before an
approved video can be published. Publication re-verifies the approved MP4,
copies it and the release-cover poster into content-addressed durable storage,
and advances only that track to:

```yaml
music_video:
  project: assets/source/video/{track-key}/project.yaml
  status: published
  opt_in: true
  public_url: /media/music-videos/{track-key}/{sha256}/video.mp4
  poster: /media/music-videos/{track-key}/{sha256}/poster-{poster-sha256}.jpg
```

`opt_in` is optional and therefore false-by-absence for every existing release.
Astro requires `status: published`, `opt_in: true`, and both valid public fields
before rendering a player or metadata. The Admin can later uncheck Opt In; this
keeps the content-addressed files for recovery but excludes the player and media
from subsequent builds. Re-enabling display is refused if the durable files are
missing.

`MRP_PUBLIC_MEDIA_ROOT` controls the durable store and defaults to
`~/.mrp/public-media/maricoparecords`. It must be outside the repository and is
independent of disposable `MRP_SITE_OUT_ROOT` output. Ordinary MP4 binaries are
never committed. Instead,
`assets/source/video/{track-key}/publication.yaml` versions only public URLs and
the reviewed project/input/manifest/output/poster hashes; the Changes page
attributes this receipt to the owning release.

At build time MRP resolves only opted-in published local references, refuses
missing or escaping media, and overlays those files at `/media/` in the
immutable Astro artifact. Album/EP tracks display on their track page; a
single's sole track displays on the release page. The same build is used for
staging and production, verification requires the player and referenced MP4/
poster while scanning for private paths, and rollback restores the media with
the rest of the selected build.

## Privacy and dependency boundary

The track workflow lives entirely in `mrp.video`. It does not import MRP Admin,
Astro, or publishing code. Normal MRP commands remain usable without video
dependencies, and all generated runtime paths, hashes, logs, previews, renders,
and renderer manifests stay below the ignored processed tree.
