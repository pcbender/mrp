"""Artist-level identity fields (likeness_notes, reference_image) —
schema, save round-trip, and reference-image storage."""

import asyncio
from pathlib import Path

from mrp.admin.routes.artists import (
    _SCHEMA_PATH,
    _TEXT_FIELDS,
    _store_reference_image,
)
from mrp.core.validate import validate_schema


class _FakeUpload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


def _record(**extra):
    return {"artist": {"id": "stab", "name": "STAB", "visibility": "public", **extra}}


def test_schema_accepts_artist_likeness_notes(tmp_path):
    record = _record(likeness_notes="80s pop-rock frontwoman; same face every render.")
    assert validate_schema(tmp_path / "stab.yaml", record, _SCHEMA_PATH) == []


def test_schema_accepts_null_likeness_notes(tmp_path):
    assert validate_schema(tmp_path / "stab.yaml", _record(likeness_notes=None), _SCHEMA_PATH) == []


def test_schema_still_rejects_unknown_fields(tmp_path):
    errors = validate_schema(tmp_path / "stab.yaml", _record(likeness="nope"), _SCHEMA_PATH)
    assert errors


def test_schema_accepts_reference_image(tmp_path):
    record = _record(reference_image="assets/artists/stab/reference.jpg")
    assert validate_schema(tmp_path / "stab.yaml", record, _SCHEMA_PATH) == []


def test_schema_accepts_member_reference_image(tmp_path):
    record = _record(members=[{
        "slug": "raven-cortez", "name": "Raven Cortez",
        "reference_image": "assets/artists/4castle/members/raven-cortez.jpg",
    }])
    assert validate_schema(tmp_path / "4castle.yaml", record, _SCHEMA_PATH) == []


def test_identity_fields_are_saved_text_fields():
    # artist_save() round-trips exactly the fields in _TEXT_FIELDS.
    assert "likeness_notes" in _TEXT_FIELDS
    assert "reference_image" in _TEXT_FIELDS


def test_store_reference_image_lands_in_git_assets(tmp_path):
    upload = _FakeUpload("Base.JPEG", b"refbytes")
    path, err = asyncio.run(_store_reference_image(tmp_path, "stab", upload))
    assert err is None
    assert path == "assets/artists/stab/reference.jpg"
    dest = tmp_path / "assets/artists/stab/reference.jpg"
    assert dest.read_bytes() == b"refbytes"
    # Never anywhere under the published site tree.
    assert not (tmp_path / "site").exists()


def test_store_reference_image_replaces_other_extension(tmp_path):
    asyncio.run(_store_reference_image(tmp_path, "stab", _FakeUpload("a.png", b"1")))
    asyncio.run(_store_reference_image(tmp_path, "stab", _FakeUpload("b.webp", b"2")))
    d = tmp_path / "assets/artists/stab"
    assert not (d / "reference.png").exists()
    assert (d / "reference.webp").read_bytes() == b"2"


def test_store_reference_image_rejects_unsupported_ext(tmp_path):
    path, err = asyncio.run(_store_reference_image(tmp_path, "stab", _FakeUpload("x.txt", b"z")))
    assert path is None
    assert "Unsupported" in err
