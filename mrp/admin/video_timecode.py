"""The one time format for the music-video admin pages.

The track video pages had grown five renderings of the same quantity — ``M:SS``
in the track record, ``M:SS.ss`` in the full-track preview readout, ``M:SS.mmm``
in the timing scrubber, and both ``123.456s`` and ``123.46s`` in scene lists,
gap reports and render summaries. Reading a scene start on one page and matching
it against a render plan on the next meant converting in your head.

Everything now renders as seconds to three decimals, which is the unit the
aligned-lyrics YAML stores, the unit every editable input posts, and the unit
the renderer works in. A displayed scene end and the number in the field beside
it are the same string.

Editable inputs still format themselves — they need a bare number with no
suffix — but they agree with this to the digit.
"""

from __future__ import annotations

import math

_MAX_PLACES = 3


def seconds(value: object, places: int = 3) -> str:
    """Format track seconds as ``N.NNNs``.

    Anything unusable — a missing duration, a half-populated manifest — reads as
    the start of the track rather than raising inside a template.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        number = 0.0
    if not math.isfinite(number):
        number = 0.0
    return f"{number:.{max(0, min(_MAX_PLACES, int(places)))}f}s"
