# MRP Music Video Live Preview Milestones

Last updated: 2026-07-27

Overall status: **Complete**

Implementation plan:
[MRP Music Video Live Preview Plan](<MRP Music Video Live Preview Plan.md>)

Milestone 0 evidence:
[MRP Music Video Live Preview Spike](<MRP Music Video Live Preview Spike.md>)

Milestone 5 evidence:
[MRP Music Video Live Preview Release Gates](<MRP Music Video Live Preview Release Gates.md>)

This document is the durable progress ledger for the non-rendering,
audio-reactive Scene Preview and Full-track Preview work. Update it in the same
change that starts, materially advances, or completes a milestone.

## Status definitions

- **Not started** — no implementation work for the milestone has landed.
- **In progress** — implementation exists but one or more exit criteria remain.
- **Blocked** — progress requires a named decision or external state change.
- **Complete** — every exit criterion is satisfied and completion evidence is
  recorded below.

A milestone is not complete merely because its code exists locally. Relevant
tests, manual checks, privacy checks, and documentation must be recorded.

## Current position

Current next action: **Plan complete — review and commit the working tree when
ready**

| Milestone | Status | Started | Completed | Completion evidence |
|---|---|---:|---:|---|
| Planning baseline | Complete | 2026-07-27 | 2026-07-27 | Plan and tracker created from the current Admin/renderer contracts. |
| 0. Contract and performance spike | Complete | 2026-07-27 | 2026-07-27 | [Measured spike report](<MRP Music Video Live Preview Spike.md>) freezes the version-1 payload and budgets. |
| 1. Shared absolute-time browser engine | Complete | 2026-07-27 | 2026-07-27 | Absolute-time engine, Scene Preview integration, focused tests, and real-page check complete. |
| 2. Private preview document | Complete | 2026-07-27 | 2026-07-27 | Version-1 adapter, private route, read-only cache lookup, bounds, and privacy gates complete. |
| 3. Audio-reactive Scene Preview | Complete | 2026-07-27 | 2026-07-27 | Canonical state, Python/JavaScript parity, live unsaved overlays, transitions, and real-browser checks complete. |
| 4. Full-track Preview | Complete | 2026-07-27 | 2026-07-27 | Dedicated page, saved-state transport, every-scene jumps, lyrics, stale detection, fallbacks, and real-browser checks complete. |
| 5. Fidelity, performance, and release gates | Complete | 2026-07-27 | 2026-07-27 | [Release-gate report](<MRP Music Video Live Preview Release Gates.md>) records passing performance, fidelity, accessibility, privacy, and compatibility evidence. |

## Existing baseline checklist

These capabilities predate this plan and are inputs, not newly completed Live
Preview milestones.

- [x] Private admin route serves the selected track master.
- [x] Timing editor has master playback, seeking, and aligned scene/lyric time.
- [x] Actor Preview draws every current geometry family and trace behavior.
- [x] Scene Preview draws a compiled selected-scene composition at 960×540.
- [x] Scene Preview can loop its selected range with master audio.
- [x] Scene Preview reflects unsaved placement and direction fields.
- [x] Python caches normalized master and semantic stem analysis.
- [x] Python resolves scene styles, gaps, transitions, trace time, and rotation.
- [x] Rendered frame, contact-sheet, draft, and full-render confirmation exists.
- [x] One shared absolute-time Scene/Full-track browser engine.
- [x] Safe all-scene preview document.
- [x] Canonical sampled audio/choreography state in the browser.
- [x] Audio-reactive Scene Preview.
- [x] Full-track live canvas and transport.
- [x] Measured fidelity and performance release gates.

