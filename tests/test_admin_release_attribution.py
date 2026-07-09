"""Unit tests for the admin release-editor attribution helpers.

Covers the pure parse/resolve helpers behind the release-level `featuring`
field (Details tab) and the track-level `featuring` + `performers` editor.
"""

import yaml

from mrp.admin.routes.workspace import (
    _artist_member_slugs,
    _build_performers,
    _featuring_ref_errors,
    _parse_id_list,
    _performer_ref_errors,
)


def _write_artist(root, artist_id, members=None):
    (root / "content" / "artists").mkdir(parents=True, exist_ok=True)
    record = {"artist": {"id": artist_id, "name": artist_id.title(), "visibility": "public"}}
    if members is not None:
        record["artist"]["members"] = members
    (root / "content" / "artists" / f"{artist_id}.yaml").write_text(yaml.safe_dump(record))


def _repo(tmp_path):
    _write_artist(tmp_path, "pcbender")
    _write_artist(tmp_path, "stab")
    _write_artist(tmp_path, "4castle", members=[
        {"slug": "raven-cortez", "name": "Raven Cortez"},
        {"slug": "mack-bishop", "name": "Mack Bishop"},
    ])
    return tmp_path


# --- _parse_id_list ----------------------------------------------------------

def test_parse_id_list_splits_and_trims():
    assert _parse_id_list("stab, pcbender ,") == ["stab", "pcbender"]
    assert _parse_id_list("stab\npcbender") == ["stab", "pcbender"]
    assert _parse_id_list("") == []
    assert _parse_id_list(None) == []


# --- _build_performers -------------------------------------------------------

def test_build_performers_member_and_artist():
    performers = _build_performers(
        ["member", "artist"],
        ["raven-cortez", "pcbender"],
        ["lead vocals", "guitar"],
        ["", "cameo"],
    )
    assert performers == [
        {"member": "raven-cortez", "role": "lead vocals"},
        {"artist": "pcbender", "role": "guitar", "note": "cameo"},
    ]


def test_build_performers_skips_blank_rows():
    performers = _build_performers(["member", "member"], ["raven-cortez", ""], ["vocals", ""], ["", ""])
    assert performers == [{"member": "raven-cortez", "role": "vocals"}]


def test_build_performers_defaults_kind_to_member():
    # An unexpected/blank kind falls back to member (schema still enforces XOR).
    performers = _build_performers([""], ["raven-cortez"], ["vocals"], [""])
    assert performers == [{"member": "raven-cortez", "role": "vocals"}]


# --- _artist_member_slugs ----------------------------------------------------

def test_artist_member_slugs(tmp_path):
    repo = _repo(tmp_path)
    assert _artist_member_slugs(repo, "4castle") == {"raven-cortez", "mack-bishop"}
    assert _artist_member_slugs(repo, "pcbender") == set()   # no members
    assert _artist_member_slugs(repo, "ghost") == set()      # no record
    assert _artist_member_slugs(repo, None) == set()


# --- _featuring_ref_errors ---------------------------------------------------

def test_featuring_ref_errors(tmp_path):
    repo = _repo(tmp_path)
    assert _featuring_ref_errors(repo, "release", ["stab", "pcbender"]) == []
    errors = _featuring_ref_errors(repo, "release", ["stab", "nobody"])
    assert len(errors) == 1
    assert errors[0]["field"] == "release.featuring.1"
    assert "nobody" in errors[0]["message"]


# --- _performer_ref_errors ---------------------------------------------------

def test_performer_ref_errors_all_valid(tmp_path):
    repo = _repo(tmp_path)
    performers = [
        {"member": "raven-cortez", "role": "lead vocals"},
        {"artist": "pcbender", "role": "guitar"},
    ]
    slugs = _artist_member_slugs(repo, "4castle")
    assert _performer_ref_errors(repo, "release.song", performers, slugs, "4castle") == []


def test_performer_ref_errors_unknown_member_and_artist(tmp_path):
    repo = _repo(tmp_path)
    performers = [
        {"member": "ghost", "role": "vocals"},
        {"artist": "noone", "role": "guitar"},
    ]
    slugs = _artist_member_slugs(repo, "4castle")
    errors = _performer_ref_errors(repo, "release.song", performers, slugs, "4castle")
    fields = {e["field"] for e in errors}
    assert fields == {"release.song.performers.0.member", "release.song.performers.1.artist"}


def test_performer_member_scoped_to_owning_artist(tmp_path):
    repo = _repo(tmp_path)
    # raven-cortez is a 4castle member; a pcbender release cannot reference it.
    performers = [{"member": "raven-cortez", "role": "vocals"}]
    slugs = _artist_member_slugs(repo, "pcbender")  # empty
    errors = _performer_ref_errors(repo, "release.song", performers, slugs, "pcbender")
    assert len(errors) == 1
    assert errors[0]["field"] == "release.song.performers.0.member"
