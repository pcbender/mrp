# Maricopa Records — AI Music Critic
## Build Plan — Phases 3 & 4 (revised, v3 — supersedes v2)

> **Status:** Phases 1–2 are **complete**. The per-song pipeline emits one
> `out/<track_id>.json` finding record per song, each with a standalone `verdict_tier.rank`.
>
> **What changed from v2:** Phase 3 is now a **three-pass** album algorithm. A new
> **Pass 3** re-tightens each track review *in album context*, instead of smuggling
> context-reranking into the album writer. Work packets renumbered; Phase 4 hardening
> shifts to WP-14–17.
>
> **How to run this:** one work packet at a time, in order. Each ends with a **GATE** —
> stop, summarize, wait for review. Phase headers are for you; packets are for the agent.

---

## The three-pass flow (the spine of Phase 3)

```
Pass 1  TRACK REVIEW (standalone)      ← already built (Phases 1–2)
          per-song record + verdict_tier.rank, neighbor-free. The honest QA signal.
                    │
                    ▼
Pass 2  ALBUM REVIEW                    ← consumes Pass 1 records + tracklist ORDER + cohesion
          album_features (arc, peaks/valleys from existing ranks), cohesion verdict,
          album-level review + sum_vs_parts + persona_delivery.
                    │
                    ▼
Pass 3  TIGHTEN TRACK REVIEWS IN CONTEXT
          re-pass each track knowing its sequence position, neighbors, and the album arc.
          Produces a contextual review per track. Does NOT overwrite Pass 1.
```

**Two non-negotiables:**

1. **The album layer never re-listens.** Passes 2 and 3 read `out/<track_id>.json` plus
   tracklist order plus a light text/tag cohesion pass. Ingest / DSP / impression are
   done. If the agent proposes re-extracting audio, stop it.

2. **Pass 1 is immutable.** The standalone `review` and `rank` stay frozen on the track
   record as the honest "is this a good song" signal. Pass 3 output is **additive** and
   lives on the **album** record (the same song on a compilation earns a different
   context), never on the track record.

---

## What only exists at the album level

- **Sequencing** — opener's job, mid-album sag, peak placement, whether the closer earns it.
- **Arc** — trajectory across runtime, plotted from per-track facts (BPM curve, key/mood progression, runtime).
- **Cohesion vs. variety** — statement vs. shuffle playlist: tag overlap, palette consistency, lyrical threads.
- **Internal ranking** — peaks/valleys read directly from existing `verdict_tier.rank`.
- **Sum vs. parts** — is the album *more* than its tracks (sequencing/cohesion elevate it) or *less*.
- **Persona statement (Maricopa)** — does the collection deliver on what the artist is supposed to be.
- **Context shift (Pass 3)** — a track's role *in sequence* (e.g. a standalone rank-2 cut that is the perfect breather at position 6).

---

## Canonical album record (the Phase 3 contract)

```json
{
  "album_id": "stab--runway-state",
  "artist": "STAB",
  "persona": "…",
  "tracklist": ["stab--cargo-cult", "stab--brownout", "stab--tin-ear"],  // ORDER is data
  "track_records": ["out/stab--cargo-cult.json", "…"],                    // reuse, don't recompute

  "album_features": {
    "total_runtime_s": 2480,
    "bpm_curve": [92, 78, 84],
    "key_progression": ["Am", "Em", "Dm"],
    "mood_progression": ["…"],
    "rank_distribution": { "5": 1, "4": 0, "3": 1, "2": 1 },
    "peak_track": "stab--cargo-cult",
    "valley_tracks": ["stab--tin-ear"]
  },

  "cohesion": {
    "palette_consistency": 0.0,
    "theme_threads": ["…"],
    "verdict": "cohesive_statement | varied | shuffle_playlist"
  },

  "review": {                                  // Pass 2 — album-level
    "target": "album_blurb | album_long",
    "review_text": "…",
    "verdict_tier": { "rank": 4, "label": "strong" },
    "sum_vs_parts": "greater | equal | lesser",
    "persona_delivery": "on_character | expands | off_character",
    "anchors_used": ["opener sets the tone", "track 3 is the peak", "closer earns it"]
  },

  "track_reviews_in_context": [                // Pass 3 — additive, per track
    {
      "track_id": "stab--tin-ear",
      "position": 6,
      "standalone_rank": 2,                    // copied from Pass 1, never changed
      "context_rank": 3,                       // optional: how it plays here
      "context_note": "elevated as the back-half breather; lands because of what precedes it",
      "review_text": "…"
    }
  ]
}
```

