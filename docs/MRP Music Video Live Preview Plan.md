# MRP Music Video Live Preview Plan

Status: implemented and release-gated, 2026-07-27

Companion documents:

- [MRP Music Video Designer Plan](<MRP Music Video Designer Plan.md>) defines
  the production renderer, editor, render, approval, and publication workflow.
- [MRP Music Video Live Preview Milestones](<MRP Music Video Live Preview Milestones.md>)
  records implementation status, completion evidence, and the next action.
- [MRP Music Video Live Preview Spike](<MRP Music Video Live Preview Spike.md>)
  records the measured version-1 contract and performance decision.
- [MRP Music Video Live Preview Release Gates](<MRP Music Video Live Preview Release Gates.md>)
  records the final performance, fidelity, privacy, and accessibility evidence.
- [MRP Music Video Track Workflow](<MRP Music Video Track Workflow.md>) defines
  the current track-project, analysis, timing, casting, render, and approval
  contracts.

## Purpose

Add a private, non-rendering live preview system to MRP Admin. It must let an
operator hear the track master while viewing the saved music-video project
across the complete song, and it must make the existing Scene Preview respond
to the same audio and choreography state.

This is not another MP4 preview path. The browser draws an editorial preview
onto a canvas directly from safe project data and sampled renderer state. It
starts without encoding frames, supports seeking, and shares one clock and
drawing engine between scene and full-track playback.

The production Python renderer remains authoritative. A rendered frame or
verified draft remains the final check for exact pixels, font rasterization,
encoding, and publication.

## Terminology

- **Actor Preview** is the square, actor-local identity canvas. It previews
  component topology and behavior without track placement or a musical
  timeline.
- **Scene Preview** is the 16:9 storyboard in Scene Casting. It previews the
  selected scene, including live unsaved direction edits.
- **Full-track Preview** is the new 16:9 canvas and transport that play the
  saved project from the start of the master through its end.
- **Live Preview** means Scene Preview and Full-track Preview together, backed
  by the shared browser engine described here.
- **Rendered preview** means a Python-rendered frame, contact sheet, draft MP4,
  or full MP4. Those artifacts are outside this plan except as comparison
  evidence.

## Goals

1. Use the track master as the single playback clock for every timed preview.
2. Make Scene Preview and Full-track Preview share the same audio-reactive
   visual-state contract and canvas implementation.
3. Preserve fast live editing in Scene Casting, including unsaved placement,
   visibility, wardrobe, energy, and trace changes.
4. Follow the saved project across every scene, gap, transition, and lyric cue
   without starting a background render.
5. Keep Python authoritative for audio analysis, choreography, section
   resolution, and renderer contracts.
6. Keep all production paths, source media, stems, and cache locations out of
   browser payloads.
7. State the fidelity boundary honestly: editor-trustworthy motion and timing,
   but not a promise of pixel identity with OpenCV and FFmpeg output.

## Non-goals

- Do not replace frame, draft, full-render, verification, approval, or
  publication jobs.
- Do not advance `music_video.status`, create an artifact record, or write
  project source merely because a live preview was played.
- Do not add React, Vite, a browser audio-analysis library, WebSockets, or a
  second production renderer.
- Do not expose master paths, stem paths, runtime manifests, analysis-cache
  paths, or generated workspace paths.
- Do not make the public Astro site load project or analysis data.
- Do not simulate opening or closing cards in the first live-preview release.
  Full-track playback initially covers master-audio time `0..duration`.
- Do not turn Full-track Preview into a second editing surface. Scene Casting
  remains the owner of per-scene direction.
- Do not require exact browser/OpenCV font or antialiasing parity.

## Existing baseline

The live-preview work builds on working components rather than beginning from
an empty surface.

| Area | Current capability | Remaining gap |
|---|---|---|
| Private audio | The admin-only `/video/audio` route serves the selected track master. | Full-track transport and shared clock semantics. |
| Actor canvas | All supported curve families, actor components, trace playback, color flow, and component dragging render in `spiro-preview.js`. | Keep actor-local behavior separate from track time. |
| Scene canvas | The selected compiled scene draws at 960×540, accepts live direction edits, and can loop its master-audio range. | It uses scene-relative trace time and does not consume canonical audio/choreography state. |
| Scene compilation | Python resolves actor casts and legacy compositions and serializes a safe selected-scene storyboard. | Serialize all saved scenes plus the renderer fields needed by Live Preview. |
| Timing | Aligned sections, gaps, lyric cues, and master duration already exist. | Deliver a safe indexed timeline to the browser. |
| Analysis | Python caches normalized master and semantic-role features. | Read a valid cache into a browser-safe sampled state without exposing cache details. |
| Choreography | Python resolves section styles, transitions, gaps, trace time, rotation time, and visibility. | Sample this canonical state for browser interpolation. |
| Renderer checks | Rendered frames, contact sheets, and drafts remain available. | Add deliberate live-versus-render comparison evidence. |

