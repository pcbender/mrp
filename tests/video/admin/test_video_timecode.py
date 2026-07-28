"""The admin's one time format, and its parity with the browser half.

Server-rendered scene lists and script-written playhead readouts sit next to
each other on the same page, so the Python and JavaScript formatters have to
agree character for character. The parity test runs both over one table of
values rather than asserting a hand-copied expectation twice.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from mrp.admin.video_timecode import seconds

_TIMECODE_JS = (
    Path(__file__).resolve().parents[3] / "mrp" / "admin" / "static" / "video-timecode.js"
)

# Positions, a rounding boundary, an hour-long render, and the junk a partially
# populated manifest can hand a template.
_VALUES = [0, 3.5, 39.462, 59.9996, 90.005, 218.7333, 3661.5, None, "x", -4]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0.000s"),
        (3.5, "3.500s"),
        # The unit and precision the aligned-lyrics YAML stores, so a displayed
        # scene end matches the number in the field beside it.
        (39.462, "39.462s"),
        (218.7333, "218.733s"),
        # Hours never turn into a second colon-separated format.
        (3661.5, "3661.500s"),
        # A missing duration reads as the start of the track, never a crash.
        (None, "0.000s"),
        ("x", "0.000s"),
        (-4, "-4.000s"),
    ],
)
def test_seconds_formats_track_time(value: object, expected: str) -> None:
    assert seconds(value) == expected


def test_seconds_honours_a_narrower_precision() -> None:
    assert seconds(218.7333, places=1) == "218.7s"


def test_browser_and_server_formatters_agree() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")
    script = (
        f"const t = require({str(_TIMECODE_JS)!r});"
        f"const values = {json.dumps(_VALUES)};"
        "console.log(JSON.stringify(values.map((v) => t.seconds(v))));"
    )
    result = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout) == [seconds(v) for v in _VALUES]
