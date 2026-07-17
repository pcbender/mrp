"""Artist-level identity fields (likeness_notes) — schema + save round-trip."""

from pathlib import Path

from mrp.admin.routes.artists import _SCHEMA_PATH, _TEXT_FIELDS
from mrp.core.validate import validate_schema


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


def test_likeness_notes_is_a_saved_text_field():
    # artist_save() round-trips exactly the fields in _TEXT_FIELDS.
    assert "likeness_notes" in _TEXT_FIELDS
