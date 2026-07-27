# MRP Music Video Live Preview Release Gates

Status: complete Milestone 5 release evidence, 2026-07-27

Companion documents:

- [MRP Music Video Live Preview Plan](<MRP Music Video Live Preview Plan.md>)
  defines the architecture, budgets, and authority boundary.
- [MRP Music Video Live Preview Milestones](<MRP Music Video Live Preview Milestones.md>)
  is the durable completion ledger.
- [MRP Music Video Live Preview Spike](<MRP Music Video Live Preview Spike.md>)
  records the version-1 contract decision and baseline measurements.

## Result

The version-1 browser Live Preview stays within its payload, decode,
first-frame, seek, and redraw budgets on both representative tracks. The
browser follows the audio element's absolute time and reduces drawing work
without slowing or synthesizing that clock.

The production renderer remains authoritative for exact pixels. Side-by-side
checks show matching saved compositions, placement, trace phase, transition
membership, lyric cue, and musical time, with expected Canvas/OpenCV
rasterization and blending differences.

## Performance measurements

Measurements used the local Admin server and headless Chromium at 960×540.
Payload bytes are the uncompressed JSON response body. Navigation time starts
at the browser navigation origin; after-data time starts at the private data
resource's `responseEnd`.

| Measurement | A Distant Memory | A Good Day to Be | Budget |
|---|---:|---:|---:|
| Preview mode | audio-reactive | geometry-only | explicit mode |
| Response body | 811,232 bytes | 57,448 bytes | 1.25 MiB target; 2 MiB hard limit |
| JSON parse + state decode median | 3.9 ms | 0.1 ms | — |
| JSON parse + state decode p95 | 4.0 ms | 0.2 ms | 15 ms |
| First frame after data | 12.2 ms | 304.3 ms | 500 ms geometry frame |
| First frame after navigation | 1,509.1 ms | 851.7 ms | 2,000 ms audio-reactive page |
| Paused seek + redraw | 0.5 ms | 0.6 ms | 100 ms |
| Typical-scene scheduled redraw | 29.18 fps | 29.59 fps | 30 fps target |
| Typical-scene target retained | 30 fps | 30 fps | 30 fps |
| Expensive-scene scheduled redraw | 18.77 fps | 14.77 fps | adaptive 20/15 fps |
| Expensive-scene target selected | 20 fps | 15 fps | 15 fps floor |
| Engine/audio difference after expensive playback | 8.12 ms | 43.34 ms | below one selected redraw interval |

These numbers were measured against the original 36-column state contract. The
post-release review dropped the eight columns the browser never read, so the
audio-reactive response body is now about 22% smaller than the figure above;
the row is kept as the measurement taken at release time. Every other budget is
unaffected.

The measured actual redraw values include browser scheduling and CDP
observation overhead, so a nominal 30 fps target appears just under 30.
Audio time remains authoritative: the engine/audio difference stayed below
one redraw interval even when the complex geometry-only bridge selected the
15 fps floor.

Reduced-motion emulation selected a fixed 15 fps redraw target. Keyboard-only
Space play/pause advanced the real master from 0 to 0.80s, Arrow Right moved
the scrubber and engine together to 0.81s, and Enter on the final scene button
jumped to the correct `chorus-2` sampled state.

## Fidelity comparisons

The isolated renderer produced 960×540 draft PNGs in `/tmp`; the browser
canvas was captured at the renderer's exact frame time. These files are
temporary comparison evidence, not project or publication artifacts.

| Time | State checked | Result |
|---:|---|---|
| 20.000s | Long pre-verse gap and transition | The canonical sampled state selected Verse during its configured gap takeover and blended six previous/current traces. Renderer and Canvas showed the same dominant orbit, fading prior traces, placement, and phase. |
| 42.267s | Stable Chorus with lyric | Both showed the same three saved traces, anchors, scale relationships, trace heads, palette roles, and `I've been waiting` cue. |
| 50.000s | Expensive Bridge | Both showed the same single oversized bridge flower, rotation/phase, head position, and `Your face is a distant memory` cue. |

At 42.25s, Scene Preview and Full-track Preview returned the same three trace
IDs and identical mapped anchor, scale, opacity, line width, color, rotation,
integrated trace time, trail, and depth values after excluding the Scene
Casting guides and labels.

### Intentional renderer differences

- Canvas uses browser curve stroking, floating-point placement, line joins,
  and antialiasing; the renderer uses OpenCV integer rasterization.
- Canvas adds its existing editor glow/shadow. This is especially visible on
  bright or screen-blended bridge traces.
- Canvas `screen` compositing and shadow participation differ from the
  renderer's NumPy/OpenCV blend formula. The bridge is visibly brighter in
  Live Preview even though the mapped color, opacity, and line width inputs
  match.
- Canvas color-flow segments use the existing browser hue helper; the renderer
  evaluates per-point flow values in its own HSV pipeline. Hue motion and role
  remain useful for editing, but exact color is a rendered-frame decision.
- Live lyrics use the browser system font because font paths are deliberately
  excluded from the private document. Cue text, time, fade, color, safe width,
  and vertical position match; glyph metrics, weight, stroke, and
  antialiasing may differ.
- Opening and closing cards remain outside version 1. Full-track Preview covers
  master-audio time only.

These are bounded raster/display differences. Python remains canonical for
scene resolution, choreography, transition curves and gaps, semantic audio
state, layer mapping inputs, integrated trace/rotation time, deterministic
phase, and lyric timing.

## Privacy and lifecycle gates

- Both real data responses contain no tested absolute path, `master_path`,
  `cache_dir`, common source-audio filename, PCM, or runtime-manifest field.
- The full-track page performs GET requests only. Repeated navigation left the
  video-job row count unchanged and did not change release, project, aligned
  lyric, analysis, artifact, approval, or publication state.
- `A Good Day to Be` remained geometry-only and no analysis cache was created
  by navigation.
- A simulated changed source revision displayed
  `Stale loaded state · Reload`, retained object identity for the loaded
  document, and did not interrupt playback.
- Missing or stale analysis, oversized audio state, missing project/timing,
  structured route errors, and malformed browser documents have explicit
  covered fallbacks or refusals.
- Live Preview data and scripts remain Admin-only and are absent from public
  Astro output. Public build `20260727T230457144918Z-site` contains no Live
  Preview route, browser bundle, document marker, or private video-project
  path.

## Authority statement

Live Preview is the fast editorial check for saved scene choice, motion,
musical response, transitions, lyric timing, and whole-track flow. It does not
advance `music_video.status`, create approval evidence, or promise exact
pixels. Use **Render frame to confirm** or a verified draft/full render for
font rasterization, precise compositing, encoded timing, approval, and
publication.
