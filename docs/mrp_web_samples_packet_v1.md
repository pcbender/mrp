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
- **Stereo, 128k AAC in `.m4a`** — best quality/byte with universal `<audio>` support. MP3 is the hedge if any downstream tool dislikes AAC.
- **Loudness:** normalize the *excerpt* to **-14 LUFS**, -1 dBTP true-peak ceiling.
- **Fades:** ~0.3s in, ~1.5s out (no hard edges).
- **Manual override** per track for the handful the auto-picker gets wrong.
- **Idempotent cache:** skip existing samples unless `--force`; a revised master regenerates only its one sample.
- ~0.5 MB/track → ~150 MB for 300. Trivial.

---

## WP-SAMPLE · Hook-centered web sample generator

- **Deliverable:** a `prime-samples` command + selection helper + manifest.
- **Files:** `critic/samples/select.py`, `critic/samples/cli.py`, `samples/overrides.json` (hand-edited), `samples/<track_id>.m4a`, `samples/manifest.json`.

### Selection logic (fallback ladder, in `select.py`)

For each track, choose the 30s window:

1. **Manual override** present in `samples/overrides.json` (`{track_id: {start_s, duration_s}}`) → use it.
2. Else **first chorus / hook** if `sections` are semantically labeled → start there.
3. Else **highest-energy 30s window** (peak RMS over `sections`) → start there.
4. Else **fallback offset** at ~25% into the track (never the cold open) → start there.
   Always clamp so the window doesn't run past the end; if the track is shorter than the
   target length, use the whole track. Record which rung fired in the manifest's `selection` field.

### Encode behavior (`cli.py`)

Cut from `source.path`, apply fades, normalize to -14 LUFS, encode stereo 128k AAC:

```
ffmpeg -ss <start_s> -t <len> -i "<master>" \
  -af "afade=t=in:st=0:d=0.3, afade=t=out:st=<len-1.5>:d=1.5, \
       loudnorm=I=-14:TP=-1:LRA=11" \
  -ac 2 -c:a aac -b:a 128k "samples/<track_id>.m4a"
```

(Per-excerpt `loudnorm` rather than track-level gain, because a chorus is louder than the
track average — normalizing the actual excerpt is what makes the catalog consistent.)

### CLI surface

```
critic prime-samples [--all | --track <id>] [--length 30] [--format m4a|mp3] \
                     [--target-lufs -14] [--force]
```

- `--all` walks every `out/<track_id>.json`; cached samples are skipped unless `--force`.
- Missing/unreachable master → skip, log `status: needs_source` in the manifest, continue (don't crash the batch).

### Manifest (the handoff to Weaver) — `samples/manifest.json`

```json
{
  "track_id": "stab--cargo-cult",
  "sample_path": "samples/stab--cargo-cult.m4a",
  "start_s": 96.4,
  "duration_s": 30.0,
  "selection": "first_chorus | peak_energy | fallback_offset | manual_override",
  "target_lufs": -14.0,
  "measured_lufs_out": -14.1,
  "format": "aac_128k_m4a",
  "status": "ok | needs_source | short_track"
}
```

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

- **Cut from the master, never from the model proxy.** The proxy is mono 96k for Gemini only.
- This packet **does not** touch the critic phases or their records (read-only on `out/<track_id>.json`).
- Idempotent: don't regenerate an existing sample unless `--force` or the master changed.
- Don't add any web-serving code — produce files + manifest; Weaver consumes them.
- Stop at each GATE. Summarize, don't proceed.
