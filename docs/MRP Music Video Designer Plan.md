# MRP Music Video Designer Plan

Status: proposed implementation plan, 2026-07-20

This plan moves the headless Python music-video renderer from the Spirophonic
repository into MRP and makes MRP Admin the only production UI for creating,
reviewing, rendering, approving, and publishing those videos.

The Spirophonic React application remains in its repository unchanged. React,
Vite, Node, and the browser instrument are not dependencies of video rendering
and will not be migrated into MRP.

## Settled architecture decisions

1. MRP owns music-video production because it already owns track metadata,
   lyrics, master paths, release artwork, background jobs, approval, and Astro
   publication.
2. The renderer moves into an isolated `mrp.video` Python package. Renderer
   modules must not import the admin application, Astro code, or publishing
   pipeline.
3. MRP Admin uses FastAPI, Jinja, and HTMX for the workflow. Small vanilla
   JavaScript modules may provide audio scrubbing, timeline dragging, and
   canvas previews; no React application will be added.
4. Track-schema changes are additive and backward compatible. Existing release
   files will not be backfilled merely to satisfy the video feature.
5. Human decisions such as corrected timing and section casts are versioned
   source material. Analysis caches, draft renders, and temporary encodes are
   generated artifacts and remain outside Git.
6. Renderer tests have their own directory and command. Developing the renderer
   must not require collecting or running the full MRP or Astro test suite.
7. A full MP4 is not committed to Git by default. Public media storage and
   deployment must be settled before Astro exposes an approved video.

## Target architecture

```text
content/releases/{release}.yaml
  track master, stems, lyrics, video status/reference
                  |
                  v
MRP Admin: FastAPI + Jinja + HTMX
  assets -> timing -> cast -> preview -> render -> approve
                  |
                  v
mrp.video (UI-independent Python engine)
  project -> analysis -> alignment -> casting -> frames -> FFmpeg -> verify
                  |
          +-------+--------+
          |                |
          v                v
assets/source/video/   assets/processed/video/
reviewed source        caches, previews, renders
                  |
                  v
approved media publication -> Astro player/reference
```

The admin adapter translates an MRP track plus its reviewed video project into
the renderer's internal models. The renderer does not read release YAML or know
how Astro publishes a release.

## Track contract

The release is the catalog wrapper, not the video owner. A single-track
release stores its one track at `release.song`; an EP or album stores at least
two tracks in `release.tracks[]`. Both locations use the same track contract,
and `stems` plus `music_video` live only on the individual track. There is no
release-level stems collection or release-level music-video state.

### Optional stems

Add an optional `stems` array to the existing song/track definition in
`mrp/schemas/release.schema.json`:

```yaml
song:
  master_path: /mnt/c/Masters/You Don't Say.wav
  stems:
    - id: lead-vocal
      label: Lead vocal
      role: vocals
      path: /mnt/c/Stems/You Don't Say/Lead Vocal.wav
      enabled: true
    - id: drums
      label: Drums
      role: drums
      path: /mnt/c/Stems/You Don't Say/Drums.wav
      enabled: true
    - id: guitar-left
      label: Guitar left
      role: instruments
      path: /mnt/c/Stems/You Don't Say/Guitar L.wav
      enabled: true
```

Initial stem rules:

- The entire field is optional. An old track with only `master_path` remains
  valid and renderable using master-derived controls.
- Each stem has a stable slug-like `id`, a local `path`, a semantic `role`, and
  optional `label` and `enabled` fields.
- Initial roles are `drums`, `bass`, `vocals`, `instruments`, and `other`.
- Multiple stems may share a semantic role. The analysis layer must define and
  test deterministic aggregation rather than silently selecting one file.
- `id` values must be unique within a track. This requires a repository
  validation check in addition to JSON Schema validation.
- Stem paths are internal production data. They must never appear in generated
  HTML, JSON-LD, a browser payload, or a public render manifest.
- The master remains `master_path`; it is not duplicated as a stem.

An array of records is preferable to a name-to-path mapping because it gives the
editor stable row identity, permits multiple instrument or vocal stems, and
separates a human filename from the renderer's semantic role.

### Optional music-video state

Add an optional `music_video` object to the same track definition:

```yaml
song:
  music_video:
    project: assets/source/video/pcbender--you-dont-say/project.yaml
    status: cast
    opt_in: false
    public_url:
    poster:
```

Initial fields:

- `project`: repo-relative path to the versioned video project.
- `status`: `draft`, `timed`, `cast`, `previewed`, `rendered`, `approved`, or
  `published`.