## Settled decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-07-27 | Live Preview is a non-rendering, private Admin feature. | It must start without MP4 generation and must not create public or approval state. |
| 2026-07-27 | Scene and Full-track Preview share one browser engine. | Two implementations would drift and make scene/full-track comparison unreliable. |
| 2026-07-27 | `audio.currentTime` is the only playback clock. | Absolute master time preserves analysis, transitions, trace phase, and seeking. |
| 2026-07-27 | Python samples canonical audio and choreography state. | Avoid duplicating feature extraction and integrated choreography in JavaScript. |
| 2026-07-27 | JavaScript applies the small layer mapping and draws live shapes. | Scene Casting must keep reacting to unsaved actor/direction edits. |
| 2026-07-27 | Full-track Preview shows saved state; Scene Preview may overlay unsaved local edits. | Prevent a mixed, misleading whole-track project while keeping editing responsive. |
| 2026-07-27 | Missing/stale analysis falls back to geometry-only mode. | Page navigation must never trigger an implicit expensive analysis run. |
| 2026-07-27 | Rendered frames remain authoritative. | Canvas and OpenCV differ in font metrics, rasterization, and exact pixels. |
| 2026-07-27 | Opening/closing cards are outside the first release. | The initial Full-track Preview follows master-audio time only. |
| 2026-07-27 | Live Preview does not advance `music_video.status`. | Playback is ephemeral and is not a fingerprinted render artifact. |
| 2026-07-27 | Version 1 samples canonical state at 20 Hz into an interleaved little-endian `Float32` block encoded as base64. | It was the smallest lossless tested format, measuring 818–880 KB and at most 7.0 ms p95 browser decode for the two current tracks. |
| 2026-07-27 | Sections reference a deduplicated composition table. | Repeating trace geometry for every section wastes payload without improving browser lookup. |
| 2026-07-27 | Version 1 rejects `Float16` and other lossy state quantization. | About 0.062 maximum absolute error can visibly shift integrated trace and rotation time. |
| 2026-07-27 | Canvas redraw targets 30 fps, adapts to 20 fps for expensive scenes, and has a 15 fps floor. | Current bridge scenes measured about 23–24 fps in headless software rendering; audio time must remain authoritative. |
| 2026-07-27 | Preview data uses the existing isolated video interpreter when the base Admin interpreter lacks renderer dependencies. | The normal Admin remains lightweight and importable, while cached NumPy analysis can still produce the canonical audio-reactive document without a job, artifact, or status write. |

Add decisions here only when they change or constrain later implementation.
Do not silently overwrite earlier decisions; append a superseding row.

## Milestone 0 — Contract and performance spike

Status: **Complete** — 2026-07-27

Objective: freeze a measured version-1 preview document and implementation
budget before committing to an encoding or sampling rate.

### Work checklist

- [x] Record master duration, section count, actor count, trace count, largest
  geometry, aligned lyric count, and current analysis size for
  `A Distant Memory`.
- [x] Record the same measurements for `A Good Day to Be`.
- [x] Prototype the logical safe serializer without writing private paths.
- [x] Compare plain JSON, interleaved `Float32`, and quantized data only if
  needed.
- [x] Compare 15 Hz and 20 Hz state sampling against the current canvas cost.
- [x] Measure server generation time from an existing analysis cache.
- [x] Measure response bytes, browser parse/decode time, and representative
  canvas frame cost; explicitly defer end-to-end page/first-frame timing until
  the route and shared engine exist.
- [x] Confirm the spike never computes missing/stale analysis.
- [x] Freeze the version-1 fields, encoding, sample rate, limits, and fallback.
- [x] Update the implementation plan with the accepted measured targets.

### Exit criteria

- [x] Both real tracks have recorded measurements.
- [x] One encoding and state-sampling rate are selected with evidence.
- [x] Transfer, first-frame, and redraw budgets are accepted or revised.
- [x] The version-1 logical contract contains no private path or media data.
- [x] The next milestone can implement against a frozen contract decision.

### Completion evidence

- Branch/commit/PR: `main`; documentation working tree only, no commit or PR.
- Measurement report:
  [MRP Music Video Live Preview Spike](<MRP Music Video Live Preview Spike.md>).
- Commands/tests: temporary `python3 /tmp/mrp-live-preview-spike.py`; cached
  headless Chromium parse/decode and 960×540 canvas fixtures; private-data
  pattern scan.
- Manual/browser evidence: two real project inventories; 15/20 Hz payload
  generation; three encodings; 12-repeat parse/decode timings; five 120-frame
  canvas batches per representative scene.