## Settled product decisions

### One shared engine

Scene Preview and Full-track Preview use one browser engine with the public
conceptual API:

```text
loadPreview(document)
renderAt(masterTimeSeconds, liveOverrides?)
play(audioElement, optionalRange?)
pause()
seek(masterTimeSeconds)
destroy()
```

`renderAt()` accepts absolute master time. It must work while playing, paused,
or scrubbing. A scene loop changes only the allowed playback range; it does not
reset musical time to zero.

Actor Preview may continue to use the lower-level geometry helpers without
loading a track preview document.

### Python owns canonical state

Python continues to own:

- project and aligned-lyrics validation;
- exact-scene, section-type, automatic, and legacy composition resolution;
- audio feature extraction and semantic-role sampling;
- section selection, transition planning, gap behavior, and choreography;
- integrated trace and rotation time;
- deterministic phase offsets and palette/mapping preset resolution;
- source-revision and staleness checks.

The browser owns:

- transport interaction and the animation loop;
- interpolation between adjacent sampled states;
- applying the renderer's small layer-mapping formula to the current shapes;
- drawing curves, trails, ghosts, heads, colors, lyrics, and background;
- overlaying unsaved fields from the selected Scene Casting form;
- accessibility and operator-facing availability/staleness messages.

This hybrid boundary avoids reimplementing audio analysis or choreography in
JavaScript while still allowing unsaved scene edits to react immediately.

### Absolute master time

The `<audio>` element's `currentTime` is the only playback clock.
`requestAnimationFrame` decides when to redraw but never advances musical time
independently while audio playback is active.

- Full-track Preview renders `audio.currentTime`.
- Scene Preview renders the same absolute time and loops within
  `[scene.start, scene.end)`.
- Seeking while paused calls `renderAt(audio.currentTime)` immediately.
- A gap is resolved by the sampled choreography state, not by a separate
  JavaScript guess.
- A scene transition retains the canonical integrated trace and rotation time,
  so shapes do not jump or restart at a boundary.

### Saved and unsaved state

Full-track Preview represents the current saved, validated project revision.
It never mixes unsaved fields from an arbitrary editor form into other scenes.

Scene Preview starts from that same saved preview document, then overlays the
selected form's unsaved actor assignment and direction fields. The UI must
label this state clearly when local edits differ from the saved project.

Saving a project invalidates the loaded preview document. HTMX navigation or a
full page response must reload the new source revision before claiming that the
preview is current.

### Availability and fallback

Live Preview has two explicit modes:

1. **Audio-reactive** — project, aligned timing, master metadata, and a current
   analysis cache are available.
2. **Geometry-only** — project and timing are available but analysis is
   missing or stale. Audio may still play, but the UI states that visual audio
   response is unavailable.

Opening a preview page must never run expensive audio analysis synchronously.
When analysis is missing or stale, the operator is directed to the existing
analysis job. Geometry-only mode remains usable.

### Authority and status

Live Preview is ephemeral and admin-only:

- it creates no image or video artifact;
- it does not advance `draft`, `timed`, `cast`, or `previewed` status;
- it does not satisfy approval preflight;
- it is never treated as verification evidence by publication code;
- it always offers a rendered-frame action when exact confirmation matters.

## Target architecture

```text
saved project.yaml + lyrics.aligned.yaml
                  |
                  | validate and resolve every scene
                  v
       admin live-preview adapter
                  |
      +-----------+------------------+
      |                              |
      v                              v
safe scene/lyric document    current cached analysis
                                     |
                                     | sample existing Python functions
                                     v
                         AudioVisualState + ChoreographyState
      |                              |
      +---------------+--------------+
                      v
       private fingerprinted preview document
                      |
                      v
       shared browser Live Preview engine
          renderAt(absolute master time)
             |                     |
             v                     v
      Scene Preview          Full-track Preview
      selected range         complete master transport
      + live form overlay    + scene/lyric indicators
```

