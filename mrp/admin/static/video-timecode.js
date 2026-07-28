// Browser half of mrp/admin/video_timecode.py — the one time format every
// track video page uses. Server-rendered text goes through the Jinja `seconds`
// filter; anything a script writes into the DOM goes through here, so a
// playhead readout and the scene list beside it agree to the digit.
//
// Load this before /static/video-live-preview.js on any page that needs it.
(function (root, factory) {
  'use strict';

  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) {
    root.mrpTimecode = api;
    root.mrpSeconds = api.seconds;
  }
})(typeof window === 'undefined' ? null : window, function () {
  'use strict';

  const MAX_PLACES = 3;

  // Anything unusable reads as the start of the track rather than as NaN in the
  // middle of a transport readout.
  function seconds(value, decimals) {
    const number = Number(value);
    const places = Math.max(
      0,
      Math.min(MAX_PLACES, Math.trunc(decimals === undefined ? 3 : decimals))
    );
    return `${(Number.isFinite(number) ? number : 0).toFixed(places)}s`;
  }

  return { seconds };
});
