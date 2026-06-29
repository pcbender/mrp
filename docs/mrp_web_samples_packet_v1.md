# Maricopa Records — Web Sample Generator

## Standalone Work Packet (independent of critic Phases 3–4)

> **What this is:** a catalog-wide tool that cuts a 30-second, hook-centered,
> loudness-matched audio sample of each released track for the website to serve.
> **What it is not:** part of the critic pipeline. It reuses the same ingest machinery
> and the DSP data already in the per-track records, but adds no dependency to the
> critic phases and threads through none of them.
> 
> **Division of labor:** `mrp` **produces** samples + a manifest; **Weaver serves** them.
> This packet drops files and a manifest — it adds no web code.
> 
> **Depends on:** Phases 1–2 complete (each `out/<track_id>.json` carries `source.path`,
> `hard_facts.sections`, and `hard_facts.lufs`).

---

## Why it's not just "first 30 seconds"

Two fields the critic already computed make the sample smart:

- **`hard_facts.sections`** → start the excerpt at the hook/chorus, not the cold intro.
- **`hard_facts.lufs`** → normalize every sample to a consistent web loudness so a visitor
  clicking down the catalog never gets whisper-then-blast.

Net result: hook-centered and level-matched samples for free, which beats every "30s from
the top" player on a competitor's page.

---

## Locked decisions

- **Length:** 30s default (iTunes/Spotify convention; gives the hook room). Configurable.
- **Cut from the master**, not the model proxy. The 96k mono proxy is for Gemini and would sound thin to a human. Read `source.path` from the record (local master or LANDR re-download).
- **Stereo, 128k MP3** — universal `<audio>` support, no container ambiguity.
- **Loudness:** normalize the *excerpt* to **-14 LUFS**, -1 dBTP true-peak ceiling.
- **Fades:** ~0.3s in, ~1.5s out (no hard edges).
- **Manual override** per track for the handful the auto-picker gets wrong.
- **Idempotent cache:** skip existing samples unless `--force`; a revised master regenerates only its one sample.
- ~0.5 MB/track → ~150 MB for 300. Trivial.

---

## WP-SAMPLE · Hook-centered web sample generator

- **Deliverable:** a `prime-samples` command + selection helper + manifest + `preview_audio` write-back.
- **Files:** `app/sampler/select.py`, `app/sampler/cli.py`, `app/sampler/overrides.json` (hand-edited), `site/public/samples/<track_id>.mp3`, `app/sampler/manifest.json`.

### Selection logic (fallback ladder, in `select.py`)

For each track, choose the 30s window:

1. **Manual override** present in `samples/overrides.json` (`{track_id: {start_s, duration_s}}`) → use it.
2. Else **first chorus / hook** if `sections` are semantically labeled → start there.
3. Else **highest-energy 30s window** (peak RMS over `sections`) → start there.
4. Else **fallback offset** at ~25% into the track (never the cold open) → start there.
   Always clamp so the window doesn't run past the end; if the track is shorter than the
   target length, use the whole track. Record which rung fired in the manifest's `selection` field.

### Encode behavior (`cli.py`)

Cut from `source.path`, apply fades, normalize to -14 LUFS using two-pass loudnorm, encode stereo 128k MP3:

```
# Pass 1 — measure the excerpt
ffmpeg -ss <start_s> -t <len> -i "<master>" \
  -af "afade=t=in:st=0:d=0.3, afade=t=out:st=<len-1.5>:d=1.5, \
       loudnorm=I=-14:TP=-1:LRA=11:print_format=json" \
  -f null - 2>&1  # parse measured_I, measured_LRA, measured_TP, measured_thresh, offset

# Pass 2 — encode with measured values
ffmpeg -ss <start_s> -t <len> -i "<master>" \
  -af "afade=t=in:st=0:d=0.3, afade=t=out:st=<len-1.5>:d=1.5, \
       loudnorm=I=-14:TP=-1:LRA=11:measured_I=<I>:measured_LRA=<LRA>:measured_TP=<TP>:measured_thresh=<thresh>:offset=<offset>:linear=true" \
  -ac 2 -c:a libmp3lame -b:a 128k "site/public/samples/<track_id>.mp3"
```

Two-pass on the excerpt (not the full track) — a chorus is louder than the track average,
so normalizing the actual excerpt is what makes the catalog consistent.

### CLI surface

```
critic prime-samples [--all | --track <id>] [--length 30] [--target-lufs -14] [--force]
```

- `--all` walks every `out/<track_id>.json`; cached samples are skipped unless `--force`.
- Missing/unreachable master → skip, log `status: needs_source` in the manifest, continue (don't crash the batch).

### Manifest (the handoff to Weaver) — `samples/manifest.json`

```json
{
  "track_id": "stab--cargo-cult",
  "sample_path": "site/public/samples/stab--cargo-cult.mp3",
  "preview_audio": "/samples/stab--cargo-cult.mp3",
  "start_s": 96.4,
  "duration_s": 30.0,
  "selection": "first_chorus | peak_energy | fallback_offset | manual_override",
  "target_lufs": -14.0,
  "measured_lufs_out": -14.1,
  "format": "mp3_128k",
  "status": "ok | needs_source | short_track"
}
```

`preview_audio` is the site-relative URL written back into `content/releases/{slug}.yaml`
under `song.preview_audio` or `tracks[n].preview_audio`. The Astro build picks it up at
build time; no web code changes are needed.

The `selection` field is your review lever: anything that fired `fallback_offset` is a
candidate for a manual override entry.

### Execution (staged — two checkpoints in one packet)

1. **Build + prove:** implement the tool, run on **5–8 tracks** spanning genres/tempos.
   - **GATE:** stop. Present those samples + their manifest rows (especially the `selection` column) so the auto-picker can be ear-checked before committing the catalog.
2. **Batch:** after approval, run `--all` over the ~300, then surface the manifest summary — counts by `selection` and any `needs_source`/`short_track` rows.
   - **GATE:** **end of packet.** Present the manifest summary and the list of tracks worth a manual override.

### Acceptance

- Samples start on the hook (not the intro) on the majority of the proof set.
- Loudness is consistent across samples by ear (no whisper-to-blast).
- Masters are never modified; `out/<track_id>.json` is never modified.
- Manifest is complete and lists selection method + status per track.

---

## Notes for the agent

- **Cut from the master, never from the model proxy.** The proxy is mono 96k for Gemini only. Masters live at `/mnt/c/Masters`.
- The critic metadata (sections, lufs, source path) is **descriptive, not prescriptive**. The sampler (`select.py`) owns the decision about which 30s window to use; the critic makes no recommendation.
- This packet is **read-only on `out/<track_id>.json`**. It writes only to `site/public/samples/` and `content/releases/*.yaml` (`preview_audio` field).
- Idempotent: don't regenerate an existing sample unless `--force` or the master changed.
- Don't add any web-serving code — files in `site/public/samples/` are served automatically by the Astro build.
- Stop at each GATE. Summarize, don't proceed.
