"""YouTube channel keywords on the artist record — schema, admin parsing,
and the promoter's append-only merge against the 500-character budget."""

import os
import sys
from pathlib import Path

import pytest

from mrp.admin.routes.artists import (
    KEYWORD_BUDGET,
    _SCHEMA_PATH,
    _apply_blocklist,
    _is_blocked,
    _keyword_field,
    _parse_blocklist,
    _parse_keywords,
)
from mrp.core.validate import validate_schema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "promoter"))

# promoter.config calls load_dotenv() at import time, which would otherwise leak
# the repo's real API keys into os.environ for the whole session — see the same
# guard in test_keyword_evidence.py.
_ENV_BEFORE = dict(os.environ)
from promoter import writeback  # noqa: E402
from promoter.keywords import (  # noqa: E402
    apply_blocklist,
    is_blocked,
    keyword_field,
    merge_keywords,
    normalize,
)

os.environ.clear()
os.environ.update(_ENV_BEFORE)


def _record(**extra):
    return {"artist": {"id": "stab", "name": "STAB", "visibility": "public", **extra}}


# --- schema ------------------------------------------------------------------

def test_schema_accepts_keywords(tmp_path):
    record = _record(keywords=["desert psychedelia", "STAB"], keywords_auto_generated=True)
    assert validate_schema(tmp_path / "stab.yaml", record, _SCHEMA_PATH) == []


def test_schema_accepts_record_without_keywords(tmp_path):
    assert validate_schema(tmp_path / "stab.yaml", _record(), _SCHEMA_PATH) == []


def test_schema_rejects_empty_keyword(tmp_path):
    assert validate_schema(tmp_path / "stab.yaml", _record(keywords=[""]), _SCHEMA_PATH)


def test_schema_rejects_non_list_keywords(tmp_path):
    assert validate_schema(tmp_path / "stab.yaml", _record(keywords="a, b"), _SCHEMA_PATH)


# --- admin form parsing ------------------------------------------------------

def test_parse_keywords_accepts_lines_and_commas():
    assert _parse_keywords("desert rock\nslide guitar, STAB") == [
        "desert rock", "slide guitar", "STAB",
    ]


def test_parse_keywords_dedupes_case_insensitively():
    assert _parse_keywords("Desert Rock\ndesert rock") == ["Desert Rock"]


def test_parse_keywords_strips_quotes_and_collapses_space():
    assert _parse_keywords('  "slide   guitar"  ') == ["slide guitar"]


def test_parse_keywords_empty_is_empty():
    assert _parse_keywords("   \n  \n") == []


def test_keyword_field_quotes_only_multiword():
    assert _keyword_field(["STAB", "desert rock"]) == 'STAB, "desert rock"'


def test_admin_and_promoter_field_formats_agree():
    keywords = ["STAB", "desert rock", "slide guitar"]
    assert _keyword_field(keywords) == keyword_field(keywords)


def test_admin_and_promoter_budgets_agree():
    from promoter.keywords import KEYWORD_BUDGET as PROMOTER_BUDGET
    assert KEYWORD_BUDGET == PROMOTER_BUDGET


# --- merge -------------------------------------------------------------------

def test_merge_appends_new_after_existing():
    kept, dropped, _ = merge_keywords(["desert rock"], ["slide guitar"])
    assert kept == ["desert rock", "slide guitar"]
    assert dropped == []


def test_merge_never_reorders_or_drops_curated_keywords():
    existing = ["zzz last", "aaa first"]
    kept, _, _ = merge_keywords(existing, ["new one"])
    assert kept[:2] == existing


def test_merge_skips_candidates_already_present():
    kept, _, _ = merge_keywords(["desert rock"], ["Desert Rock", "slide guitar"])
    assert kept == ["desert rock", "slide guitar"]


def test_merge_drops_newest_first_when_over_budget():
    # 21 quoted keywords joined with ", " is 481 chars — room for one more, not two.
    existing = [f"existing keyword {i:02d}" for i in range(21)]
    kept, dropped, _ = merge_keywords(existing, ["candidate one", "candidate two"])
    assert len(keyword_field(kept)) <= KEYWORD_BUDGET
    # Candidates are at the tail, so they go before anything already curated.
    assert kept == existing + ["candidate one"]
    assert dropped == ["candidate two"]


def test_merge_trims_existing_that_overflows_on_its_own():
    existing = [f"a very long existing keyword number {i:02d}" for i in range(30)]
    kept, dropped, _ = merge_keywords(existing, [])
    assert len(keyword_field(kept)) <= KEYWORD_BUDGET
    assert dropped
    assert kept == existing[: len(kept)]


def test_merge_budget_measures_the_pasted_string():
    # Two 3-char keywords: "abc, def" is 8 chars, so a budget of 8 fits both.
    kept, dropped, _ = merge_keywords(["abc", "def"], [], budget=8)
    assert kept == ["abc", "def"] and dropped == []
    kept, dropped, _ = merge_keywords(["abc", "def"], [], budget=7)
    assert kept == ["abc"] and dropped == ["def"]


def test_merge_counts_quotes_of_multiword_keywords():
    # '"a b"' is 5 chars, not 3.
    kept, _, _ = merge_keywords(["a b"], [], budget=4)
    assert kept == []


