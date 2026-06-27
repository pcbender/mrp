# Maricopa Records — AI Music Critic
## Build Plan v1 (for Claude Code / WSL2)

> **How to run this:** Feed Claude Code **one work packet (WP) at a time**, in order.
> Each packet ends with a **GATE** — the agent must stop, summarize what it built,
> and wait for your review before continuing. Do not paste the whole doc and say "go."
> The phase headers are for you; the packets are for the agent.

---

## System overview (give the agent this context first)

A pipeline that ingests a song and produces a short, human-sounding review plus a
machine-readable QA verdict. Each stage is a **worker** that fills its slice of one
shared JSON record (the *track finding*). The final stage is a Claude-written synthesis.

Three signal sources feed the writer: the **lyrics** (text), the **artist persona**
(text), and the **audio**, which is decomposed into hard DSP facts, optional trained
tags, and an audio-LLM impression. The writer never invents hard facts — it is handed
them.

**Canonical record (the contract between all stages):**

```json
{
  "track_id": "stab--cargo-cult",
  "source":   { "type": "local_master|landr_redownload", "path": "...", "proxy": "..." },
  "lyrics":   "…",
  "persona":  "…",
  "hard_facts": {
    "bpm": 92, "key": "A", "mode": "minor", "time_signature": "4/4",
    "duration_s": 218.4, "lufs": -9.2, "sections": [],
    "confidence": { "bpm": 0.91, "key": 0.74 }
  },
  "tags":       { "genre": [], "mood": [], "instruments": [] },
  "impression": { "text": "…", "model": "gemini-2.5-pro" },
  "review": {
    "target": "blurb|liner",
    "review_text": "…",
    "verdict_tier": { "rank": 2, "label": "soft_floor" },
    "anchors_used": ["key change at chorus", "lyric: 'I built the runway…'"]
  }
}
```

**Verdict ladder (ordinal; floor is rank 2, never below):**

| rank | label        | register                                              |
|------|--------------|-------------------------------------------------------|
| 5    | standout     | "play this first," "career-best"                      |
| 4    | highlight    | "a highlight," "lands cleanly," "holds the room"      |
| 3    | dependable   | "does its job and does it well," "a dependable cut"   |
| 2    | soft_floor   | "a grower," "for the faithful," "worthy of a listen"  |

The prose is always warm; the **rank** is the honest QA signal you sort on internally.

**Locked decisions (do not let the agent relitigate):**
- Language: Python 3.11+, in WSL2 Ubuntu, project + working files on native ext4 (not `/mnt/c`).
- Phase 1 has **no GPU and no audio-LLM** dependency.
- Synthesis writer: Anthropic SDK, model configurable, default `claude-sonnet-4-6` (use `claude-opus-4-8` for hero tracks).
- Impression layer (Phase 2): Google `google-genai` SDK, default `gemini-2.5-pro`.
- Masters stay archival on Windows; the pipeline works off a downsampled array + a small Opus proxy.
- Streaming rips are out of scope. Lost-original fallback = re-download from LANDR/distributor.

---

## PHASE 1 — Ingest + DSP + text-driven review (MVP, no GPU, no audio-LLM)

Goal: a runnable CLI that turns one local WAV + lyrics + persona into a reviewed JSON record.

### WP-1 · Scaffold + ingest stage
- **Deliverable:** project skeleton and an `ingest` worker.
- **Files:** `pyproject.toml` (or `requirements.txt`), `critic/config.py`, `critic/ingest.py`, `critic/record.py` (dataclasses/pydantic for the canonical record), `README.md`.
- **Behavior of `ingest`:**
  - Accept a path that may be `/mnt/c/...` **or** a native path; if it's `/mnt/c`, copy into `~/audio/masters/` via `rsync -a` and use the local copy.
  - Produce two derivatives: (a) a downsampled mono array for DSP via `librosa.load(path, sr=22050, mono=True)`; (b) a compressed proxy via `ffmpeg -i <in> -c:a libopus -b:a 96k <proxy.opus>`.
  - Refuse unreadable/corrupt input with a clear error; populate `source` in the record.
- **Acceptance:** `python -m critic.ingest <path>` on a real master prints the resolved local path, proxy path, sample rate, and duration. ffmpeg presence is checked with a friendly message if missing.
- **GATE:** stop, show the record JSON and the proxy file size, wait for review.

### WP-2 · DSP feature extraction
- **Deliverable:** `dsp` worker that fills `hard_facts`.
- **Files:** `critic/dsp.py`.
- **Behavior:** extract bpm, key+mode, time signature (best-effort), duration, integrated LUFS, and a coarse section map. Attach a `confidence` sub-object (at minimum bpm + key). Use `librosa`; LUFS via `pyloudnorm`.
- **Acceptance:** on 2–3 of your tracks the bpm/key are sane (spot-check against what you know). Output validates against the `hard_facts` schema.
- **GATE:** stop, show `hard_facts` for the sample tracks, wait for review.

### WP-3 · Synthesis writer (the critic voice)
- **Deliverable:** `synthesize` worker that fills `review`.
- **Files:** `critic/synthesize.py`, `critic/prompts/critic_system.md`.
- **Behavior:** call the Anthropic SDK with lyrics + persona + hard_facts. Enforce the
  warm-critic rules: never dismissive, floor at rank 2, specific praise / gentle hedges,
  anchor in a real fact or quoted line, avoid AI-critic clichés, land on exactly one
  ladder rung. Return `{review_text, verdict_tier, anchors_used}`. `target` (`blurb` vs
  `liner`) is a parameter. The model picks the tier from the findings unless a
  `target_tier` is passed; a hard floor prevents dropping below rank 2.