The adapter belongs in the admin layer because it translates private MRP
project state into a browser contract. The renderer package must not import
admin code or know about routes or templates.

The base Admin interpreter intentionally does not require NumPy, librosa, or
the renderer dependency set. When those imports are unavailable, the data
adapter performs the same bounded, read-only build through the existing
isolated video interpreter selected by `mrp.admin.video_jobs.worker_python`.
This is a synchronous document build, not a persistent job: it creates no job
row, analysis, artifact, approval, content, or status write. A missing or
invalid video environment returns a structured availability error.

Recommended implementation surfaces:

```text
mrp/admin/video_live_preview.py
mrp/admin/routes/video.py
mrp/admin/static/spiro-preview.js
mrp/admin/static/video-live-preview.js
mrp/admin/templates/releases/workspace/video_casting.html
mrp/admin/templates/releases/workspace/video_live_preview.html
tests/video/admin/test_video_live_preview.py
tests/video/admin/js/video-live-preview.test.mjs
```

File names may change as implementation lands, but the admin/renderer
dependency direction and the version-1 document contract may not change
without a recorded superseding decision.

## Private preview-document contract

The data route should return a versioned document rather than embedding a large
payload in the casting page. Keep it distinct from the Full-track Preview page:

```text
GET /releases/{release}/tracks/{track}/video/live-preview
GET /releases/{release}/tracks/{track}/video/live-preview/data
```

The first route renders the eventual Full-track Preview page; the second returns
the private preview document used by both that page and Scene Preview. Milestone
0 froze the version-1 encoding and state schema. The logical document contains:

```yaml
format: mrp-music-video-live-preview
version: 1
source_revision:
  project_sha256: ...
  lyrics_sha256: ...
  analysis_key: ...          # identifier only, never a path
  renderer_contract: ...
mode: audio-reactive         # or geometry-only
duration_seconds: 204.8
state_rate_hz: 20
state_encoding: base64-float32-le
state_width: 28
state_sample_count: 4097
video:
  width: 1920
  height: 1080
  background: "#101014"
  canvas_margin: 0.08
compositions:
  actor:type:verse:
    traces: [...]
sections:
  - id: verse-1
    type: verse
    label: Verse 1
    start: 12.4
    end: 35.7
    composition_key: actor:type:verse
    previous_section_id: intro
lyrics:
  - text: ...
    start: 13.2
    end: 16.8
state_schema: [...]
state_samples_base64: ...
```

Compositions are deduplicated by stable composition key. Sections reference
the composition table rather than repeating trace geometry. The safe document
may also contain allowlisted actor, palette, mapping, and text configuration
needed to apply live Scene Preview overrides.

Each safe trace descriptor includes the renderer fields required for drawing
and live mapping:

- stable trace/component identity and deterministic phase fraction;
- geometry family and active geometry fields;
- semantic role and audio drivers;
- anchor, scale, rotation speed, depth, opacity, line width, and blend mode;
- base color, color-lock, hue shift, and optional color-flow settings;
- cycles per second, trail fraction, ghost count/spacing, and head radius.

The sampled state contains only normalized renderer values:

- master, drums, bass, vocals, and instruments energy/accent;
- master spectral centroid;
- section identity and previous-section identity;
- transition progress, from which composition weights are derived;
- layer fraction, scale, motion, and color intensity;
- onset, palette, lyric, spatial, trail, beat, and intensity values;
- integrated trace time and rotation time.

The state carries only columns the browser engine reads. Section progress,
rotation direction, and trace speed are never consumed, and per-role visibility
is unreachable because every caller supplies an explicit visibility override,
exactly as `render_frame` passes `composition_weight`. Carrying them cost about
a fifth of the response body for nothing.

No sample contains PCM audio, source filenames, stem identifiers, absolute
paths, runtime manifest paths, or cache paths.

### Version-1 state encoding

The state timeline is one interleaved little-endian `Float32` block encoded as
base64 inside the JSON envelope:

- fixed rate: 20 Hz;
- sample count: `ceil(duration_seconds * 20) + 1`;
- sample time: `min(duration_seconds, sample_index / 20)`;
- width: 28 values;
- no repeated time column;
- numeric values interpolate linearly;
- current and previous section indices use step lookup.

