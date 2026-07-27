# MRP Music Video Live Preview Contract and Performance Spike

Status: completed, 2026-07-27

Companion documents:

- [MRP Music Video Live Preview Plan](<MRP Music Video Live Preview Plan.md>)
  defines the durable architecture and implementation sequence.
- [MRP Music Video Live Preview Milestones](<MRP Music Video Live Preview Milestones.md>)
  records milestone status and completion evidence.

## Conclusion

Milestone 0 supports proceeding with the shared browser Live Preview engine.
Version 1 uses a JSON envelope with one interleaved, little-endian `Float32`
state block encoded as base64. Canonical state is sampled at a fixed 20 Hz;
the browser interpolates numeric values at its independent canvas redraw rate.

This was the smallest tested representation that preserved canonical trace and
rotation timing while remaining comfortably inside the revised transfer and
decode budgets:

- 818–880 KB for the two current tracks at 20 Hz;
- 2.3–2.5 ms median and at most 7.0 ms p95 JSON parse plus base64 decode in the
  measured headless Chromium runs;
- 286–783 ms median state generation in the spike, depending on project and
  whether a real analysis cache was available.

The existing canvas can draw most representative scenes above 30 frames per
second in headless software rendering. The two bridge scenes measured about
23–24 frames per second. Version 1 therefore targets 30 fps for typical scenes
and adaptively reduces expensive scenes to 20 fps, then 15 fps if necessary,
without changing the audio clock.

## Scope and method

The spike loaded the current track project and aligned lyrics, compiled safe
browser-facing actor/composition data, and sampled the existing Python
choreography functions. It compared:

- ordinary JSON objects;
- JSON row arrays;
- interleaved `Float32` values in a base64 JSON field;
- a `Float16` size/error estimate;
- 15 Hz and 20 Hz state sampling;
- parse/decode cost in the repository's cached headless Chromium;
- the current `mrpDrawShapes` canvas path at 960×540.

The canvas fixture warmed each scene for 20 draws, then measured five repeats
of 120 frames and retained the median repeat. A one-pixel readback forced
canvas work to complete. This is a conservative software-canvas benchmark, not
a claim about a specific operator's GPU or an end-to-end page load.

No route or browser engine exists yet, so end-to-end navigation and first-frame
latency remain release-gate measurements. Milestone 0 established that
serialization and browser decode are not the first-frame bottleneck and
retains the 500 ms first-geometry-frame budget from document availability.

All generated fixtures and scripts lived below `/tmp`. They are exploratory,
noncanonical, and intentionally untracked.

## Representative project inventory

| Measurement | A Distant Memory | A Good Day to Be |
|---|---:|---:|
| Master duration | 205.0 s | 212.0 s |
| Project document | 24,172 bytes | 45,167 bytes |
| Aligned lyrics document | 4,890 bytes | 6,044 bytes |
| Sections | 8 | 11 |
| Aligned lyric lines | 29 | 34 |
| Actors | 14 | 10 |
| Actor components | 15 | 21 |
| Unique compiled compositions | 4 | 8 |
| Unique compiled traces | 10 | 13 |
| Maximum traces in one composition | 4 | 3 |
| Maximum compiled geometry samples | 1,200 | 1,200 |
| Maximum path-data characters | 0 | 6,031 |
| Safe document without sampled state | 29,418 bytes | 65,309 bytes |
| Gzipped safe document | 3,762 bytes | 10,495 bytes |
| Existing analysis cache | 1,554,307 bytes | Missing |
| Existing analysis frames | 8,817 | 0 |
| Median analysis-cache load | 8.37 ms | Not applicable |

Compositions were deduplicated by stable composition key. Sections referenced
that table rather than repeating trace geometry for every occurrence.

`A Good Day to Be` had no current analysis cache. The spike did not create one.
For fixed-width encoding size and choreography-cost comparisons only, it used
zero normalized audio values. Its geometry counts, payload size, browser
decode, and canvas results are valid; its sample-generation result does not
claim audio-reactive preview availability. A real request must return
geometry-only mode in this condition.