- `opt_in`: optional boolean; public display is disabled unless it is exactly
  `true`, even when an approved video has been published.
- `public_url`: optional public MP4 URL or site path, written only after the
  approved-media publication step.
- `poster`: optional public poster URL or site path.

Job errors, percentages, logs, and temporary paths do not belong in release
YAML. They remain in the admin job database and processed-artifact workspace.

### Versioned and generated artifacts

Use a stable track key: `{artist_id}--{track_slug}`.

Versioned source:

```text
assets/source/video/actors/{actor-id}.yaml
assets/source/video/{track-key}/project.yaml
assets/source/video/{track-key}/lyrics.aligned.yaml
```

The global actor library stores reusable visual identities. Importing a library
actor into a project creates a complete pinned snapshot with the library actor
ID and content revision as provenance; later library edits cannot silently
change an approved project. The project stores those actor snapshots, scene
assignments and direction, reviewed timing, visual presets, card settings,
renderer contract version, and the source renderer revision used during the
transplant. These files participate in MRP's Changes review and Git history.

Generated and ignored:

```text
assets/processed/video/{track-key}/analysis/
assets/processed/video/{track-key}/previews/
assets/processed/video/{track-key}/renders/
assets/processed/video/{track-key}/logs/
```

The generated project adapter may resolve absolute source paths at runtime, but
tracked project files should not duplicate private absolute paths already held
by the release record.

## Astro compatibility contract

`release.schema.json` currently sets `additionalProperties: false` for a track,
so schema support must land before the admin writes either new field. Astro is
currently permissive and reads only the fields its components use, but that is
not sufficient evidence by itself. Every model change must pass the following
gates:

1. Existing song and album fixtures validate without modification.
2. A new enriched fixture containing stems and an unpublished video validates.
3. Importers and release creation continue producing valid records without
   stems or `music_video`.
4. Track-detail saves preserve both new objects when unrelated fields change.
5. An Astro build made from an enriched unpublished record succeeds and emits
   the same user-visible track content as the legacy shape.
6. Generated HTML and JSON-LD contain no master path, stem path, processed path,
   or internal project path.
7. Astro does not render a video merely because project data exists. It renders
   one only from an approved/published public reference added in the final
   publication milestone.
8. The full repository validation and a real catalog Astro build pass before a
   schema-changing pull request is merged.

The compatibility tests should compare normalized relevant HTML rather than an
entire build directory, which may contain unrelated generated metadata.

## Test architecture

All new video tests live below `tests/video/`, split so each lane can run by
path without collecting the rest of MRP:

```text
tests/video/engine/       renderer, analysis, alignment, casting, encoding
tests/video/admin/        adapters, routes, forms, jobs, artifact lifecycle
tests/video/contracts/    release schema and serialization compatibility
tests/video/site/         explicit Astro compatibility and publication smoke tests
tests/video/fixtures/     tiny deterministic media and project fixtures
```

Do not put a heavy shared `conftest.py` at `tests/video/`; each lane owns only
the fixtures it needs. In particular, contract and site tests must not import
NumPy, librosa, OpenCV, or the renderer merely to create a track record.

Primary commands:

```bash
# Fast renderer lane; does not collect admin, publishing, or Astro tests
pytest tests/video/engine

# MRP integration without Astro
python3 -m pytest tests/video/admin tests/video/contracts

# Explicit cross-surface compatibility gate
python3 -m pytest tests/video/site

# All video-related tests, still isolated from unrelated MRP tests
python3 -m pytest tests/video
```

Add strict markers in `pytest.ini` for tests needing native media tools:

- `video_ffmpeg`: invokes local FFmpeg/ffprobe.
- `video_slow`: longer render or performance acceptance.
- `video_external`: an explicitly invoked external-service acceptance test;
  never part of normal local or CI runs.

Normal engine tests must not use the network or require an OpenAI key. Alignment
tests use a fake timestamp provider. A real transcription acceptance run is a
manual or separately triggered test.

### Renderer test levels

1. **Pure contract and math tests**: geometry, tracing, timing, section lookup,
   semantic mappings, casting, and manifest validation.
2. **Synthetic analysis tests**: short generated WAV stems with known pulses and
   intensity changes; verify shared timing, role aggregation, caching, and
   master-only fallbacks.
3. **Frame tests**: small even-sized RGB frames, deterministic configuration,
   fixed fonts, and stable tolerance-based image assertions. Exact hashes are
   used only where dependency versions make them reliable.