The fixed column order is:

| Indices | State |
|---|---|
| 0–1 | Current and previous section indices |
| 2–12 | Master/role energy and accent, then master spectral centroid |
| 13–27 | Transition progress, layer fraction, scale, motion, color intensity, onset response, palette shift, lyrics opacity, spatial spread, anchor drift, trail length, beat gain, intensity gain, trace time, and rotation time |

The response includes the exact `state_schema` names as a decoder assertion.
Version 1 does not use `Float16` or other lossy quantization: the spike measured
about 0.062 maximum absolute error, enough to shift integrated trace or rotation
time visibly. Geometry-only mode omits the state block and carries a structured
reason.

The complete measurements and field names are recorded in
[MRP Music Video Live Preview Spike](<MRP Music Video Live Preview Spike.md>).

## Browser engine responsibilities

### State lookup

- Binary-search or directly index the two samples around master time.
- Interpolate numeric state; treat section identities as step values.
- Use the canonical previous/current section IDs and transition weight when
  two compositions are visible.
- Cache generated geometry by stable trace identity and geometry signature.
- Reuse paths across frames; do not regenerate 900–1200 points on every
  animation tick.

### Layer mapping

Port only the pure `map_layer_state` behavior and its preset constants. Do not
port feature extraction or choreography.

The JavaScript mapping function must have fixture-based parity tests against
Python at representative times and boundary values. Any future Python mapping
change must either update the shared preview contract or deliberately record a
known live-preview difference.

### Drawing

The shared engine must support:

- every current geometry family, including path and text components;
- deterministic phase, trails, ghosts, trace heads, and trace speed;
- canonical scale, rotation, anchor drift, opacity, line width, hue, palette,
  beat pulse, and background response;
- previous/current composition blending during transitions;
- background-before-foreground ordering;
- normal and screen blending where Canvas 2D provides an equivalent;
- lyric cue selection and fades;
- a clearly documented approximation for renderer-only raster details.

Scene-only editing affordances such as drag handles, labels, guides, and
selection halos are overlays. They do not belong in Full-track Preview.

### Transport

Full-track Preview provides:

- native play/pause plus a synchronized scrubber;
- current and total time;
- active scene and lyric indicators;
- click/keyboard seeking;
- reset and jump-to-scene actions;
- deterministic redraw on `loadedmetadata`, `seeked`, pause, and ended;
- animation driven by `requestAnimationFrame` while playing.

Scene Preview uses the same transport adapter with a bounded range. Reaching
the end seeks to the scene start while retaining absolute-time rendering.

## Fidelity contract

| Feature | Live Preview target | Authority |
|---|---|---|
| Scene resolution and cast | Same saved resolution order and compiled traces | Python project contracts |
| Geometry and placement | Same parameters; Canvas rasterization may differ | Rendered frame |
| Absolute trace phase | Same deterministic phase and integrated trace time | Python sampled state |
| Audio energy/accent response | Same normalized state and mapping formulas | Python analysis/mapping |
| Scene styles and gaps | Same sampled choreography | Python choreography |
| Scene transitions | Same timing, curve, and composition weights | Python choreography |
| Color, palette, hue flow | Same inputs; small color/raster differences allowed | Rendered frame |
| Opacity, line width, beat pulse | Same mapped values; antialiasing may differ | Rendered frame |
| Lyrics | Same cue timing/text/fade; browser font metrics may differ | Rendered frame |
| Blend modes | Equivalent Canvas operation where available | Rendered frame |
| Opening/closing cards | Not in the first release | Draft/full render |
| Exact pixels and encoded timing | Explicitly not promised | Verified render |

The UI copy should say **Live preview** and retain **Render frame to confirm**.
It must not use “exact render” or “pixel-perfect.”

## Performance budgets

Milestone 0 measured budgets on both `A Distant Memory` and the more complex
`A Good Day to Be` project.

Accepted version-1 budgets:

- no analysis computation during a preview-document request;
- preview-document generation from current caches in at most 1.5 seconds on
  the development machine;
- no more than 1.25 MiB uncompressed for a four-minute track, with a hard
  2 MiB refusal/fallback threshold;
- browser parse plus state decode at or below 15 ms p95;
- first geometry-only frame within 500 ms of document availability;
- first audio-reactive frame within 2 seconds of page navigation on the local
  admin server;
