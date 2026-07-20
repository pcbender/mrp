# MRP Music Video Track Workflow

Milestone 3 connects one MRP release track to the headless renderer without
copying private production paths into versioned project files.

## Commands

Install the optional renderer environment from `requirements-video.txt`. Add
`requirements-video-align.txt` only when new OpenAI transcription is required.

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

`reviewed` is optional on existing aligned sections and lines. A newly aligned
file therefore remains backward compatible. Uncertain and unmatched cues count
as pending until explicitly reviewed; once none remain, saving advances a draft
track's `music_video.status` to `timed`. Bracketed structure directives are
section metadata and the shared renderer contract rejects them as displayed
lyric cues.

## Admin section-casting editor

After reviewed timing advances a track to `timed`, the per-track Video page
links to `/releases/{release}/tracks/{track}/video/casting`. Every aligned
section is a stable scene. Resolution order is exact section override, then a
case-insensitive section-type default, then the deterministic auto cast (or the
global-layer fallback when auto casting is disabled).

The editor can materialize an auto cast, clear back to inheritance, or save a
manual composition containing one to twelve traces. Each trace exposes its
role, hypotrochoid/epitrochoid geometry, anchor, scale, color, depth, opacity,
line and rotation behavior, cyclic trail, ghosts, and optional scale/opacity/
color/pulse audio drivers. Scene-level controls cover visible roles, spatial
and motion response, lyric opacity, trace/trail response, beat gain, and
intensity gain. Section-type settings apply consistently to repeated forms;
exact-section settings permit deliberately different scene geometry.

Saves validate the complete shared project contract and atomically replace the
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

## Privacy and dependency boundary

The track workflow lives entirely in `mrp.video`. It does not import MRP Admin,
Astro, or publishing code. Normal MRP commands remain usable without video
dependencies, and all generated runtime paths, hashes, logs, previews, renders,
and renderer manifests stay below the ignored processed tree.
