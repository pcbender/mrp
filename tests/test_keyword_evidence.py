"""Evidence gathering and the triumvirate tally.

Both halves are pure: candidates come from files on disk, and consensus is a
count over ballots. Neither calls a model, so the rules that decide what may be
claimed for a channel are tested directly.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "promoter"))

# promoter.config calls load_dotenv() at import time. Left alone that puts the
# repo's real API keys into os.environ for the rest of the session, and tests
# elsewhere that assert a tool "fails cleanly without an API key" then find one
# and pass when they should fail. Restore the environment after importing.
_ENV_BEFORE = dict(os.environ)
from promoter.evidence import (  # noqa: E402
    Candidate,
    gather,
    gated,
    name_variants,
    tempo_terms,
    track_release_map,
)
from promoter.triumvirate import consensus  # noqa: E402

os.environ.clear()
os.environ.update(_ENV_BEFORE)


def _catalog(tmp_path: Path, releases: dict[str, list[str]], artist: str = "stab") -> tuple[Path, Path]:
    """Write a synthetic catalog: {release_slug: [track_slug, ...]}."""
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir(exist_ok=True)
    for index, (release_slug, tracks) in enumerate(releases.items()):
        (releases_dir / f"{release_slug}.yaml").write_text(
            yaml.dump({"release": {
                "slug": release_slug,
                "artist_id": artist,
                "release_date": f"2025-{index % 12 + 1:02d}-01",
                "tracks": [{"slug": t, "title": t} for t in tracks],
            }}),
            encoding="utf-8",
        )
    critic_dir = tmp_path / "critic"
    critic_dir.mkdir(exist_ok=True)
    return critic_dir, releases_dir


def _record(critic_dir: Path, track: str, genre=(), instruments=(), bpm=None, artist="stab"):
    payload = {"tags": {"genre": list(genre), "instruments": list(instruments)}}
    if bpm is not None:
        payload["hard_facts"] = {"bpm": bpm}
    (critic_dir / f"{artist}--{track}.json").write_text(json.dumps(payload), encoding="utf-8")


# --- mapping -----------------------------------------------------------------

def test_track_release_map_links_tracks_to_their_release(tmp_path):
    _, releases_dir = _catalog(tmp_path, {"ep-one": ["a", "b"], "single-two": ["c"]})
    tracks, dates = track_release_map("stab", releases_dir)
    assert tracks == {"a": "ep-one", "b": "ep-one", "c": "single-two"}
    assert set(dates) == {"ep-one", "single-two"}


def test_track_release_map_includes_the_song_of_a_single(tmp_path):
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    (releases_dir / "lone.yaml").write_text(
        yaml.dump({"release": {"slug": "lone", "artist_id": "stab",
                               "song": {"slug": "lone-song", "title": "Lone"}}}),
        encoding="utf-8",
    )
    tracks, _ = track_release_map("stab", releases_dir)
    assert tracks == {"lone-song": "lone"}


def test_track_release_map_ignores_other_artists(tmp_path):
    _, releases_dir = _catalog(tmp_path, {"mine": ["a"]}, artist="stab")
    tracks, _ = track_release_map("someone-else", releases_dir)
    assert tracks == {}


# --- gathering ---------------------------------------------------------------

def test_gather_counts_releases_not_tracks(tmp_path):
    # Four tracks carry the tag, but they sit on two releases.
    critic_dir, releases_dir = _catalog(tmp_path, {"r1": ["a", "b"], "r2": ["c", "d"], "r3": ["e"]})
    for track in ("a", "b", "c", "d"):
        _record(critic_dir, track, genre=["classic rock"])
    _record(critic_dir, "e", genre=["folk"])

    result = gather("stab", critic_dir, releases_dir)
    rock = next(c for c in result["candidates"] if c.term == "classic rock")
    assert rock.tracks == 4
    assert len(rock.releases) == 2
    assert result["total_releases"] == 3
    assert result["matched"] == 5


def test_gather_skips_critic_records_with_no_live_release(tmp_path):
    critic_dir, releases_dir = _catalog(tmp_path, {"r1": ["a"]})
    _record(critic_dir, "a", genre=["rock"])
    _record(critic_dir, "orphan", genre=["jazz"])  # no release references it

    result = gather("stab", critic_dir, releases_dir)
    assert result["matched"] == 1
    assert [c.term for c in result["candidates"]] == ["rock"]


def test_gather_survives_an_unreadable_record(tmp_path):
    critic_dir, releases_dir = _catalog(tmp_path, {"r1": ["a", "b"]})
    _record(critic_dir, "a", genre=["rock"])
    (critic_dir / "stab--b.json").write_text("{not json", encoding="utf-8")

    result = gather("stab", critic_dir, releases_dir)
    assert [c.term for c in result["candidates"]] == ["rock"]


# --- gates -------------------------------------------------------------------

def _candidate(term: str, releases: int, tracks: int | None = None) -> Candidate:
    return Candidate(
        term=term, kind="genre",
        tracks=tracks if tracks is not None else releases,
        releases={f"r{i}" for i in range(releases)},
    )


def test_rate_floor_cuts_the_bagpipes_case():
    # 7 of 88 releases is dispersed but rare — the motivating rejection.
    passed, rejected = gated([_candidate("bagpipes", 7)], total_releases=88)
    assert passed == []
    assert [c.term for c in rejected] == ["bagpipes"]


def test_rate_floor_keeps_a_catalog_wide_trait():
    passed, _ = gated([_candidate("classic rock", 78)], total_releases=88)
    assert [c.term for c in passed] == ["classic rock"]


def test_dispersion_floor_cuts_a_concentrated_tag():
    # 2 of 4 releases clears the rate floor but is too concentrated to claim.
    passed, rejected = gated([_candidate("sea shanty", 2)], total_releases=4)
    assert passed == []
    assert [c.term for c in rejected] == ["sea shanty"]


def test_both_floors_must_be_cleared():
    # Exactly at the floors: 3 releases and 25%.
    passed, _ = gated([_candidate("blues", 3)], total_releases=12)
    assert [c.term for c in passed] == ["blues"]


def test_gates_are_inert_when_the_catalog_is_empty():
    passed, rejected = gated([_candidate("rock", 0)], total_releases=0)
    assert passed == [] and len(rejected) == 1


def test_evidence_line_reports_releases_tracks_and_span():
    candidate = Candidate(term="blues", kind="genre", tracks=9,
                          releases={"a", "b"}, dates=["2025-02-01", "2026-04-01"])
    assert candidate.evidence(8) == "2/8 releases (25%), 9 tracks, 2025-02..2026-04"


# --- derived terms -----------------------------------------------------------

def test_tempo_terms_use_the_median_not_the_outliers():
    assert tempo_terms([70.0, 72.0, 74.0, 200.0]) == ["slow tempo"]
    assert tempo_terms([]) == []


def test_name_variants_splits_internal_capitals():
    assert "4 Castle" in name_variants("4Castle")


def test_name_variants_leaves_all_caps_runs_alone():
    # "PCBender" must not become "P C Bender".
    assert name_variants("PCBender")[0] == "PCBender"
    assert all(" " not in v.split(" music")[0].split(" official")[0]
               for v in name_variants("PCBender"))


def test_name_variants_dedupe_and_empty():
    assert name_variants("") == []
    assert len(name_variants("Stab")) == len(set(name_variants("Stab")))


# --- consensus ---------------------------------------------------------------

def _vote(candidate, keep=True, phrasing=""):
    return {"candidate": candidate, "keep": keep, "phrasing": phrasing or candidate}


def test_two_of_three_keeps_survives():
    kept, _ = consensus(
        ["classic rock"],
        {"gemini": [_vote("classic rock")],
         "claude": [_vote("classic rock")],
         "openai": [_vote("classic rock", keep=False)]},
    )
    assert kept == ["classic rock"]


def test_one_lone_keep_does_not_survive():
    kept, tally = consensus(
        ["instrumental rock"],
        {"gemini": [_vote("instrumental rock")],
         "claude": [_vote("instrumental rock", keep=False)],
         "openai": [_vote("instrumental rock", keep=False)]},
    )
    assert kept == []
    assert tally[0]["keeps"] == ["gemini"] and tally[0]["kept"] is False


def test_a_model_cannot_add_a_candidate():
    # The core guarantee: a term nobody put on the ballot cannot get in.
    kept, tally = consensus(
        ["classic rock"],
        {"gemini": [_vote("classic rock"), _vote("Scottish music")],
         "claude": [_vote("classic rock"), _vote("Scottish music")],
         "openai": [_vote("Scottish music")]},
    )
    assert kept == ["classic rock"]
    assert [row["term"] for row in tally] == ["classic rock"]


def test_rephrasing_needs_two_backers():
    kept, _ = consensus(
        ["guitar"],
        {"gemini": [_vote("guitar", phrasing="classic rock guitar")],
         "claude": [_vote("guitar", phrasing="blues guitar")],
         "openai": [_vote("guitar")]},
    )
    assert kept == ["guitar"]  # no rewrite reached quorum, so the term stands


def test_two_agreeing_rephrasings_win_the_term():
    kept, tally = consensus(
        ["guitar"],
        {"gemini": [_vote("guitar", phrasing="classic rock guitar")],
         "claude": [_vote("guitar", phrasing="classic rock guitar")],
         "openai": [_vote("guitar", keep=False)]},
    )
    assert kept == ["classic rock guitar"]
    assert sorted(tally[0]["rephrased_by"]) == ["claude", "gemini"]


def test_casing_ties_resolve_to_the_first_backer_in_vendor_order():
    # Same rewrite, different capitalisation: "claude" sorts before "gemini",
    # so its spelling wins. Arbitrary but deterministic.
    kept, _ = consensus(
        ["guitar"],
        {"gemini": [_vote("guitar", phrasing="Classic Rock Guitar")],
         "claude": [_vote("guitar", phrasing="classic rock guitar")]},
    )
    assert kept == ["classic rock guitar"]


def test_duplicate_votes_from_one_vendor_count_once():
    kept, tally = consensus(
        ["rock"],
        {"gemini": [_vote("rock"), _vote("rock")],
         "claude": [_vote("rock", keep=False)]},
    )
    assert kept == []
    assert tally[0]["keeps"] == ["gemini"]


def test_consensus_matches_candidates_case_insensitively():
    kept, _ = consensus(
        ["Classic Rock"],
        {"gemini": [_vote("classic rock")], "claude": [_vote("CLASSIC ROCK")]},
    )
    assert kept == ["Classic Rock"]


def test_kept_terms_keep_ballot_order():
    ballots = {v: [_vote("a"), _vote("b"), _vote("c")] for v in ("gemini", "claude")}
    kept, _ = consensus(["a", "b", "c"], ballots)
    assert kept == ["a", "b", "c"]


# --- seat failures -----------------------------------------------------------

def test_a_dead_seat_is_recorded_not_raised(monkeypatch):
    from promoter import triumvirate as tv

    def ok(system, user, model):
        return [_vote("rock")]

    def boom(system, user, model):
        raise RuntimeError("503 upstream")

    monkeypatch.setitem(tv.ADAPTERS, "gemini", ok)
    monkeypatch.setitem(tv.ADAPTERS, "claude", ok)
    monkeypatch.setitem(tv.ADAPTERS, "openai", boom)

    ballots, errors = tv.collect_ballots(
        {"name": "Stab"}, ["rock — 9/10 releases"],
        (("gemini", "m"), ("claude", "m"), ("openai", "m")),
    )
    assert set(ballots) == {"gemini", "claude"}
    assert "503 upstream" in errors["openai"]

    # Two surviving seats still reach quorum, so the run produces a keyword.
    kept, _ = consensus(["rock"], ballots)
    assert kept == ["rock"]


def test_ballot_that_is_not_json_is_a_seat_failure():
    from promoter.triumvirate import BallotError, _votes

    with pytest.raises(BallotError):
        _votes("I'd rather not answer that")
    with pytest.raises(BallotError):
        _votes('{"notes": "no votes here"}')