- Decisions added or superseded: 20 Hz base64 little-endian `Float32`,
  deduplicated compositions, no lossy quantization, and adaptive 30/20/15 fps
  drawing.
- Notes: `A Good Day to Be` had no analysis cache. Zero normalized audio was
  used only for bounded-size/choreography-cost measurement; the cache remained
  absent and the implemented route must return geometry-only mode.

## Milestone 1 — Shared absolute-time browser engine

Status: **Complete** — 2026-07-27

Objective: extract the existing scene drawing/transport behavior into a
reusable engine with `renderAt(masterTime)` while preserving current editor
behavior.

Depends on: Milestone 0.

### Work checklist

- [x] Separate geometry helpers from track-timed preview behavior.
- [x] Create the reusable Live Preview module.
- [x] Add `loadPreview`, `renderAt`, play, pause, seek, bounded-loop, and
  destroy behavior.
- [x] Make paused seeking redraw the selected time rather than a fully revealed
  static curve.
- [x] Cache geometry by trace identity and geometry signature.
- [x] Move the current Scene Preview off the large inline script.
- [x] Preserve Scene Casting live fields, dragging, selection, labels, guides,
  audio toggle, and looping.
- [x] Keep Actor Preview actor-local and behavior-compatible.
- [x] Add DOM-independent Node tests for clock, state lookup, and lifecycle.
- [x] Confirm no new framework or runtime dependency is required.

### Exit criteria

- [x] Scene Preview uses the shared engine.
- [x] Absolute-time render, paused seek, and bounded loop tests pass.
- [x] Existing Actor and Scene Preview controls behave as before.
- [x] Repeated navigation/HTMX replacement leaves no duplicate animation loop
  or audio listener.
- [x] Existing video admin and renderer lanes remain green.

### Completion evidence

- Branch/commit/PR: `main`; uncommitted working tree, no PR.
- Python tests: `24 passed` in focused casting tests; `106 passed` in the full
  video Admin lane; `149 passed` with three dependency deprecation warnings in
  the isolated renderer-engine lane.
- JavaScript tests: `7 passed` for absolute render/seek, silent and audio
  clocks, bounded and terminal ranges, state sample lookup, and teardown.
- Manual routes checked:
  `/releases/a-distant-memory/tracks/a-distant-memory/video/casting`,
  `/static/video-live-preview.js`, and the private audio route.
- Performance observation: normalized numeric geometry is now held in a
  bounded signature cache; scheduled/adaptive redraw performance remains a
  Milestone 5 gate.
- Notes: a 1440×8000 headless Chromium check rendered the selected Adlib scene
  with both actors, labels, frame guides, and 0% absolute scene progress. No
  framework or package dependency was added.

## Milestone 2 — Private preview document

Status: **Complete** — 2026-07-27

Objective: expose a bounded, versioned, fingerprinted, private document
containing all saved scenes plus safe sampled renderer state.

Depends on: Milestones 0 and 1.

### Work checklist

- [x] Add the admin live-preview adapter without adding admin imports to
  `mrp.video`.
- [x] Validate the project and aligned lyrics before serialization.
- [x] Resolve every scene through the canonical composition order.
- [x] Serialize every renderer field required by the browser allowlist.
- [x] Include stable deterministic phase and preset values.
- [x] Read only a valid existing analysis cache.
- [x] Sample canonical `AudioVisualState` and `ChoreographyState`.
- [x] Add source-revision metadata and current/stale checks.
- [x] Return explicit audio-reactive or geometry-only mode.
- [x] Enforce duration, sample-count, trace-count, and response-size bounds.
- [x] Add the private route and structured error responses.
- [x] Prove the request performs no project, content, job, artifact, or status
  write.
- [x] Scan route bodies and fixtures for all known private path prefixes.

### Exit criteria

- [x] An analyzed project returns the selected version-1 document
  deterministically.
- [x] A missing/stale analysis returns geometry-only mode without analysis
  execution.
- [x] Exact/type/automatic/legacy scene resolution is covered.
- [x] Project, timing, and analysis changes alter source revision correctly.
- [x] Payload budgets pass for both representative tracks.
- [x] No private path, filename, PCM data, or cache location reaches the
  response.

