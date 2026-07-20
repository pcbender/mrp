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

## Privacy and dependency boundary

The track workflow lives entirely in `mrp.video`. It does not import MRP Admin,
Astro, or publishing code. Normal MRP commands remain usable without video
dependencies, and all generated runtime paths, hashes, logs, previews, renders,
and renderer manifests stay below the ignored processed tree.