- 30 canvas frames per second at 960×540 for typical scenes;
- adaptive reduction to 20 frames per second for expensive scenes, with a
  15-frames-per-second hard floor and no audio-clock drift;
- seeking redraw within 100 ms after browser `seeked`;
- geometry is cached and payload/state arrays are bounded by track duration.

State sampling rate and canvas redraw rate are independent. The fixed 20 Hz
state timeline is interpolated during canvas redraws. Increasing payload
frequency requires a versioned, measured contract change.

## Privacy and safety

- The route resolves the release and track exactly as existing private video
  routes do.
- Only an existing project below the approved project root may be read.
- The response serializer uses explicit allowlists; it does not dump the full
  project or runtime manifest.
- Private-path scans cover the response body, rendered template, tests, logs,
  and any saved fixture.
- The preview document is never copied to `site/public`, an Astro build, a
  rendered artifact directory, or a publication receipt.
- Response errors name logical inputs such as “analysis is stale,” not local
  filenames.
- A missing or stale analysis cache produces geometry-only mode rather than an
  implicit analysis run.
- Live Preview does not write release YAML, project YAML, aligned lyrics,
  artifacts, job records, or approval records.

## Staleness and invalidation

The response carries a source revision derived from safe hashes and contract
versions. The browser displays:

- **Current** when project, lyrics, and analysis match the loaded document;
- **Unsaved scene edits** when Scene Casting overlays local form changes;
- **Geometry only** when analysis is unavailable;
- **Stale** when the server reports a newer saved source revision.

Project, timing, actor, scene-cast, and analysis changes invalidate the prior
document. A Full-track Preview may continue playing an already loaded document,
but it must retain the stale label and offer reload. It must not silently swap
timelines mid-play.

## Accessibility and operator controls

- Canvas has an accessible label and a textual current-scene/current-lyric
  companion.
- Play/pause, reset, seek, and scene-jump controls are keyboard operable.
- Time and status updates avoid noisy live-region announcements on every
  animation frame.
- Reduced-motion preference may lower redraw frequency but does not alter audio
  time or scene selection.
- Errors and fallbacks are visible text, not only console messages.
- Audio remains under an explicit user gesture; the page does not autoplay.

## Test strategy

### Python contract tests

Add an isolated admin lane covering:

- safe resolution of every timed scene, including actor and legacy projects;
- exact-scene, section-type, automatic, and fallback composition order;
- sampled audio and choreography values at representative times;
- gaps, transitions, first/last scene boundaries, and duration clamping;
- current, missing, and stale analysis behavior;
- source-revision changes after project, timing, or analysis changes;
- response-size limits and deterministic serialization;
- absence of master, stem, project, processed, and cache paths;
- route-level authorization/not-found/error behavior;
- no writes and no `music_video.status` change.

### Browser engine tests

Keep the calculation core DOM-independent and test it with Node's built-in test
runner rather than adding a JavaScript framework. Cover:

- state interpolation and section step changes;
- absolute-time seek, pause, reset, scene looping, and track end;
- mapping parity fixtures produced by Python;
- previous/current composition blending;
- geometry cache invalidation;
- geometry-only fallback;
- live Scene Casting overrides without mutation of the base document.

The existing renderer lane remains independent:

```bash
.venv/bin/pytest tests/video/engine
```

### Cross-surface and manual checks

- Compare Live Preview with Python-rendered frames at selected times before,
  during, and after transitions.
- Exercise both real tracks named in the performance section.
- Confirm scene loop and full-track playback show the same pixels at the same
  absolute master time, excluding scene editing overlays.
- Scrub while paused and while playing.
- Save a scene, verify staleness, reload, and confirm the new revision.
- Run the video admin lane, renderer lane, repository validation, private-path
  scans, and Graphify refresh.

## Implementation milestones

Detailed status and evidence live in the companion milestone tracker.

### Milestone 0: Contract and performance spike

Status: completed 2026-07-27.

Measure representative projects, compare payload encodings and sampling rates,
and freeze the version-1 logical contract and budgets.

Exit: one encoding and sampling approach is recorded with payload, generation,
parse, and canvas-frame measurements for both real tracks.

Evidence:
[MRP Music Video Live Preview Spike](<MRP Music Video Live Preview Spike.md>).

### Milestone 1: Shared absolute-time browser engine

