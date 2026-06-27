# Running the critic on one track

## Setup

```bash
cd app/critic
python3 -m venv .venv
.venv/bin/pip install -e .
sudo apt install ffmpeg      # if not already installed
```

## Single-track review

```bash
.venv/bin/critic review /mnt/c/Masters/Joni.wav \
  --release-slug winds-of-change \
  --track-slug   joni \
  --target       blurb
```

- `--release-slug` matches `content/releases/<slug>.yaml`
- `--track-slug` matches either the release slug (for singles) or a track
  entry within the release's `tracks:` array
- Lyrics and artist persona are pulled automatically from the catalog
- Output JSON is written to `out/<artist>--<track>.json`

## Format options

```bash
# Full liner-note paragraph
.venv/bin/critic review /mnt/c/Masters/Joni.wav \
  --release-slug winds-of-change \
  --track-slug   joni \
  --target       liner

# Pin to a specific verdict tier (2-5)
.venv/bin/critic review ... --target-tier 4

# Use sonnet instead of haiku
.venv/bin/critic review ... --model default
```

## Individual workers

Each stage can be run and inspected on its own:

```bash
# Ingest only
.venv/bin/python -m critic.ingest /mnt/c/Masters/Joni.wav

# DSP only
.venv/bin/python -m critic.dsp /mnt/c/Masters/Joni.wav

# Synthesize from a saved finding JSON
.venv/bin/python -m critic.synthesize out/pcbender--joni.json \
  --artist PCBender --target liner
```