### Completion evidence

- Branch/commit/PR: `main`; uncommitted working tree, no PR.
- Contract fixture/version: version 1, 20 Hz, 36-column interleaved
  little-endian `Float32`, base64 JSON envelope.
- Python tests: `118 passed` in the complete video Admin lane and `149 passed`
  with three existing dependency deprecation warnings in the renderer-engine
  lane. Twelve focused adapter tests cover deterministic serialization,
  analysis current/stale behavior, composition modes, revision changes,
  bounds, privacy, the route, and isolated-interpreter dispatch.
- Payload measurements: `A Distant Memory` returned audio-reactive mode,
  4,097 samples, and 811,232 bytes in 905.96 ms locally; the normal
  system-Python Admin path completed through the isolated interpreter in
  1,191.27 ms. `A Good Day to Be` returned bounded geometry-only mode in
  56,568 bytes and 56.19 ms because its analysis cache is absent.
- Privacy scan: both real documents and fixtures were checked for `/home/`,
  `/mnt/`, `master_path`, `cache_dir`, and common audio suffixes with no
  matches. Source-file size/mtime snapshots were unchanged by generation.
- Notes: visual/casting edits change the project revision but do not stale
  otherwise-current audio analysis. Changed analysis settings, changed/newer
  audio, invalid cache metadata, or duration mismatch fall back to an explicit
  geometry-only reason. The route sets `private, no-store`, a content ETag,
  and structured safe errors.

## Milestone 3 — Audio-reactive Scene Preview

Status: **Complete** — 2026-07-27

Objective: make the existing Scene Preview use canonical sampled audio and
choreography state at absolute master time while retaining live unsaved edits.

Depends on: Milestones 1 and 2.

### Work checklist

- [x] Interpolate canonical preview-state samples.
- [x] Port the pure layer-mapping formula and preset constants.
- [x] Add Python-versus-JavaScript mapping parity fixtures.
- [x] Apply semantic energy/accent drivers to live scene shapes.
- [x] Apply canonical scale, rotation, opacity, line width, hue, trail, beat,
  visibility, and background response.
- [x] Preserve deterministic phase and integrated trace/rotation time.
- [x] Blend previous/current compositions during the selected scene transition.
- [x] Keep the loop bounded to the selected scene while retaining absolute
  master time.
- [x] Overlay unsaved assignment, placement, visibility, wardrobe, and energy
  fields.
- [x] Display Current, Unsaved scene edits, Geometry only, and Stale states.
- [x] Retain Render frame to confirm.

### Exit criteria

- [x] Scene Preview reacts to master/drums/bass/vocals/instruments as configured.
- [x] The same absolute time produces parity with expected Python mapping state.
- [x] Starting, pausing, seeking, and looping do not reset trace phase.
- [x] Unsaved edits update live without mutating the loaded base document.
- [x] Geometry-only mode remains usable and clearly labeled.
- [x] Existing Scene Casting save and drag behavior remains green.

### Completion evidence

- Branch/commit/PR: `main`; uncommitted working tree, no PR.
- Python tests: `120 passed` in the complete video Admin lane and `149 passed`
  with three existing dependency deprecation warnings in the renderer-engine
  lane. The Admin lane regenerates the shared mapping fixture from canonical
  Python and covers the expanded Scene Preview payload/template.
- JavaScript/parity tests: `10 passed`; version-1 Float32 decode,
  interpolation, absolute clocks, lifecycle, Python mapping parity, renderer
  color math, and reactive background are covered. Both JavaScript modules
  also pass `node --check`.
- Rendered-frame comparison times: on the real `A Distant Memory` Adlib scene,
  canvas hashes differed at 0.75s and 2.75s, and returning to 0.75s reproduced
  the exact first hash. A local unsaved scale edit produced a third hash and
  the `Unsaved scene edits` state. Exact-pixel authority remains the existing
  rendered-frame control.
- Manual route/project checked: real Admin routes for `A Distant Memory` and
  `A Good Day to Be`; casting page, static modules, data document, and private
  audio returned 200/206 as applicable. Headless Chromium showed
  `Current · audio reactive` for the analyzed track and
  `Geometry only · Run Analyze` for the missing-analysis track.