Status: completed 2026-07-27.

Extract the reusable drawing and transport behavior from the inline Scene
Casting script. Add `renderAt(masterTime)` and preserve current Actor and Scene
Preview behavior without adding audio reactivity yet.

Exit: the current scene storyboard uses the shared engine, paused seeking works,
and existing editor interactions remain intact.

Evidence:
[MRP Music Video Live Preview Milestones](<MRP Music Video Live Preview Milestones.md>)
records the focused browser, Admin, renderer, and real-page checks.

### Milestone 2: Private preview document

Status: completed 2026-07-27.

Add the admin adapter, versioned route, all-scene serialization, safe sampled
state, revision metadata, fallbacks, limits, and privacy tests.

Exit: a current analyzed track returns a bounded audio-reactive document, and a
track without current analysis returns a bounded geometry-only document without
running analysis.

### Milestone 3: Audio-reactive Scene Preview

Status: completed 2026-07-27.

Drive the selected scene with absolute master time and the sampled preview
state. Preserve live unsaved direction and actor changes, scene looping, drag
handles, and rendered-frame confirmation.

Exit: the scene preview reacts to the same musical time as sampled Python state,
and parity checks pass at representative times.

### Milestone 4: Full-track Preview

Status: completed 2026-07-27.

Add the dedicated page, navigation, complete transport, scene/gap/transition
playback, lyrics, scene indicators, staleness handling, and geometry-only
fallback.

Exit: an operator can play or scrub the complete saved project without
rendering an MP4, and Scene Preview matches it at the same master time.

### Milestone 5: Fidelity, performance, and release gates

Status: completed 2026-07-27.

Close high-value parity gaps, enforce budgets, validate both real tracks,
document intentional differences, and complete repository/privacy checks.

Exit: performance and fidelity evidence is recorded, no private path is exposed,
and the UI consistently distinguishes Live Preview from rendered authority.

## Pull-request and integration strategy

Each milestone should land as one bounded change when practical. Milestones 1
and 2 may share a branch but should remain separately reviewable because the
browser refactor and private data contract have different risks.

Every milestone must:

- leave the current editor and render workflow usable;
- preserve the isolated `tests/video/engine` lane;
- add only the smallest new dependency surface, preferably none;
- update the milestone tracker with exact test and manual evidence;
- run `graphify update .` after code changes;
- avoid generated output in Git.

## Risks and mitigations

### Python/JavaScript mapping drift

Risk: a renderer formula changes without a matching browser change.

Mitigation: fixture-based parity at named times, an explicit preview contract
version, and documented intentional differences.

### Payload growth

Risk: JSON state for a long track becomes slow to transfer and parse.

Mitigation: measure first, separate state rate from redraw rate, use a compact
schema-described representation only when needed, and enforce a hard response
limit with geometry-only fallback.

### Browser canvas cost

Risk: large text/path actors and many traces cannot sustain the target frame
rate.

Mitigation: geometry caching, stable scene caches, a 960×540 ceiling, adaptive
redraw frequency, and performance evidence from the complex real project.

### Implicit expensive work

Risk: navigating to Live Preview unexpectedly recomputes analysis.

Mitigation: cache reads only; missing/stale analysis has an explicit fallback
and existing job action.

### Confusing saved and unsaved state

Risk: an operator assumes Full-track Preview includes uncommitted scene fields.

Mitigation: saved-revision badges, an unsaved overlay label in Scene Preview,
and no full-track editing surface.

### Overstated fidelity

Risk: canvas output is mistaken for approval evidence.

Mitigation: consistent “Live preview” naming, a fidelity table, rendered-frame
confirmation actions, and no status/artifact side effects.

## Global completion criteria

- Scene and Full-track Preview share one absolute-time browser engine.
- Both show the same saved scene at the same master time.
- Scene Preview can overlay live unsaved edits without mutating saved state.
- Full-track Preview plays and scrubs every scene, gap, transition, and lyric
  cue across the master duration.
- Current analysis produces audio-reactive motion; missing analysis produces an
  explicit geometry-only fallback.
- Python remains canonical for analysis, choreography, composition resolution,
  and revision state.
- Browser payloads contain no private production paths or media.
- Live Preview creates no artifact, status transition, approval evidence, or
  public output.
- Performance budgets pass on both representative real projects.
- Known browser/render differences are documented and rendered frames remain
  the authority.