4. **Encoding acceptance**: a tiny low-frame-rate MP4 streamed to FFmpeg; assert
   streams, dimensions, duration tolerance, codecs, and render manifest. Do not
   compare encoded MP4 bytes.
5. **Real-song acceptance**: manually invoked short ranges from an operator's
   local assets. These never become repository fixtures.

The existing TypeScript-exported trochoid golden fixture moves with the Python
geometry tests. It remains test data and does not create a JavaScript runtime
dependency.

### Continuous integration lanes

When CI is added or revised, use separate jobs:

- MRP core/schema tests.
- Astro build/site tests.
- Video engine tests with locked video dependencies and FFmpeg.
- Optional slow video acceptance.

A failure in one lane remains visible, but developers can reproduce that lane
without running every other subsystem.

## Dependency strategy

MRP currently has a lightweight `requirements.txt`. Keep heavy media packages
in a separate `requirements-video.txt` during the transplant. It should contain
the locked renderer dependencies and reference the base requirements where
appropriate. Keep OpenAI alignment dependencies separate or optional so an
existing aligned project can render without the API client.

Admin modules must import heavy renderer modules only inside video-specific
routes or worker entry points. Starting MRP Admin for non-video work should fail
with a clear "video dependencies not installed" message only when the user opens
or runs the video feature, not at server import time.

FFmpeg and ffprobe remain native prerequisites and receive an explicit preflight
in the Video stage.

## Renderer transplant strategy

Move the existing headless modules as one coherent engine rather than rewriting
them through admin routes:

```text
alignment, analysis, cards, casting, choreography, encoder, geometry,
mappings, pipeline, presets, project, render_manifest, renderer, text,
tracing, verification
```

Target namespace: `mrp.video`. Keep a small CLI surface under
`scripts/mrp video ...` for diagnosis, automation, and isolated acceptance
testing. The CLI and admin adapter both call the same application functions.

Safe cross-repository sequence:

1. Record the source Spirophonic commit and pass its renderer suite.
2. Copy the engine and fixtures into MRP temporarily, change only the package
   namespace, and establish parity in `tests/video/engine`.
3. Do not add admin coupling until parity passes.
4. Merge the MRP engine transplant.
5. In a separate Spirophonic pull request, remove the Python renderer, Python
   packaging, and renderer-only documentation while leaving all React/TypeScript
   application files unchanged.

Temporary duplication is allowed only across those two reviewed changes. The
final architecture has one renderer implementation in MRP.

## Background-job requirements

MRP's current thread plus SQLite polling pattern is a useful UI foundation, but
full renders require stronger execution semantics.

Extend video jobs with:

- progress percentage and current phase/message;
- heartbeat and start/completion timestamps;
- cancellation request and terminal `cancelled` state;
- artifact and structured-log references;
- interrupted-job recovery on admin restart;
- one active full render per track;
- child-process execution for analysis and rendering so cancellation and
  failures do not destabilize the admin server.

The child process should emit structured progress events. HTMX continues polling
and replacing a job fragment; no websocket framework is required initially.

## Admin UX

Add an optional **Video** workspace stage after **Tracks**. It does not block a
release that has no requested music video.

The stage first shows a track matrix with:

- master, stems, lyrics, and artwork readiness;
- timing, cast, preview, render, and approval state;
- last job and validation result;
- an entry point to `/releases/{release}/tracks/{track}/video`.

The per-track editor follows the user's production workflow.

### 1. Assets

- Reuse track master and lyrics already in MRP.
- Edit/import any number of stems and assign semantic roles.
- Default opening and closing cards from release artwork, with overrides.
- Validate existence, decodability, duration agreement, image dimensions, font,
  FFmpeg, and ffprobe before processing.

The local-first application may begin with path-based import. The UI should call
this **Import assets**, not upload, until browser multipart storage is actually
implemented.

### 2. Sections and timing

- Generate structured sections and aligned line cues.
- Never expose raw `[verse]`, `[chorus]`, or other structure tags as lyric cues.
- Show an audio player, section/line rows, confidence, and start/end controls.
- Use a small JavaScript timeline helper for scrubbing and dragging boundaries.
- Save timing edits to the versioned aligned-lyrics artifact.
- Require explicit review of uncertain/unmatched lines before approval.

### 3. Cast

- Provide deterministic auto-generated casting as the default.
- Show each section as its own scene and preserve a fixed visual identity for
  that section.
- Permit section-type defaults and exact-section overrides.
- Add/remove traces and edit geometry, anchor, scale, color, depth, motion,
  trace, beat, and intensity controls.