- Notes: selected-scene looping remains bounded while all state, trace phase,
  integrated trace/rotation time, and seeking stay in absolute master time.
  Text actors receive the renderer's deterministic phase per contour.

## Milestone 4 — Full-track Preview

Status: **Complete** — 2026-07-27

Objective: let an operator play and scrub the complete saved music-video project
against the track master without starting an MP4 or frame-sequence job.

Depends on: Milestones 1–3.

### Work checklist

- [x] Add the dedicated per-track Live Preview route and template.
- [x] Link it between Casting and Rendering in the Video workspace.
- [x] Add accessible play/pause, scrubber, reset, time, and scene-jump controls.
- [x] Follow the complete master from time zero through duration.
- [x] Resolve current and previous scene from sampled canonical state.
- [x] Draw gaps and transition spans without restarting phase.
- [x] Add current-scene and current-lyric text indicators.
- [x] Draw lyric cue timing/fades with documented browser font differences.
- [x] Support audio-reactive and geometry-only modes.
- [x] Detect and display stale loaded state without swapping mid-play.
- [x] Add reload and Render frame to confirm actions.
- [x] Verify that playback creates no artifact or status change.

### Exit criteria

- [x] Every timed scene is reachable by playback, scrubbing, and scene jump.
- [x] Gaps, cuts, and configured transition curves follow canonical timing.
- [x] Scene and Full-track Preview match at the same saved master time,
  excluding Scene Casting overlays.
- [x] Lyrics and active-scene text remain synchronized after arbitrary seeks.
- [x] Track end, pause, reset, and page teardown are deterministic.
- [x] No MP4/frame job, artifact record, source write, or status change occurs.

### Completion evidence

- Branch/commit/PR: `main`; uncommitted working tree, no PR.
- Python/route tests: `121 passed` in the complete video Admin lane; the new
  route/template test verifies private no-store delivery, workspace ordering,
  controls, frame confirmation, and a read-only filesystem snapshot.
- JavaScript tests: `14 passed` for the shared engine and version-1 state,
  including sampled-versus-geometry scene lookup, canonical transition
  blending/cuts, absolute lyric fades, and revision-staleness comparison.
- Real tracks checked: `A Distant Memory` in audio-reactive mode with eight
  scene jumps and `A Good Day to Be` in explicit geometry-only mode with
  eleven scene jumps. Every button resolved its intended scene.
- Scene/full-track comparison times: at 42.25s in the saved Chorus,
  Full-track Preview and Scene Preview returned the same three trace IDs and
  identical mapped anchors, scale, opacity, line width, color, rotation,
  trace time, trail, and depth after Scene Preview finished loading.
- Notes: real master-audio play advanced the audio-authoritative clock,
  pause froze it, reset returned to 0 and the first scene, and the frame input
  followed every seek. A simulated newer timing revision displayed
  `Stale loaded state · Reload` while retaining the same loaded document and
  continuing playback. Server logs contained GET/206 traffic only; playback
  did not launch a frame or MP4 job.

## Milestone 5 — Fidelity, performance, and release gates

Status: **Complete** — 2026-07-27

Objective: close the high-value parity gaps, enforce measured limits, and
record the evidence needed to treat Live Preview as a durable editor feature.

Depends on: Milestones 0–4.

### Work checklist

- [x] Compare geometry, placement, transition, audio response, background,
  color, opacity, line width, trace phase, and lyrics against rendered frames.
- [x] Implement or explicitly document remaining blend/raster approximations.
- [x] Re-run payload and frame-rate measurements on both representative tracks.
- [x] Verify adaptive redraw does not introduce audio-clock drift.
- [x] Exercise reduced-motion and keyboard operation.
- [x] Exercise missing, stale, oversized, and malformed preview documents.
- [x] Verify no analysis job runs on page navigation.
- [x] Run private-path scans over responses, templates, fixtures, and built
  public output.
- [x] Run isolated video admin, JavaScript, renderer, contract, and public-site
  compatibility lanes as applicable.
- [x] Run repository validation and refresh Graphify.
- [x] Update user-facing workflow documentation and help text.
- [x] Record intentional differences from rendered output.

