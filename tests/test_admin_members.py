"""Unit tests for the admin band-members editor helpers.

The admin routes are HTMX form handlers; these cover the pure form-parsing,
row-summary, and duplicate-slug logic without needing a live server.
"""

import asyncio
from pathlib import Path

from mrp.admin.routes.artists import (
    _duplicate_slug_error,
    _member_from_form,
    _member_rows,
    _store_identity_image,
    _store_member_reference_image,
)


class _FakeUpload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


def test_member_from_form_parses_roles_and_status():
    member = _member_from_form({
        "member_name": "Raven Cortez",
        "member_slug": "raven-cortez",
        "member_roles": "lead guitar, vocals ,",
        "member_status": "guest",
        "member_display_order": "2",
        "member_bio": "P1.\n\nP2.",
    })
    assert member["slug"] == "raven-cortez"
    assert member["roles"] == ["lead guitar", "vocals"]  # blank trailing dropped
    assert member["status"] == "guest"
    assert member["display_order"] == 2
    assert member["bio"] == "P1.\n\nP2."


def test_member_from_form_derives_slug_from_name():
    member = _member_from_form({"member_name": "Mack Bishop", "member_slug": ""})
    assert member["slug"] == "mack-bishop"


def test_member_from_form_blanks_become_none():
    member = _member_from_form({"member_name": "X", "member_slug": "x",
                                "member_image": "  ", "member_likeness_notes": ""})
    assert member["image"] is None
    assert member["likeness_notes"] is None
    assert member["roles"] == []


def test_member_from_form_invalid_status_and_order_are_none():
    member = _member_from_form({"member_name": "X", "member_slug": "x",
                                "member_status": "bogus", "member_display_order": "abc"})
    assert member["status"] is None
    assert member["display_order"] is None


def test_member_rows_sort_by_display_order_then_name():
    rows = _member_rows([
        {"slug": "b", "name": "Bravo", "display_order": 2},
        {"slug": "a", "name": "Alpha", "display_order": 1},
        {"slug": "z", "name": "Zeta"},  # no order -> last
    ])
    assert [r["slug"] for r in rows] == ["a", "b", "z"]


def test_member_rows_completeness_flags():
    (row,) = _member_rows([{
        "slug": "raven", "name": "Raven", "roles": ["vocals"],
        "bio": "hi", "image": None, "likeness_notes": None,
    }])
    assert row["has_roles"] is True
    assert row["has_bio"] is True
    assert row["has_image"] is False
    assert row["has_likeness"] is False
    assert row["status"] == "current"  # default when unset


def test_duplicate_slug_error_detects_collision():
    members = [{"slug": "raven"}, {"slug": "mack"}]
    assert _duplicate_slug_error(Path("a.yaml"), members, "raven")
    assert _duplicate_slug_error(Path("a.yaml"), members, "new") == []


def test_duplicate_slug_error_ignores_self_index():
    members = [{"slug": "raven"}, {"slug": "mack"}]
    # editing index 0, keeping its own slug -> not a collision
    assert _duplicate_slug_error(Path("a.yaml"), members, "raven", ignore_index=0) == []
    # editing index 1 but renaming onto raven -> collision
    assert _duplicate_slug_error(Path("a.yaml"), members, "raven", ignore_index=1)


def test_store_identity_image_saves_and_normalizes_ext(tmp_path):
    upload = _FakeUpload("Portrait.JPEG", b"imgbytes")
    path, err = asyncio.run(_store_identity_image(tmp_path, "4castle", "raven-cortez", upload))
    assert err is None
    assert path == "/assets/artists/4castle/raven-cortez.jpg"
    dest = tmp_path / "site/public/assets/artists/4castle/raven-cortez.jpg"
    assert dest.read_bytes() == b"imgbytes"


def test_store_identity_image_rejects_unsupported_ext(tmp_path):
    path, err = asyncio.run(_store_identity_image(tmp_path, "4castle", "x", _FakeUpload("x.txt", b"z")))
    assert path is None
    assert "Unsupported" in err


def test_store_identity_image_rejects_empty(tmp_path):
    path, err = asyncio.run(_store_identity_image(tmp_path, "4castle", "x", _FakeUpload("x.png", b"")))
    assert path is None
    assert "Empty" in err


def test_store_identity_image_replaces_other_extension(tmp_path):
    asyncio.run(_store_identity_image(tmp_path, "4castle", "x", _FakeUpload("a.png", b"1")))
    asyncio.run(_store_identity_image(tmp_path, "4castle", "x", _FakeUpload("a.webp", b"2")))
    d = tmp_path / "site/public/assets/artists/4castle"
    assert not (d / "x.png").exists()
    assert (d / "x.webp").read_bytes() == b"2"


def test_member_from_form_parses_reference_image():
    member = _member_from_form({"member_name": "X", "member_slug": "x",
                                "member_reference_image": "assets/artists/b/members/x.jpg"})
    assert member["reference_image"] == "assets/artists/b/members/x.jpg"
    blank = _member_from_form({"member_name": "X", "member_slug": "x",
                               "member_reference_image": "  "})
    assert blank["reference_image"] is None


def test_store_member_reference_image_lands_in_members_subdir(tmp_path):
    path, err = asyncio.run(
        _store_member_reference_image(tmp_path, "4castle", "raven-cortez",
                                      _FakeUpload("base.JPEG", b"ref")))
    assert err is None
    assert path == "assets/artists/4castle/members/raven-cortez.jpg"
    dest = tmp_path / "assets/artists/4castle/members/raven-cortez.jpg"
    assert dest.read_bytes() == b"ref"
    # Clear of the artist's own reference.* and the published site tree.
    assert not (tmp_path / "assets/artists/4castle/reference.jpg").exists()
    assert not (tmp_path / "site").exists()
