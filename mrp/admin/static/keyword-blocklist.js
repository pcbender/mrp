// The per-artist keyword blocklist, kept apart from the DOM so it can be tested
// directly against the same rules the server enforces.
//
// Patterns read like a .gitignore: `*` `?` `[abc]` globs, `#` comments, blank
// lines, and `!` to re-include, with the last matching line winning. Matching is
// case-insensitive and spans the whole keyword — `PCB*` blocks "PCB Bender",
// bare `PCB` blocks only the keyword "PCB".
//
// This mirrors is_blocked() in app/promoter/promoter/keywords.py and
// _is_blocked() in mrp/admin/routes/artists.py; tests assert all three agree.
(function (root, factory) {
  'use strict';

  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.mrpKeywordBlocklist = api;
})(typeof window === 'undefined' ? null : window, function () {
  'use strict';

  // Translate one glob to an anchored, case-insensitive regex. Everything
  // outside the three glob constructs is escaped, so a keyword containing
  // regex punctuation can't turn into a pattern of its own.
  function toRegExp(pattern) {
    let out = '';
    for (let i = 0; i < pattern.length; i++) {
      const c = pattern[i];
      if (c === '*') {
        out += '.*';
      } else if (c === '?') {
        out += '.';
      } else if (c === '[') {
        let j = i + 1;
        if (pattern[j] === '!' || pattern[j] === '^') j++;
        if (pattern[j] === ']') j++;
        while (j < pattern.length && pattern[j] !== ']') j++;
        if (j >= pattern.length) {
          out += '\\[';  // unterminated class — treat as a literal bracket
        } else {
          const cls = pattern.slice(i + 1, j).replace(/\\/g, '\\\\').replace(/^!/, '^');
          out += '[' + cls + ']';
          i = j;
        }
      } else {
        out += c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      }
    }
    return new RegExp('^' + out + '$', 'i');
  }

  function normalize(text) {
    return String(text == null ? '' : text).trim().replace(/\s+/g, ' ');
  }

  function isBlocked(keyword, patterns) {
    const target = normalize(keyword);
    if (!target) return false;

    let blocked = false;
    for (const raw of patterns || []) {
      let pattern = normalize(raw);
      if (!pattern || pattern.startsWith('#')) continue;
      const negated = pattern.startsWith('!');
      if (negated) pattern = pattern.slice(1).trim();
      if (!pattern) continue;
      if (toRegExp(pattern).test(target)) blocked = !negated;
    }
    return blocked;
  }

  // Split keywords into {kept, blocked}, preserving order in both.
  function apply(keywords, patterns) {
    const kept = [];
    const blocked = [];
    for (const keyword of keywords || []) {
      (isBlocked(keyword, patterns) ? blocked : kept).push(keyword);
    }
    return { kept: kept, blocked: blocked };
  }

  return { isBlocked: isBlocked, apply: apply, toRegExp: toRegExp };
});