### Exit criteria

- [x] Performance budgets pass or have an approved documented revision.
- [x] Fidelity comparison evidence covers boundaries and representative scenes.
- [x] Privacy and no-write/status guarantees pass.
- [x] Accessibility checks pass.
- [x] All relevant isolated and compatibility lanes pass.
- [x] The Live Preview/Rendered preview authority distinction is documented in
  UI and workflow docs.

### Completion evidence

- Branch/commit/PR: `main`; uncommitted working tree, no PR.
- Test summary: `19 passed` in the DOM-independent JavaScript lane,
  `123 passed` in the complete video Admin lane, and `149 passed` with three
  existing dependency deprecation warnings in the isolated renderer-engine
  lane. Contract/public-site compatibility added `29 passed`; verification,
  deployment-contract, and schema compatibility added `30 passed`.
- Performance report:
  [MRP Music Video Live Preview Release Gates](<MRP Music Video Live Preview Release Gates.md>)
  records both real tracks within response, decode, first-frame, seek, adaptive
  redraw, and audio-clock budgets.
- Fidelity comparison report: renderer-versus-Canvas evidence at 20.000,
  42.267, and 50.000 seconds covers a gap transition, stable chorus, lyric
  timing, and the expensive bridge. Same-time Scene and Full-track state also
  matched exactly after excluding editing overlays.
- Privacy/public-build scan: both private responses, source templates,
  fixtures, scripts, and build `20260727T230457144918Z-site` passed the tested
  private-path patterns. The public build contains no Live Preview route,
  bundle, payload marker, or private video-project path.
- Documentation updated: implementation plan, milestone ledger, release-gate
  report, Track Workflow, Designer Plan, Admin Milestones, and in-product help.
- Notes: reduced motion selected 15 fps; native keyboard play, pause, scrub,
  and scene jump worked. Repeated navigation left `video_jobs` at 28 rows with
  the same latest creation time and did not create analysis for the
  geometry-only track.

## Validation log

Append one row for meaningful milestone validation. Do not replace earlier
evidence when a later run fails or supersedes it.