- **Acceptance:** running on a strong track and a deliberately weaker one yields visibly
  different rungs, both publishable, with at least one real anchor each.
- **GATE:** stop, show both reviews + their tiers side by side, wait for review.

### WP-4 · End-to-end CLI + sample run
- **Deliverable:** one command that chains ingest → dsp → synthesize for a single track.
- **Files:** `critic/cli.py`, `examples/run_one.md`.
- **Behavior:** `critic review <audio> --lyrics <file> --persona <file> [--target blurb|liner]` writes the full record to `out/<track_id>.json` and prints the review.
- **Acceptance:** clean run on one real master end to end; JSON validates.
- **GATE:** **end of Phase 1.** Stop, summarize the file tree and how to run it, wait before Phase 2.

---

## PHASE 2 — Audio-LLM impression + tags + batch QA

Goal: the critic now actually "hears" the track, and you can run a whole catalog and sort by verdict.

### WP-5 · Gemini impression worker
- **Deliverable:** `impression` worker that fills `impression` from the Opus proxy.
- **Files:** `critic/impression.py`.
- **Behavior:** send `proxy.opus` (base64) to `gemini-2.5-pro` with a prompt that asks
  only for texture/feel/production — explicitly **not** bpm/key (DSP owns those). Store
  the text + model name. Degrade gracefully (skip, don't crash) if the API key is absent.
- **Acceptance:** impression text reads like someone heard the song and does not contradict `hard_facts`.
- **GATE:** stop, show one impression next to that track's hard_facts, wait for review.

### WP-6 · Trained taggers
- **Deliverable:** `tags` worker (genre / mood / instruments).
- **Files:** `critic/tags.py`.
- **Behavior:** use Essentia pretrained MTG models (or CLAP zero-shot if Essentia install is painful in WSL) to fill `tags`. Keep optional — pipeline runs without it.
- **Acceptance:** tags are plausible on the sample set.
- **GATE:** stop, show tags for 2–3 tracks, wait for review.

### WP-7 · Upgrade synthesis to use impression + tags
- **Deliverable:** writer now consumes all five inputs.
- **Files:** edit `critic/synthesize.py`, `critic/prompts/critic_system.md`.
- **Behavior:** fold impression + tags into the prompt; impression sharpens the *texture*
  language, hard_facts still own the *numbers*. Re-verify the no-clichés / floor rules hold.
- **Acceptance:** reviews are richer than Phase 1 on the same tracks, still on-ladder.
- **GATE:** stop, show before/after on one track, wait for review.

### WP-8 · Batch runner + tier-sorted QA report
- **Deliverable:** run a folder of tracks; emit a QA table.
- **Files:** `critic/batch.py`, `out/qa_report.{md,csv}`.
- **Behavior:** process every track in a directory, write each record, and produce a
  report sorted by `verdict_tier.rank` ascending so the quietly-soft-floored tracks surface
  at the top. Public review text in one column, internal rank in another.
- **Acceptance:** a catalog run produces a sortable report; the lowest-ranked tracks are the ones you'd agree are weakest.
- **GATE:** **end of Phase 2.** Stop, show the QA report, wait before Phase 3.

---

## PHASE 3 — Hardening, persona config, optional local model

Goal: make it durable, governable, and Cantor-shaped. Pick the packets you actually want; this phase is optional.

### WP-9 · Contracts, provenance, confidence handling
- **Deliverable:** every worker emits validated output with provenance + confidence; the writer hedges when confidence is low (e.g. key detection shaky).
- **Files:** `critic/schema.py`, validation wired into each worker.
- **Acceptance:** a low-confidence key produces softer factual language, not a confident wrong claim.
- **GATE:** stop, show a low-confidence case, wait for review.

### WP-10 · Critic persona + tone knobs
- **Deliverable:** the reviewer itself becomes a configurable persona (house critic), with tone parameters (warmth, brevity, formality).
- **Files:** `critic/personas/*.md`, config plumbing.
- **Acceptance:** swapping persona visibly changes voice without breaking the ladder/floor.
- **GATE:** stop, show two personas on one track, wait for review.

### WP-11 · Optional local impression model
- **Deliverable:** a local audio-LLM behind the same `impression` interface (Qwen-Omni Light/Flash or quantized Qwen2.5-Omni-7B), selectable by config.
- **Files:** `critic/impression_local.py`.
- **Notes:** must fit the 16GB ceiling (quantized / Light variant). Gemini stays the default; this is for offline / zero-marginal-cost runs.
- **Acceptance:** local path produces a usable impression and the rest of the pipeline is unchanged.
- **GATE:** stop, compare local vs Gemini impression on one track, wait for review.

### WP-12 · Eval + human-approval gate
- **Deliverable:** a small calibration harness and a governed approval step on the text artifact (matches your SOUL.md policy).
- **Files:** `critic/eval.py`, `out/calibration.md`.
- **Behavior:** a handful of reference tracks with expected rungs; flag drift. The published review requires explicit approval; the JSON record is automated.
- **Acceptance:** rung assignments are stable across reruns; nothing publishes without approval.
- **GATE:** **end of Phase 3.**

---

## Notes for the agent
- Keep each worker independently runnable (`python -m critic.<worker> ...`) — easier to review and re-run one stage.
- Never read large WAVs repeatedly from `/mnt/c`; copy to ext4 once in WP-1.
- The proxy is for the audio-LLM only; DSP reads the downsampled array, not the proxy.
- Treat the canonical record as the single source of truth; workers fill slices, they don't reshape it.
- Stop at every GATE. Summarize, don't proceed.
