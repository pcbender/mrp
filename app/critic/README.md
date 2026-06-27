# MRP Critic

AI music critic pipeline for Maricopa Records. Ingests an audio master and
produces a short, human-sounding review plus a machine-readable QA verdict.

## Setup

```bash
cd app/critic
pip install -e .
```

Requires `ffmpeg` on the system path:
```bash
sudo apt install ffmpeg
```

## Phase 1 usage (MVP)

```bash
# Run the full pipeline on one track
critic review <audio_path> --track-slug <slug> --artist-slug <slug>

# Run individual workers
python -m critic.ingest  <audio_path> [--track-id <id>]
python -m critic.dsp     <audio_path> [--track-id <id>]
```

## Output

Records are written to `out/<track_id>.json`. Each is a `TrackFinding`
— a single shared JSON document that workers fill slice by slice.

## Verdict ladder

| rank | label      | register                                    |
|------|------------|---------------------------------------------|
| 5    | standout   | "play this first," "career-best"            |
| 4    | highlight  | "a highlight," "lands cleanly"              |
| 3    | dependable | "does its job and does it well"             |
| 2    | soft_floor | "a grower," "for the faithful"              |

Floor is rank 2. `review.status` is `pending` until explicitly approved.