| Date | Milestone | Revision | Command/check | Result | Evidence/notes |
|---|---|---|---|---|---|
| 2026-07-27 | Planning baseline | working tree | Documentation review | Complete | Current audio, canvas, scene serializer, analysis, choreography, and renderer surfaces inventoried. |
| 2026-07-27 | Planning baseline | working tree | `canto repo doctor` | Pass | Repository identity, policy, instructions, Git readiness, and configured Worker surfaces passed. |
| 2026-07-27 | Planning baseline | working tree | Markdown links, trailing whitespace, and `git diff --check` | Pass | Companion files exist and documentation changes are whitespace-clean. |
| 2026-07-27 | Planning baseline | working tree | `graphify update .` | Pass | Generated graph rebuilt with 5,256 nodes, 12,880 edges, and 602 communities; generated output remains uncommitted. |
| 2026-07-27 | 0 | working tree | Two-track Python payload spike at 15 Hz and 20 Hz | Pass | 20 Hz Float32 documents measured 817,538 and 880,309 bytes; generation measured 783.25 and 285.98 ms median. |
| 2026-07-27 | 0 | working tree | Headless Chromium JSON parse/base64 decode | Pass | Selected encoding measured 2.3–2.5 ms median and at most 7.0 ms p95. |
| 2026-07-27 | 0 | working tree | Headless Chromium 960×540 canvas baseline | Budget revised | Typical scenes exceeded 30 fps; bridge scenes measured 22.59 and 23.57 fps, establishing adaptive 20 fps and 15 fps floor behavior. |
| 2026-07-27 | 0 | working tree | Missing-cache and generated-document private-data checks | Pass | No analysis cache was created for `A Good Day to Be`; generated documents contained no tested private path or media pattern. |
| 2026-07-27 | 0 | working tree | Markdown links, trailing whitespace, and `git diff --check` | Pass | Plan, tracker, spike report, and parent-roadmap links are present and whitespace-clean. |
| 2026-07-27 | 0 | working tree | `graphify update .` | Pass | Generated graph rebuilt with 5,271 nodes, 12,894 edges, and 616 communities; generated output remains uncommitted. |
| 2026-07-27 | 1 | working tree | `node tests/video/admin/js/video-live-preview.test.mjs` | Pass | Seven tests cover absolute render/seek, wall/audio clocks, range behavior, state lookup, and lifecycle cleanup. |
| 2026-07-27 | 1 | working tree | `.venv/bin/pytest -q tests/video/admin` | Pass | 106 video Admin tests passed. |
| 2026-07-27 | 1 | working tree | `.venv/bin/pytest -q tests/video/engine` | Pass | 149 renderer-engine tests passed with three existing dependency deprecation warnings. |
| 2026-07-27 | 1 | working tree | Local Admin plus headless Chromium on `A Distant Memory` | Pass | Page and script returned 200, audio returned 206, and the real Scene Preview rendered actors, overlays, and absolute range progress. |
| 2026-07-27 | 2 | working tree | `.venv/bin/pytest -q tests/video/admin` | Pass | 118 video Admin tests passed, including 12 Live Preview adapter/route tests. |
| 2026-07-27 | 2 | working tree | `.venv/bin/pytest -q tests/video/engine` | Pass | 149 renderer-engine tests passed; the read-only cache path is covered, with three existing dependency deprecation warnings. |
| 2026-07-27 | 2 | working tree | Two-track production adapter measurement | Pass | Audio-reactive `A Distant Memory`: 811,232 bytes/905.96 ms; geometry-only `A Good Day to Be`: 56,568 bytes/56.19 ms; both under bounds. |
| 2026-07-27 | 2 | working tree | System-Python Admin import and isolated-interpreter generation | Pass | Base Admin imported without NumPy/librosa; isolated generation returned the same 811,232-byte audio-reactive document in 1,191.27 ms. |
| 2026-07-27 | 2 | working tree | Determinism, read-only snapshots, privacy patterns, `ruff check`, and `git diff --check` | Pass | Identical sources produced identical bodies/ETags; no source mutation or tested private-data match; lint and whitespace checks passed. |
| 2026-07-27 | 2 | working tree | `graphify update .` | Pass | Generated graph rebuilt with 5,341 nodes, 13,189 edges, and 608 communities; generated output remains uncommitted. |
| 2026-07-27 | 3 | working tree | `node tests/video/admin/js/video-live-preview.test.mjs` | Pass | Ten tests cover clocks/lifecycle, state decode/interpolation, Python mapping parity, renderer color, and reactive background. |
| 2026-07-27 | 3 | working tree | `.venv/bin/pytest -q tests/video/admin` | Pass | 120 video Admin tests passed, including canonical Python fixture regeneration and casting-page integration. |
| 2026-07-27 | 3 | working tree | `.venv/bin/pytest -q tests/video/engine` | Pass | 149 renderer-engine tests passed with three existing dependency deprecation warnings. |
| 2026-07-27 | 3 | working tree | Real Admin plus headless Chromium on `A Distant Memory` | Pass | Current audio-reactive state rendered; 0.75/2.75s hashes differed, repeated 0.75s was identical, and an unsaved scale edit changed both canvas and status. |
| 2026-07-27 | 3 | working tree | Real Admin plus headless Chromium on `A Good Day to Be` | Pass | Missing analysis stayed drawable and displayed `Geometry only · Run Analyze`; data and audio routes remained available without creating analysis. |
| 2026-07-27 | 3 | working tree | Two-track privacy/read-only scan, `ruff check`, JavaScript syntax, and `git diff --check` | Pass | Current documents were 811,232 and 57,448 bytes with no tested private-data match or canonical-file mutation; lint, syntax, and whitespace gates passed. |
| 2026-07-27 | 4 | working tree | Complete Admin/JavaScript lanes and two-track real-browser transport | Pass | 121 Admin and 14 JavaScript tests passed; all eight and eleven authored scenes were reachable, same-time Scene/Full state matched, and stale state did not interrupt playback. |
| 2026-07-27 | 5 | working tree | Headless Chromium performance, reduced-motion, keyboard, and renderer comparison | Pass | Both tracks passed documented payload, decode, first-frame, seek, adaptive 30/20/15 fps, clock-drift, accessibility, and three-time fidelity checks. |
| 2026-07-27 | 5 | working tree | Admin, JavaScript, renderer, contract/site, verify/deploy/schema lanes | Pass | 123 Admin, 19 JavaScript, 149 renderer-engine, 29 contract/site, and 30 verification/deployment/schema tests passed. |
| 2026-07-27 | 5 | working tree | Private response/source/public-build scans and no-write check | Pass | No absolute private path reached responses or source fixtures; build `20260727T230457144918Z-site` contained no Live Preview surface; navigation left 28 video jobs unchanged. |
| 2026-07-27 | 5 | working tree | `scripts/mrp --json inspect`, `scripts/mrp --json validate`, public build, lint, syntax, whitespace, and `graphify update .` | Pass | Repository inspection and validation passed with zero errors/warnings; public build produced 1,485 files; final source and graph checks passed. |

