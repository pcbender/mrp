"""The browser rule that keeps lyric cues from colliding.

Exercised through node against the same file the page loads, so the behaviour
tested is the behaviour shipped.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_CASCADE_JS = (
    Path(__file__).resolve().parents[3]
    / "mrp"
    / "admin"
    / "static"
    / "video-timing-cascade.js"
)


def _plan(cues: list[dict], section_end, from_index: int) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")
    script = (
        f"const c = require({str(_CASCADE_JS)!r});"
        f"const out = c.plan({json.dumps(cues)}, {json.dumps(section_end)},"
        f" {from_index});"
        "console.log(JSON.stringify(out));"
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def test_a_cue_pushed_forward_moves_the_next_one_out_of_the_way():
    cues = [
        {"start": 40.1, "end": 42.5},  # just dragged out to 42.5
        {"start": 42.1, "end": 44.9},
        {"start": 45.2, "end": 47.0},
    ]

    result = _plan(cues, 60.0, 0)

    # Only the overlapping neighbour moves; its end is untouched because the
    # new start still leaves it a length.
    assert result["moves"] == [{"index": 1, "start": 42.5, "end": 44.9}]
    # Cue 3 already cleared cue 2, so the cascade stops rather than shunting
    # every remaining cue down the timeline.
    assert result["blocked"] is None


def test_the_cascade_carries_through_a_run_of_overlapping_cues():
    cues = [
        {"start": 0.0, "end": 5.0},
        {"start": 1.0, "end": 2.0},
        {"start": 1.5, "end": 2.5},
    ]

    result = _plan(cues, 60.0, 0)

    # Each cue is swallowed by the new start, so each keeps its length instead
    # of its end, and the one after it sees the moved value.
    assert result["moves"] == [
        {"index": 1, "start": 5.0, "end": 6.0},
        {"index": 2, "start": 6.0, "end": 7.0},
    ]
    assert result["blocked"] is None


def test_a_cue_that_will_not_fit_stops_the_cascade_instead_of_moving_the_scene():
    cues = [
        {"start": 40.0, "end": 42.5},
        {"start": 42.1, "end": 44.9},
        {"start": 44.5, "end": 46.4},
    ]

    result = _plan(cues, 46.0, 0)

    # The cue that fits is moved; the one that would run past the scene end is
    # reported so the scene boundary is never widened behind the reader's back.
    assert result["moves"] == [{"index": 1, "start": 42.5, "end": 44.9}]
    assert result["blocked"] == {"index": 2, "needs": 46.4, "limit": 46.0}


def test_cues_that_already_clear_each_other_are_left_alone():
    cues = [
        {"start": 0.0, "end": 1.0},
        {"start": 1.0, "end": 2.0},
        {"start": 3.0, "end": 4.0},
    ]

    assert _plan(cues, 10.0, 0) == {"moves": [], "blocked": None}


def test_an_unreadable_boundary_stops_the_cascade_rather_than_writing_NaN():
    cues = [
        {"start": 0.0, "end": 5.0},
        {"start": "", "end": 6.0},
        {"start": 1.0, "end": 2.0},
    ]

    assert _plan(cues, 10.0, 0) == {"moves": [], "blocked": None}


def test_a_missing_scene_end_still_moves_cues():
    """The scene end is only a limit; without one, nothing blocks."""
    cues = [{"start": 0.0, "end": 5.0}, {"start": 1.0, "end": 6.0}]

    result = _plan(cues, None, 0)

    assert result["moves"] == [{"index": 1, "start": 5.0, "end": 6.0}]
    assert result["blocked"] is None