- Generate contact sheets and selected-time frames through background jobs.
- Use HTMX for saved forms/fragments and small canvas JavaScript only for local
  interaction.

### 4. Preview

- Render one frame, a section, or a chosen time range.
- Default to low resolution and frame rate.
- Record the project revision/hash used for every preview.
- Let the user compare and discard drafts without modifying public assets.

### 5. Full render and approval

- Preflight exact inputs and estimated work.
- Run an isolated, cancellable full render with progress and ETA.
- Verify audio/video streams, duration, frame count, codecs, and faststart.
- Preserve the renderer manifest and input hashes.
- Require human approval before public-media publication.

## Public media and Astro

Astro integration is deliberately last. Before implementation, choose one
durable MP4 strategy:

1. object storage/CDN with `music_video.public_url`;
2. a production media directory managed by MRP outside Git and copied into the
   build/deploy artifact; or
3. Git LFS, if the repository and deployment environment explicitly adopt it.

Do not commit ordinary full-length MP4 binaries to the main Git object store.

After storage is settled:

- publish only an approved render;
- write `public_url` and `poster` through a validated track slice-save;
- render an accessible `<video controls>` or external player on the song page;
- preserve the existing cover and page layout when no public video exists;
- add metadata only from public fields;
- prove that local paths and internal project data never reach site output;
- include the public media in staging, verification, rollback, and Changes-page
  semantics.

## Implementation milestones

### Milestone 0: Baseline and plan

- Capture the source Spirophonic commit, renderer test result, dependency set,
  and representative frame/render manifests in
  [MRP Music Video Renderer Baseline](<MRP Music Video Renderer Baseline.md>).
- Add this plan to the MRP roadmap.
- No runtime behavior changes.

Exit: both repositories are clean apart from the reviewed planning change and
the source renderer baseline is reproducible.

### Milestone 1: Backward-compatible contracts and test lanes

- Add optional `stems` and `music_video` schema definitions.
- Document the fields in `CONTENT-MODEL.md`.
- Add old-shape, enriched-shape, round-trip, privacy, and Astro compatibility
  fixtures.
- Establish the `tests/video/{engine,admin,contracts,site}` directories and
  commands.
- Add video dependency and pytest-marker configuration without moving the
  renderer yet.

Exit: old records need no edits; repository validation and Astro build pass;
new internal fields do not alter or leak into public output.

### Milestone 2: Renderer transplant with parity

MRP-side status 2026-07-20: implemented on
`feat/music-video-designer-plan`. The isolated engine, diagnostics, locked
optional dependencies, reference-project validation, and FFmpeg acceptance are
in MRP. The separate post-merge Spirophonic Python cleanup remains deferred;
its React application is untouched.

- Move the headless Python engine and its tests into `mrp.video`.
- Preserve deterministic geometry, casting, frames, encoding, verification, and
  manifest behavior.
- Add `scripts/mrp video` diagnostic commands.
- Run the isolated engine lane and tiny FFmpeg acceptance test.
- Remove the Python engine from Spirophonic only after MRP parity merges; do not
  edit its React application.

Exit: MRP can render the reference project without importing admin or Astro
code, and Spirophonic has no second production renderer.

### Milestone 3: MRP project adapter and artifact lifecycle

Status 2026-07-20: implemented on `feat/music-video-designer-plan`. The
track-scoped CLI, symbolic versioned project, ignored runtime workspace,
deterministic semantic aggregation, input fingerprints, stale-artifact index,
and preflight reports are documented in
[MRP Music Video Track Workflow](<MRP Music Video Track Workflow.md>).

- Convert release/track data into renderer project models.
- Add semantic aggregation for multiple stems per role.
- Create versioned project/alignment files and ignored processed directories.
- Add input hashing, stale-artifact detection, and preflight reports.
- Prove master-only and multi-stem projects.

Exit: a CLI command can prepare, analyze, align, preview, and render one MRP
track using MRP-owned data and artifact conventions.

### Milestone 4: Video jobs and workspace shell

Status 2026-07-20: implemented on `feat/music-video-designer-plan`. MRP Admin
now exposes an optional Video stage immediately after Tracks, with a per-track
readiness/artifact matrix and a path-based asset editor for masters and any
number of optional semantic stems. Lightweight route-side checks cover tools,
files, audio decodability/duration agreement, artwork dimensions, lyrics, and
font readiness without importing the renderer stack at admin startup.

