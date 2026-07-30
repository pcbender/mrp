// The rule that keeps lyric cues from colliding, kept apart from the DOM so it
// can be tested directly.
//
// Dragging a cue's end past the next cue's start used to be a save-time error
// naming a document path. Instead the later cues give way, cascading for as
// long as they overlap. A scene's boundaries are set deliberately, so a cue
// that no longer fits inside its scene stops the cascade and is reported
// rather than silently widening the scene.
(function (root, factory) {
  'use strict';

  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.mrpTimingCascade = api;
})(typeof window === 'undefined' ? null : window, function () {
  'use strict';

  const EPS = 1e-6;

  // Values arrive as input .value strings. Number('') and Number(null) are both
  // 0, so plain coercion would read a cleared field as the start of the track
  // and shunt every later cue back to it.
  function toNumber(value) {
    if (value === null || value === undefined) return NaN;
    if (typeof value === 'string' && value.trim() === '') return NaN;
    return Number(value);
  }

  // cues: [{start, end}] in timeline order. Returns the moves to apply and, if
  // the cascade ran out of room, the cue that could not fit. Never mutates its
  // input: the caller decides whether to apply the plan.
  function plan(cues, sectionEnd, fromIndex) {
    const moves = [];
    let blocked = null;
    const limit = toNumber(sectionEnd);
    const hasLimit = Number.isFinite(limit);
    // Walk a working copy so a cue moved by one step is what the next step sees.
    const timeline = cues.map((cue) => ({
      start: toNumber(cue.start),
      end: toNumber(cue.end),
    }));

    for (let index = Math.max(0, fromIndex); index < timeline.length - 1; index += 1) {
      const current = timeline[index];
      const next = timeline[index + 1];
      if (![current.end, next.start, next.end].every(Number.isFinite)) break;
      // The first cue that already clears the one before it ends the cascade.
      if (next.start >= current.end - EPS) break;

      const start = current.end;
      // A cue keeps the end it has, unless the new start would swallow it — then
      // it keeps its length instead.
      const end = next.end > start + EPS ? next.end : start + (next.end - next.start);

      if (hasLimit && end > limit + EPS) {
        blocked = { index: index + 1, needs: end, limit };
        break;
      }

      next.start = start;
      next.end = end;
      moves.push({ index: index + 1, start, end });
    }

    return { moves, blocked };
  }

  return { plan, toNumber, EPS };
});