## Sampling and server-side generation

The sample count is:

```text
ceil(duration_seconds * state_rate_hz) + 1
```

Sample `i` represents `min(duration_seconds, i / state_rate_hz)`. Time is
derived from the index and is not repeated in every row.

| Track | Rate | Samples | Float32 document | Gzipped document | Median generation |
|---|---:|---:|---:|---:|---:|
| A Distant Memory | 15 Hz | 3,076 | 620,738 bytes | 236,047 bytes | 598.77 ms |
| A Distant Memory | 20 Hz | 4,101 | 817,538 bytes | 312,412 bytes | 783.25 ms |
| A Good Day to Be | 15 Hz | 3,181 | 676,789 bytes | 62,546 bytes | 214.70 ms |
| A Good Day to Be | 20 Hz | 4,241 | 880,309 bytes | 78,653 bytes | 285.98 ms |

The unusually small gzip values for `A Good Day to Be` reflect the
zero-normalized-audio benchmark data and must not be used as a production
compression forecast. The uncompressed envelope remains the response-size
guardrail.

At 20 Hz the raw state blocks were 590,544 and 610,704 bytes. Converting the
already generated arrays to base64 JSON took 1.05 and 1.11 ms median,
respectively. Both tracks remain under the 1.5-second generation target.

## Encoding comparison

### Twenty-hertz document size

| Encoding | A Distant Memory | A Good Day to Be |
|---|---:|---:|
| Object JSON | 4,694,633 bytes | 4,133,722 bytes |
| Row-array JSON | 2,193,650 bytes | 1,547,339 bytes |
| Base64 little-endian Float32 | 817,538 bytes | 880,309 bytes |

The Float32 envelope is 2.5–5.7 times smaller than object JSON across the two
projects and is also simpler to index at runtime than thousands of objects.

### Headless Chromium parse and decode

| Track | Encoding | Median | p95 |
|---|---|---:|---:|
| A Distant Memory | Object JSON | 6.7 ms | 11.1 ms |
| A Distant Memory | Row-array JSON | 3.6 ms | 3.8 ms |
| A Distant Memory | Float32 envelope | 2.3 ms | 6.7 ms |
| A Good Day to Be | Object JSON | 6.2 ms | 7.9 ms |
| A Good Day to Be | Row-array JSON | 2.1 ms | 2.6 ms |
| A Good Day to Be | Float32 envelope | 2.5 ms | 7.0 ms |

These runs included `JSON.parse`, base64 decoding, byte copying, and creation of
the `Float32Array`. Version 1 accepts a 15 ms p95 decode budget.

### Quantization decision

The estimated `Float16` block halves raw state bytes, but its maximum absolute
error was 0.0622–0.0625. That error is material for integrated `trace_time` and
`rotation_time`: it can move visible trace heads or rotations. Version 1
therefore rejects `Float16` and other lossy quantization.

## Canvas baseline

The following are median batch costs from the existing canvas implementation,
not scheduled `requestAnimationFrame` rates:

| Track | Representative scene | Milliseconds/frame | Equivalent fps |
|---|---|---:|---:|
| A Distant Memory | Bridge, worst | 44.27 | 22.59 |
| A Distant Memory | Chorus | 16.20 | 61.72 |
| A Distant Memory | Adlib | 8.92 | 112.07 |
| A Distant Memory | Verse | 7.18 | 139.23 |
| A Good Day to Be | Bridge, worst | 42.43 | 23.57 |
| A Good Day to Be | Instrumental | 23.02 | 43.45 |
| A Good Day to Be | Chorus | 16.38 | 61.04 |
| A Good Day to Be | Final chorus | 7.54 | 132.57 |

A prototype geometry/hue cache left both worst bridge scenes at about 42 ms
per frame. Geometry caching remains required, but it is not sufficient by
itself; the expensive path is dominated by color-flow/path drawing. Milestone
1 must keep the audio clock authoritative and add adaptive redraw scheduling:

1. target 30 fps for typical scenes;
2. reduce to 20 fps when recent draw cost cannot sustain 30;
3. reduce to a 15 fps floor when necessary;
4. never slow, offset, or synthesize the audio clock to match drawing.

## Frozen version-1 state contract

The JSON envelope includes:

```yaml
format: mrp-music-video-live-preview
version: 1
mode: audio-reactive
duration_seconds: 205.0
state_rate_hz: 20
state_encoding: base64-float32-le
state_width: 36
state_sample_count: 4101
state_schema: [...]
state_samples_base64: ...
compositions:
  actors:type:verse:
    traces: [...]
sections:
  - id: verse-1
    composition_key: actors:type:verse
```

The 36 values in each interleaved sample have this fixed order:

| Indices | Fields | Lookup behavior |
|---|---|---|
| 0–1 | `section_index`, `previous_section_index` | Step values |
| 2–12 | Master/role energy and accent, then master spectral centroid | Interpolated |
| 13–30 | Canonical choreography values | Interpolated |
| 31–35 | Master, drums, bass, vocals, and instruments visibility | Interpolated |

The exact schema is:

```text
section_index
previous_section_index
master_energy
master_accent
drums_energy
drums_accent
bass_energy
bass_accent
vocals_energy
vocals_accent
instruments_energy
instruments_accent
spectral_centroid
section_progress
transition_progress
layer_fraction
scale
motion
color_intensity
onset_response
rotation_direction
palette_shift
lyrics_opacity
spatial_spread
anchor_drift
trace_speed
trail_length
beat_gain
intensity_gain
trace_time
rotation_time
visibility_master
visibility_drums
visibility_bass
visibility_vocals
visibility_instruments
```

Numeric fields interpolate linearly between adjacent samples. Section indices
are step values. The canonical previous/current section pair and transition
progress determine which two composition entries are visible.

Geometry-only mode carries the safe video, composition, section, actor,
palette, mapping, text, lyric, and revision data but omits the sampled state
block. It includes a structured reason that directs the operator to the
existing analysis action.

## Revised budgets

- Existing analysis only; a preview request must never compute analysis.
- At most 1.5 seconds to build the document on the development machine.
- Target at most 1.25 MiB uncompressed for a four-minute track.
- Hard response ceiling of 2 MiB; exceedance returns a structured fallback or
  refusal rather than an unbounded document.
- At most 15 ms p95 for JSON parse plus state decode.
- First geometry-only frame within 500 ms of document availability.
- First audio-reactive frame within 2 seconds of page navigation.
- 30 fps typical redraw, adaptive 20 fps for expensive scenes, and 15 fps hard
  floor without audio-clock drift.
- Redraw within 100 ms after browser `seeked`.

The first-frame, navigation, seeking, and scheduled-frame budgets require the
implemented route and engine and remain Milestone 5 release gates.

## Privacy and side-effect evidence

Generated documents were scanned for `/home/`, `/mnt/`, `master_path`,
`cache_dir`, and common audio filename suffixes. No match was found. The
documents contained no PCM audio, source media path, stem filename, analysis
cache path, or generated workspace path.

The `A Good Day to Be` analysis cache remained absent after the spike. No
project, content, artifact, status, or public-site data was written. The only
spike output was disposable data below `/tmp`.

## Implementation consequences

- Milestone 1 can build one absolute-time engine without waiting on a second
  payload experiment.
- Milestone 2 must implement the explicit allowlist and the exact version-1
  state schema above.
- The route must deduplicate compositions and enforce both sample-count and
  uncompressed-response bounds.
- Browser decoding should happen once per document load, yielding one
  `Float32Array`.
- Adaptive drawing belongs in the shared engine; state sampling remains fixed
  at 20 Hz regardless of draw rate.
- Renderer parity tests must compare the pure layer mapping and representative
  sampled states. A rendered frame remains the exact-pixel authority.
