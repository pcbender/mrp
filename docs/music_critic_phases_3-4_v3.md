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


## Clarifications

Questions 3

Give CP a method, not the placeholder. The short version: cosine-to-centroid, not pairwise Jaccard. Here's the reasoning to pass along.
Jaccard has two weaknesses for this. It's binary — it throws away tag strength, so two tracks both weakly "rock" score identically to two strongly "rock," and it needs an arbitrary threshold to decide when a track "has" a tag. And it's pairwise, so you're aggregating O(n²) comparisons. The cleaner construction:
For each track, build a feature vector from the tagger's probability distributions (genre ⊕ mood ⊕ instrument), L2-normalized. Take the album centroid (mean vector). Then palette_consistency = mean cosine similarity of each track to the centroid, which lands in [0, 1], is O(n), and respects strength without any thresholding knob. 1.0 = every track sits on the centroid; lower = scattered.
Which signal to feed it depends on what WP-6 actually retained, best to worst:

Raw CLAP audio embeddings (if cached) → centroid cosine over those. Truest palette measure, because embeddings encode timbre and production, not just labels — two tracks can both be "rock" with completely different palettes, and the embedding catches what the label can't.
Decoded tag probability vectors → centroid cosine over the concatenated genre/mood/instrument vectors. Good, and probably what you have.
Only top-k discrete tags, no scores → fall back to overlap ratio, but flag it as the weak option and ideally have WP-6 keep the scores.

Two design points worth stating so CP doesn't drift:
Keep tempo and key out of palette_consistency. Palette is timbre/genre/mood — texture. Tempo and key are movement, and the BPM/key progressions in album_features already carry that as arc. An album can deliberately vary tempo while staying tonally cohesive; folding those in would conflate two different axes and muddy both.
Don't hardcode the cohesion thresholds. Cosine over sparse non-negative vectors runs high in absolute terms (0.7–0.95 even for fairly varied albums), so the raw number is less meaningful than the relative spread. The cohesive_statement | varied | shuffle_playlist cutoffs should be calibrated on a couple of real albums — one you'd call cohesive, one eclectic — and that calibration belongs in WP-17, not guessed now. For <2 tracks, return 1.0 and skip the verdict.
So the answer to CP's question: yes, it's yours to implement, but the intended method is centroid cosine over the richest available tag/embedding vectors, 0–1, texture-only, thresholds deferred to eval.

Question 4

Your read is right — null when sequence doesn't move the standing, set only on a real shift. Keep it sparse, because the sparsity is the signal: a non-null context_rank is your QA query for "tracks whose standing is sequence-dependent." If you always populate it, you've buried that signal under echoes of standalone_rank and now have to diff two fields on every track to find the interesting ones. Null-means-unchanged makes divergence self-announcing, which is the same logic as freezing Pass 1 and treating context as the delta.
The rule to hand CP, made precise:

Always copy standalone_rank.
Ask: would a reasonable critic place this track on a different rung because of where it sits in the sequence? Yes → set context_rank (still respecting the rank-2 floor) and a one-line context_note with the reason. No → context_rank = null.
Don't set context_rank equal to standalone_rank as a "no change" marker — that's what null is for. Populating it defensively defeats the purpose.

Two things worth making explicit so CP gets the edges:
context_rank moves both directions. Up is the breather-earns-its-place case. Down is a standalone-strong track that sags the album where it sits, or is redundant after a similar neighbor — and a downward context_rank is a sequencing flag, not a knock on the song, because standalone_rank still holds the song's honest standing. Both directions are useful QA.
And separate context_rank from review_text. The text should get light sequencing framing pretty often — "follows the peak," "sets up the closer" — even when the rung doesn't move. So review_text can differ from standalone while context_rank stays null. The rank is reserved for an actual change in standing; the prose just reads in sequence. If there's genuinely nothing sequence-relevant to say, the contextual text may equal the standalone — that's fine, not a failure.
Net: yes to your judgment call. Set on meaningful rung change, null otherwise, note required when set, text reframed freely regardless.