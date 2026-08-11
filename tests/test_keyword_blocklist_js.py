"""The browser copy of the keyword blocklist.

The same .gitignore-style rules are implemented three times — the promoter (which
writes the YAML), the admin route (which saves the form), and the browser (which
previews the effect live). A keyword that the page shows as kept but the server
strips on save would be a silent surprise, so these run node against the exact
file the page loads and assert it agrees with both Python copies.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mrp.admin.routes.artists import _is_blocked

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "promoter"))
from promoter.keywords import is_blocked  # noqa: E402

_BLOCKLIST_JS = (
    Path(__file__).resolve().parents[1] / "mrp" / "admin" / "static" / "keyword-blocklist.js"
)

# Each case is (keyword, patterns). Kept as data so every case runs through all
# three implementations rather than only the one a hand-written assert names.
CASES = [
    ("PCB Bender", ["PCB*"]),
    ("PCBender music", ["PCB*"]),
    ("classic rock", ["PCB*"]),
    ("PCB Bender", ["PCB"]),               # whole-keyword match, so no
    ("PCB", ["PCB"]),
    ("pcb bender", ["PCB*"]),              # case-insensitive
    ("PCB BENDER", ["pcb*"]),
    ("PCB Bender", ["# PCB*", "", "   "]),  # comments and blanks are inert
    ("PCB Bender", ["PCB*", "!PCB Bender Official"]),
    ("PCB Bender Official", ["PCB*", "!PCB Bender Official"]),
    ("PCB Bender Official", ["!PCB Bender Official", "PCB*"]),  # last match wins
    ("PCB1", ["PCB?"]),
    ("PCB1", ["PCB[0-9]"]),
    ("PCBx", ["PCB[0-9]"]),
    ("PCBx", ["PCB[!0-9]"]),               # negated character class
    ("anything", []),
    ("", ["*"]),                            # empty keyword is never blocked
    ("rock (live)", ["rock (live)"]),      # regex punctuation stays literal
    ("rock xlive)", ["rock (live)"]),
    ("a+b", ["a+b"]),
    ("aab", ["a+b"]),
    ("desert rock", ["*rock"]),
    ("desert rock", ["desert *"]),
    ("PCB Bender", ["PCB [", "PCB*"]),     # unterminated class is a literal
]


def _js_blocked(cases: list[tuple[str, list[str]]]) -> list[bool]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")
    script = (
        f"const b = require({str(_BLOCKLIST_JS)!r});"
        f"const cases = {json.dumps(cases)};"
        "console.log(JSON.stringify(cases.map(c => b.isBlocked(c[0], c[1]))));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_browser_blocklist_agrees_with_both_python_copies():
    js = _js_blocked([[k, p] for k, p in CASES])
    mismatches = [
        (keyword, patterns, is_blocked(keyword, patterns), _is_blocked(keyword, patterns), js[i])
        for i, (keyword, patterns) in enumerate(CASES)
        if not (is_blocked(keyword, patterns) == _is_blocked(keyword, patterns) == js[i])
    ]
    assert not mismatches, f"promoter/admin/browser disagree: {mismatches}"


def test_the_motivating_case_blocks_in_the_browser_too():
    assert _js_blocked([["PCB Bender", ["PCB*"]]]) == [True]


def test_browser_apply_splits_kept_and_blocked():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable")
    script = (
        f"const b = require({str(_BLOCKLIST_JS)!r});"
        "console.log(JSON.stringify("
        "b.apply(['classic rock', 'PCB Bender', 'blues rock'], ['PCB*'])));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {
        "kept": ["classic rock", "blues rock"],
        "blocked": ["PCB Bender"],
    }