def test_normalize_drops_blanks_and_duplicates():
    assert normalize(["  ", "one", "One", None, "two"]) == ["one", "two"]


# --- blocklist ---------------------------------------------------------------

def test_schema_accepts_blocklist(tmp_path):
    record = _record(keywords=["desert rock"], keywords_blocked=["PCB*", "# note", "!PCB Official"])
    assert validate_schema(tmp_path / "stab.yaml", record, _SCHEMA_PATH) == []


def test_blocklist_star_matches_prefix():
    # The motivating case: PCB* removes "PCB Bender" without touching the rest.
    assert is_blocked("PCB Bender", ["PCB*"])
    assert is_blocked("PCBender music", ["PCB*"])
    assert not is_blocked("classic rock", ["PCB*"])


def test_blocklist_matches_whole_keyword_not_substring():
    # gitignore semantics: a bare pattern is not an implicit prefix match.
    assert not is_blocked("PCB Bender", ["PCB"])
    assert is_blocked("PCB", ["PCB"])


def test_blocklist_is_case_insensitive():
    assert is_blocked("pcb bender", ["PCB*"])
    assert is_blocked("PCB BENDER", ["pcb*"])


def test_blocklist_ignores_comments_and_blanks():
    assert not is_blocked("PCB Bender", ["# PCB*", "", "   "])


def test_blocklist_negation_re_includes_last_match_wins():
    patterns = ["PCB*", "!PCB Bender Official"]
    assert is_blocked("PCB Bender", patterns)
    assert not is_blocked("PCB Bender Official", patterns)


def test_blocklist_negation_order_matters():
    # Reversed, the broad rule wins because it comes last.
    patterns = ["!PCB Bender Official", "PCB*"]
    assert is_blocked("PCB Bender Official", patterns)


def test_blocklist_supports_question_mark_and_class():
    assert is_blocked("PCB1", ["PCB?"])
    assert is_blocked("PCB1", ["PCB[0-9]"])
    assert not is_blocked("PCBx", ["PCB[0-9]"])


def test_blocklist_empty_patterns_block_nothing():
    assert not is_blocked("anything", [])
    assert not is_blocked("anything", None)


def test_apply_blocklist_splits_and_preserves_order():
    kept, blocked = apply_blocklist(
        ["classic rock", "PCB Bender", "blues rock", "PCBender music"], ["PCB*"]
    )
    assert kept == ["classic rock", "blues rock"]
    assert blocked == ["PCB Bender", "PCBender music"]


def test_merge_applies_blocklist_retroactively_to_existing():
    # The whole point: adding a pattern prunes what is already on the record.
    kept, _, blocked = merge_keywords(["classic rock", "PCB Bender"], [], ["PCB*"])
    assert kept == ["classic rock"]
    assert blocked == ["PCB Bender"]


def test_merge_blocks_candidates_before_budgeting():
    kept, dropped, blocked = merge_keywords(["abc"], ["PCB Bender", "def"], ["PCB*"])
    assert kept == ["abc", "def"]
    assert blocked == ["PCB Bender"]
    assert dropped == []


def test_blocked_keywords_do_not_consume_budget():
    # "PCB Bender" is blocked, so "def" fits in a budget that could not hold both.
    kept, dropped, blocked = merge_keywords(["abc", "PCB Bender", "def"], [], ["PCB*"], budget=8)
    assert kept == ["abc", "def"] and dropped == [] and blocked == ["PCB Bender"]


def test_parse_blocklist_keeps_comments_and_order():
    assert _parse_blocklist("# name variants\nPCB*\n!PCB Official\n") == [
        "# name variants", "PCB*", "!PCB Official",
    ]


def test_parse_blocklist_drops_only_trailing_blanks():
    assert _parse_blocklist("PCB*\n\nfoo*\n\n\n") == ["PCB*", "", "foo*"]


def test_admin_and_promoter_blocklists_agree():
    patterns = ["PCB*", "!PCB Bender Official", "# comment", "x?z", "q[0-9]"]
    for keyword in ("PCB Bender", "PCB Bender Official", "PCB", "xyz", "q7", "classic rock"):
        assert _is_blocked(keyword, patterns) == is_blocked(keyword, patterns), keyword
    assert _apply_blocklist(["PCB Bender", "classic rock"], patterns) == \
        apply_blocklist(["PCB Bender", "classic rock"], patterns)


# --- writeback ---------------------------------------------------------------

def test_write_keywords_round_trips_and_flags(tmp_path, monkeypatch):
    import yaml

    monkeypatch.setattr(writeback, "ARTISTS_DIR", tmp_path)
    path = tmp_path / "stab.yaml"
    path.write_text(
        yaml.dump({"artist": {"id": "stab", "name": "STAB", "visibility": "public"}}),
        encoding="utf-8",
    )

    writeback.write_keywords("stab", ["desert rock", "Björk-adjacent"])

    artist = yaml.safe_load(path.read_text(encoding="utf-8"))["artist"]
    assert artist["keywords"] == ["desert rock", "Björk-adjacent"]
    assert artist["keywords_auto_generated"] is True
    assert artist["name"] == "STAB"  # untouched
    # content/ YAML keeps real UTF-8, not \\uXXXX escapes.
    assert "Björk-adjacent" in path.read_text(encoding="utf-8")