Video preparation, analysis, and full rendering run in isolated Python child
processes. A dedicated SQLite job record and append-only JSONL event log retain
percentage, phase/message, heartbeat, timestamps, result/artifact/log
references, cancellation state, and terminal outcome. HTMX polls the job
fragment, one active full render is allowed per track, and admin startup either
reattaches monitoring to a matching live worker or records the missing worker
as interrupted.

- Add the optional Video stage and per-track status matrix.
- Add process-backed jobs, progress, polling, cancellation, and interruption
  recovery.
- Add asset/stem editing and validation.

Exit: an operator can prepare a track and observe/cancel analysis and render
jobs without leaving MRP Admin.

### Milestone 5: Timing editor

Status 2026-07-20: implemented on `feat/music-video-designer-plan`. Alignment
is available as an isolated Video job and writes the existing track-scoped,
versioned `lyrics.aligned.yaml` contract. The timing page presents native master
audio playback plus a synchronized scrubber, section and lyric-cue boundaries,
confidence/status badges, range previews, playhead capture, and explicit review
state for sections and lines. Saves preserve canonical text, section identities,
alignment provenance, confidence, and match status while atomically validating
ordered, non-overlapping timing against the master duration.

Nullable review markers keep all earlier aligned files valid. Uncertain and
unmatched cues must be explicitly reviewed before the track advances from
`draft` to `timed`. Bracketed structure directives remain section metadata and
are rejected by the renderer contract if presented as lyric cue text.

- Add section generation, alignment, confidence review, and manual timing edits.
- Add audio scrubbing and boundary controls with minimal vanilla JavaScript.
- Save reviewed timing as versioned source.

Exit: every displayed lyric cue and section boundary can be reviewed and fixed
before visual work begins, with structure tags excluded from display cues.

### Milestone 6: Section-casting editor

Status 2026-07-20: implemented on `feat/music-video-designer-plan`. The
per-track casting page resolves every timed section through the renderer's
deterministic auto cast, a case-insensitive section-type default, or an exact
section override. Operators can switch scope, materialize/reset automatic
casts, add or remove traces, and edit geometry, anchors, scale, color, depth,
motion, trace behavior, audio drivers, beat response, and intensity controls.
All decisions are validated through the shared renderer contracts and saved
atomically in the track's versioned `project.yaml`.

Frame and all-section contact-sheet previews run as isolated process jobs.
Their artifact records include the current input fingerprint, while a casting
save marks the previous preflight stale without deleting earlier previews or
renders. The admin-only gallery labels old output stale, and a successful
current preview advances a cast track to `previewed`. A renderer test reloads
an exact-section cast from YAML and proves repeated frame pixels are identical.

- Add auto casting, section/type selection, trace CRUD, parameter controls,
  contact sheets, and frame previews.
- Save casts to the versioned project and invalidate stale previews/renders.

Exit: the user can cast substantially different scene geometry per section and
reproduce the same frame from the saved project.

#### Actor-first casting revision

Status 2026-07-21: implemented on `feat/music-video-designer-plan`. The first
casting editor exposed renderer traces directly and therefore mixed visual
identity design, scene casting, and scene direction in one large form. The
authoring contract is now additive and separates those decisions:

- The global library holds named, reusable visual identities containing one or
  more spirogram components. Component topology, color, material, and base
  behavior belong to the identity.
- The repository-wide actor library stores reusable definitions under
  `assets/source/video/actors/`. Import creates a full track-project snapshot
  plus a source revision, so library updates are explicit rather than action at
  a distance. The track actor then receives one musical character such as bass,
  drums, or vocals. That “reacts to” assignment is stable across the track.
- A scene cast assigns project actors to a section type or an exact section.
  Direction controls only the actor's performance in that scene: position,
  scale, opacity, visibility, layer, hue, and additional rotation. It cannot
  change the actor's track-level musical character.
- The renderer still consumes `SectionCompositionConfig`. Actor casts compile
  deterministically into the established trace contract before frame rendering,
  preserving renderer isolation and deterministic output.
- Projects containing only the original embedded `section_compositions` and
  `composition_overrides` remain valid. Actor casts take precedence when
  present, then resolution falls through the original exact, type, automatic,
  and global-layer paths.

The admin page presents Actor Library and Actor Designer as track-level
surfaces above the scene workspace. Actor mutations use a separate track route
and do not read or alter the selected section. Scene selection and type/exact
scope apply only to Scene Casting. The page includes a live spirogram identity
preview, recommended/adopt-current onboarding, project snapshots,
global-library publish/import, repeated-section inheritance, exact-scene
direction, and the existing private frame/contact-sheet jobs. Advanced
component and whole-scene controls remain available without dominating the
normal casting workflow.

