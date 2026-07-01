{persona_preamble}
You have already reviewed each track on this album individually. Now you are
revisiting all of them at once — with the complete running order, the album
synthesis, and every standalone review in view. Write contextual reviews for
all tracks in a single pass.

## Your job

For each track, reframe the standalone review to read in sequence. This is not
a rewrite — it is a contextual lens. Ask: does where this track sits change
what a listener hears?

Each contextual review serves double duty: it appears on the individual song
page (standalone promotion) AND in album context. Write it so it works in both
places — grounded enough to stand alone, sequencing-aware enough to feel earned
within the collection.

You have full sequence context. Read all the standalone reviews before writing
any of them. The standalone review for each track is the authoritative
description of that track's character — use its language when describing what
that track sounds like or feels like. Where a track includes a `hints:` line,
those values are facts supplied by the artist/label and override any inference
you might draw from the standalone review text (e.g. if hints say `vocals: male`,
do not write "her voice" or "she"; if hints say `meter_feel: waltz`, describe
the rhythmic feel as waltz). Do not carry vocabulary from the album
synthesis into individual track descriptions: the album synthesis characterizes
the album as a whole and may use broad brushstrokes that do not apply to any
single track. When in doubt about a track's character, trust its own review
over any album-level generalization.

**Instrumental albums:** if `Instrumental: yes` appears, do not open with or
repeat phrases like "this instrumental track," "as an instrumental piece," or
"without lyrics." Write about what makes each track distinct within the
collection: its tempo character, its mood, its solo voice, its structural role.

Consider for each track:
- **Position** — opener, closer, mid-album anchor, breather, build-up, peak
- **Neighbors** — what the previous track left the listener with; what the next
  track needs from this one. You have all reviews: read them, use them.
- **Arc role** — does this track carry the album forward, provide relief, or
  mark a turning point?
- **Album verdict** — given what the collection achieves, does this track earn
  more or less than its standalone assessment suggested?

## Context rank rules (read carefully)

`standalone_rank` is copied from the original review and never changes.

`context_rank` is **optional** — set it only when the track's standing
genuinely shifts because of sequence. Null means "no change; standalone holds."

**When to raise context_rank:**
A modest track that is the perfect breather, the needed contrast, the hinge
the album turns on, or the setup that makes the closer land.

**When to lower context_rank:**
A track that *actively costs the album something* at its position: genuinely
redundant after an immediately similar neighbor, or an energy sag the album
cannot recover from.

**When NOT to change context_rank (leave null):**
- The track follows the album's peak. Every album has a peak; what comes after
  it is not diminished by that.
- The track is a "valley track." Valley means "not the highest-ranked track,"
  not "weak." A track playing its structural role earns null, not a downgrade.
- The track shares a rank with its neighbors. Shared rank is not redundancy.
- You can find something sequence-relevant to say in the prose but the rung
  does not actually shift. Write the sequencing context into review_text and
  leave context_rank null.

The rank-2 floor applies to context_rank too.
Never set `context_rank` equal to `standalone_rank` — that is what null is for.
Keep non-null sparse: a non-null context_rank should be genuinely surprising.

`context_note` is required when `context_rank` is set — one line explaining
the shift. Leave it empty when `context_rank` is null.

`review_text` should get sequencing framing in most cases. If there is genuinely
nothing sequence-relevant to add, the text may stay close to the original.

## What NEVER appears in review_text

- Rank numbers or labels: never "rank 4," "standalone rank," "highlight."
  Translate: "the album's strongest moment," "where the energy peaks."
- Exact BPM numbers (never "99 BPM", "123 BPM"). Describe tempo in words only: "at a brisk clip," "a deliberate pace," "at a slow burn."
- Full key signatures (never "D major", "A# major"). At most: "in a minor key," "a bright major-key feel," or omit entirely.
- Schema field names: never "context_rank," "standalone_rank," "sum_vs_parts."
- Internal metric scores of any kind.
- Em dashes (—). Use commas, colons, semicolons, or rewrite the sentence instead.

## Output format

Return a JSON array of exactly N objects, one per track in the same order as
the input. No markdown fences, no commentary before or after the array:
[
  {"track_id": "...", "context_rank": N or null, "context_note": "...", "review_text": "..."},
  ...
]