| 2026-07-27 | Review | working tree | `.venv/bin/pytest -q tests/video` | Pass | 306 video tests passed, including five new cases for whole-second durations, measured-duration refusal, the build memo, revalidation, and dropped text subpaths. |
| 2026-07-27 | Review | working tree | `node --test tests/video/admin/js` | Pass | 19 JavaScript tests passed against the 28-column state contract. |

## Post-release review — 2026-07-27

A code review of the working tree found six issues. All are fixed in this same
tree; the milestone evidence above records the state before these changes.

| Issue | Resolution |
|---|---|
| The whole-second release-YAML `duration` could veto aligned timing and refuse a preview outright, using a hardcoded 0.05 s tolerance. | Timing is now checked only against a measured preflight duration, using the project's own `audio.duration_tolerance`. Without preflight the longest candidate is used and the check is skipped. |
| The response `ETag` was never honoured, so every tab refocus rebuilt and resent the whole document to compare four revision fields. | The route answers a matching `If-None-Match` with `304` and no body, and builds are memoized on a stat-and-hash fingerprint of every source the builder reads. |
| Eight of 36 state columns were never read by the browser. | `section_progress`, `rotation_direction`, `trace_speed`, and the five `visibility_*` columns are dropped. The state block is 22% smaller; a 4,097-sample document loses about 175,000 bytes. |
| The playback loop overwrote the scrubber thumb every redraw, so it could not be dragged during playback. | Indicator updates skip the thumb while a pointer or key owns it. |
| Text contour phases were derived by counting `M`/`m` commands, which keeps subpaths the renderer drops and shifts every later contour onto the wrong phase. | Phases now come from `generate_text_points`, the renderer's own expansion, with the command count kept only as a fallback. |
| Smaller items: `normalizeRange` could silently yield a `NaN` range; `mrpClearPreviewGeometryCache` was dead; the isolated-interpreter timeout allowed 15 s for process start, a librosa import, and a full timeline sample; `_encode` could raise a bare `ValueError`; a failed Scene Preview load lost the scene's saved background; a scene-jump tooltip named a time it did not seek to. | All fixed. The worker timeout is now `WORKER_TIMEOUT_SECONDS = 90`. |

The payload row in the Release Gates report predates the column reduction and
is retained as the measurement taken at release time.

## Blockers and open decisions

| Date opened | Milestone | Blocker or decision | Owner/next action | Status |
|---|---|---|---|---|
| 2026-07-27 | 0 | Select payload encoding and state sampling rate from measurements. | Completed two-track spike; selected 20 Hz base64 little-endian `Float32`. | Closed 2026-07-27 |

Close a row by changing its status and adding a dated decision-log row. Do not
delete the historical blocker.

## Progress-update procedure

Whenever a milestone changes:

1. Update its status and the summary table.
2. Check only work that is actually present.
3. Record branch/commit/PR, exact test commands, manual routes, measurements,
   and privacy evidence.
4. Add validation-log rows, including failures that materially affect the plan.
5. Update Current next action.
6. Append decision or blocker rows when scope or architecture changes.
7. Update the implementation plan only when the durable design changes.