**Album verdict ladder (warm floor at rank 2):**

| rank | label       | register                                                        |
|------|-------------|-----------------------------------------------------------------|
| 5    | essential   | "a career statement," "front to back"                           |
| 4    | strong      | "a confident, cohesive record," "it holds together"             |
| 3    | solid       | "does what it sets out to do," "a dependable collection"        |
| 2    | soft_floor  | "not their strongest collection, but worth your time"           |

`sum_vs_parts` and `persona_delivery` are separate fields, not the rank. A `lesser` album
with high-ranked tracks is a sequencing/cohesion flag — surface it in QA.

---

## PHASE 3 — Album Critic (three passes)

### WP-9 · Album record + tracklist ingest + album-features  *(Pass 2 prep)*
- **Deliverable:** album record model and an `album_features` worker.
- **Files:** `critic/album/record.py`, `critic/album/features.py`.
- **Behavior:** accept an **ordered** tracklist + artist/persona; load the referenced
  per-track records; compute runtime, BPM/key/mood progressions, `rank_distribution`,
  `peak_track`, `valley_tracks` — all from existing fields. Fail clearly on a missing
  track record; never trigger song extraction.
- **Acceptance:** curves and peak/valley map match a by-hand read; no song-stage worker runs.
- **GATE:** stop, show `album_features` for one album, wait for review.

### WP-10 · Cross-track cohesion + theme pass
- **Deliverable:** `cohesion` worker.
- **Files:** `critic/album/cohesion.py`.
- **Behavior:** palette consistency from per-track `tags`, recurring lyrical threads across
  the album's lyrics set, cohesion verdict (`cohesive_statement | varied | shuffle_playlist`).
  Text + tags only.
- **Acceptance:** defensible on 1–2 real albums; an eclectic one does not read as cohesive.
- **GATE:** stop, show `cohesion` for one album, wait for review.

### WP-11 · Album synthesis writer  *(Pass 2 — the album review)*
- **Deliverable:** `album_synthesize` worker that fills `review`.
- **Files:** `critic/album/synthesize.py`, `critic/prompts/album_critic_system.md`.
- **Behavior:** album-level voice — sequencing, arc, names real standout/grower tracks from
  `peak_track`/`valley_tracks`/`rank_distribution`, lands an album-ladder rung with the warm
  floor, sets `sum_vs_parts` and `persona_delivery`. Same anti-cliché / specific-praise rules.
  **Scope guard:** this writer does **not** rewrite or rerank individual track reviews — that
  is Pass 3's job.
- **Acceptance:** a cohesive vs. a loose album yield different rungs *and* different `sum_vs_parts`; the review names actual tracks by their rank role.
- **GATE:** stop, show two album reviews with their tiers/axes, wait for review.

### WP-12 · Tighten track reviews in context  *(Pass 3 — new)*
- **Deliverable:** `recontextualize` worker that fills `track_reviews_in_context`.
- **Files:** `critic/album/recontextualize.py`, `critic/prompts/track_context_system.md`.
- **Behavior:** for each track, re-pass the review **given** its `position`, its neighbors,
  the album arc, and the Pass 2 album verdict. Copy `standalone_rank` from Pass 1 unchanged;
  optionally set a `context_rank` and a one-line `context_note` explaining the shift; rewrite
  `review_text` to read in sequence (the breather, the palate-cleanser, the build into the
  peak). Same warm floor. **Must not** mutate `out/<track_id>.json`.
