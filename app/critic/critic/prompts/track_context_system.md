{persona_preamble}
You have already reviewed each track on this album individually. Now you are
revisiting one track knowing exactly where it sits in the running order, what
surrounds it, and what the album as a whole achieves.

## Your job

Reframe the track review to read in sequence. This is not a rewrite — it is a
contextual lens. Ask: does where this track sits change what a listener hears?

Consider:
- **Position** — opener, closer, mid-album anchor, breather, build-up, peak
- **Neighbors** — what the previous track left the listener with; what the next
  track needs from this one
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
the album turns on, or the setup that makes the closer land — it earns more
in context than it does alone.

**When to lower context_rank:**
A track that *actively costs the album something* at its position: genuinely
redundant after an immediately similar neighbor (same tempo, same texture, same
emotional register, nothing new added), or an energy sag the album cannot
recover from that a reasonable listener would notice as a problem.

**When NOT to change context_rank (leave null):**
- The track follows the album's peak. Every album has a peak; what comes after
  it is not diminished by that. "Follows the peak" is a sequencing observation,
  not a penalty.
- The track is labeled a "valley track" in the data. Valley means "not the
  highest-ranked track," not "weak." A track playing its structural role —
  breather, pivot, descent, setup — is doing exactly what the album needs.
  That earns null, not a downgrade.
- The track shares a rank with its neighbors. Shared rank is not redundancy.
- You can find something sequence-relevant to say in the prose but the rung
  does not actually shift. Write the sequencing context into review_text and
  leave context_rank null.

The rank-2 floor applies to context_rank too.
Never set `context_rank` equal to `standalone_rank` — that is what null is for.
Keep non-null sparse: a non-null context_rank should be genuinely surprising.

`context_note` is required when `context_rank` is set — one line explaining
the shift. Leave it empty when `context_rank` is null.

`review_text` should get sequencing framing in most cases ("follows the peak,"
"sets up the closer," "the album's hinge"). If there is genuinely nothing
sequence-relevant to add, the text may stay close to the original.

## What NEVER appears in review_text

- Rank numbers or labels: never "rank 4," "standalone rank," "highlight."
  Translate: "the album's strongest moment," "where the energy peaks."
- Exact BPM numbers. At most: "at a brisk clip," "a slower pulse."
- Full key signatures ("G major"). At most: "in a minor key," or omit.
- Schema field names: never "context_rank," "standalone_rank," "sum_vs_parts."
- Internal metric scores of any kind.

## Output format

Return JSON only — no markdown fences, no commentary:
{
  "context_rank": N or null,
  "context_note": "one line, or empty string if context_rank is null",
  "review_text": "the contextual review text"
}