### Milestone 7: Draft and full rendering

Status 2026-07-20: implemented on `feat/music-video-designer-plan`. The
per-track rendering workspace can launch a timed section or custom range as an
isolated draft job, retain independently named draft iterations and manifests,
play them through private admin-only routes, and discard one draft without
touching versioned source, full renders, or public assets.

Full rendering now has a separate preflight job that reports the exact input
fingerprint, frame count, output profile, card inclusion, and estimated raw
stream work. The full-render worker is pinned to that fingerprint and refuses
to encode if the project or inputs changed after planning. Existing process
jobs provide live progress, heartbeats, cancellation, restart recovery, and
one-active-full-render enforcement; the renderer atomically publishes only an
FFprobe-verified MP4 and its render manifest.

Approval rechecks the versioned project, aligned timing, master, enabled stems,
artifact fingerprint, full-render classification, verification result, output
hash, and manifest before changing only the selected track to `approved`. The
local approval record preserves the reviewed project hash, input hashes,
manifest hash, and output hash, while stale iterations remain visible but
cannot be approved.

- Add range/section draft rendering and iteration history.
- Add full render preflight, progress, cancellation, verification, and approval.
- Preserve render manifests and prevent stale-project approval.

Exit: an approved full MP4 is reproducible from the reviewed project and input
hashes, entirely within MRP.

### Milestone 8: Public-media publication and Astro player

Status 2026-07-20: implemented on `feat/music-video-designer-plan`. Approved
full renders publish into a content-addressed durable store outside both Git and
the disposable site-output tree. `MRP_PUBLIC_MEDIA_ROOT` selects the store and
defaults to `~/.mrp/public-media/maricoparecords`. Publication copies and
re-hashes the verified MP4 plus release-cover poster, then writes only public
URLs and `status: published` to the selected track. A versioned, public-only
`publication.yaml` records the project, input, manifest, MP4, and poster hashes
for Changes-page review without exposing production paths.

Public display has a separate explicit gate: the optional per-track
`music_video.opt_in` boolean must be exactly `true` in addition to published
status and valid public media. The Admin rendering page requires an unchecked
Opt In checkbox for initial publication and supports later opt-out/re-opt-in
without deleting durable media. Approval by itself never opts a track into the
site.

Astro overlays only currently opted-in local media into each immutable build
artifact and renders an accessible player plus `VideoObject` metadata on album
track pages or the single's release page. Unchecked, unpublished, and legacy
tracks retain the previous markup. Verification checks the player, MP4, poster,
and private-path boundary; the existing whole-artifact stage and rollback paths
therefore carry the exact public media automatically.

- Choose and implement durable public MP4 storage.
- Publish approved media and poster assets.
- Add the conditional Astro song-page player and public metadata.
- Extend stage, verify, rollback, and privacy tests.

Exit: an approved video survives the production workflow and appears on its song
page; releases without videos render exactly as before.

## Proposed pull-request sequence

1. Plan and architecture record.
2. Track contracts plus compatibility test lanes.
3. Renderer transplant and isolated engine tests.
4. Spirophonic Python cleanup, React untouched.
5. MRP project adapter and artifact lifecycle.
6. Process-backed video jobs and Video workspace shell.
7. Asset and timing editor.
8. Casting editor and frame/contact-sheet previews.
9. Draft/full rendering and approval.
10. Public-media storage, Astro player, and deployment verification.

Each pull request must leave the existing MRP release workflow usable and pass
the smallest relevant test lanes plus repository validation. Schema or public
site changes additionally require the explicit site compatibility lane.

## Global completion criteria

- The Spirophonic React site is unchanged by the migration.
- MRP is the sole owner of the production Python renderer.
- Existing MRP release YAML remains valid without backfill.
- Stems and private production paths never appear in public output.
- Renderer tests run independently with `pytest tests/video/engine`.
- No normal test requires network access or an API key.
- Timing and casting decisions are versioned and reproducible.
- Generated caches and draft/full binaries are excluded from normal Git history.
- Full renders are cancellable, verified, and cannot be published without human
  approval.
- Astro changes are conditional and preserve current pages for tracks without a
  published video.

## Recommended starting point

Begin with Milestone 1, not the renderer copy. The optional schema contract,
privacy guarantees, and test lanes establish the safe landing zone for every
later change and prove that adding stems cannot break or leak into Astro.