- **Acceptance:** at least one track's contextual review meaningfully differs from its
  standalone review for a defensible sequencing reason; Pass 1 records are byte-identical after the run.
- **GATE:** stop, show one track's standalone vs. contextual review side by side, wait for review.

### WP-13 · Album CLI + report  *(orchestrates Pass 2 → Pass 3)*
- **Deliverable:** one command that runs the album passes end to end.
- **Files:** `critic/album/cli.py`, `out/<album_id>.json`, `out/album_qa.md`.
- **Behavior:** `critic album <tracklist> --artist <name> --persona <file> [--target album_blurb|album_long]`
  → load track records → features → cohesion → album review (Pass 2) → contextual track
  reviews (Pass 3) → write album record. QA view shows the album rung, `sum_vs_parts`, the
  rank distribution, and any track where `context_rank` diverges from `standalone_rank`.
- **Acceptance:** clean end-to-end run reusing existing song records; album JSON validates; track records untouched.
- **GATE:** **end of Phase 3.** Summarize the album module + how to run it, wait before Phase 4.

---

## PHASE 4 — Cumulative hardening (song + album)

Goal: harden, govern, and Cantor-shape **both** critics in one pass. Optional; pick what you want.

### WP-14 · Contracts, provenance, confidence (both record types)
- **Deliverable:** every worker — song and album — emits validated output with provenance + confidence; writers hedge on low confidence.
- **Files:** `critic/schema.py` (both records), validation wired into all workers.
- **Acceptance:** a low-confidence key softens song language; a thin-data album degrades gracefully instead of asserting a confident arc.
- **GATE:** stop, show one low-confidence case per layer, wait for review.

### WP-15 · Critic persona + tone knobs (shared)
- **Deliverable:** configurable persona used by all three writers (track, album, context).
- **Files:** `critic/personas/*.md`, plumbing into each writer.
- **Acceptance:** swapping persona changes voice consistently across all passes without breaking any ladder/floor.
- **GATE:** stop, show one persona across a track + album + contextual review, wait for review.

### WP-16 · Optional local impression model
- **Deliverable:** local audio-LLM behind the existing `impression` interface (Qwen-Omni Light/Flash or quantized Qwen2.5-Omni-7B), config-selectable.
- **Files:** `critic/impression_local.py`.
- **Notes:** must fit the 16GB ceiling. Gemini stays default. Song-layer only; the album passes inherit it for free via the records.
- **Acceptance:** local path produces a usable impression; album/context output unchanged in structure.
- **GATE:** stop, compare local vs Gemini on one track, wait for review.

### WP-17 · Eval + local approval gate (all passes)
- **Deliverable:** calibration harness + a **local** approval gate over every published text artifact (track, album, contextual).
- **Files:** `critic/eval.py`, `out/calibration.md`.
- **Behavior:** reference tracks **and** a reference album with expected rungs; flag drift.
  Approval gate is local to `mrp` — review text carries `pending` → `approved`, defaults to
  `pending`, only `publishable` after explicit approval; JSON records are automated. A code
  comment may note this mirrors Cantor's SOUL.md policy, but **`mrp` owns its own copy — do
  not import or look for SOUL.md.**
- **Acceptance:** rungs stable across reruns at all layers; nothing publishes without approval.
- **GATE:** **end of Phase 4.**

---

## Notes for the agent
- **Do not re-run song extraction for albums.** Passes 2–3 read `out/<track_id>.json`.
- **Pass 1 is immutable.** Pass 3 writes contextual reviews onto the **album** record only; `out/<track_id>.json` is never modified.
- Tracklist **order** is data — preserve it, never sort it.
- The album writer (WP-11) sets the album verdict; the recontextualizer (WP-12) handles per-track context. Keep them separate.
- Keep each album worker independently runnable (`python -m critic.album.<worker> ...`).
- SOUL.md is a **different project** (Cantor), out of scope. WP-17's gate is local to `mrp`.
- Stop at every GATE. Summarize, don't proceed.
