from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from urllib.parse import urlencode

import yaml
from starlette.requests import Request

from mrp.admin.routes.releases import _new_release_skeleton
from mrp.admin.routes import workspace as workspace_routes
from mrp.admin.workspace import validate_release_dict
from mrp.core.migrate_site import load_structured_record


ROOT = Path(__file__).resolve().parents[3]
ENRICHED = ROOT / "tests" / "video" / "fixtures" / "releases" / "enriched-album.yaml"


def _request(path: str, fields: list[tuple[str, str]]) -> Request:
    body = urlencode(fields).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        },
        receive,
    )


def _record() -> dict:
    return yaml.safe_load(ENRICHED.read_text(encoding="utf-8"))


def test_track_slice_save_preserves_stems_and_music_video(tmp_path: Path, monkeypatch):
    record = _record()
    original_track = copy.deepcopy(record["release"]["tracks"][0])
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(workspace_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        workspace_routes.track_save(
            _request(
                "/releases/video-contract/tracks/private-track",
                [
                    ("track_title", "Private Track, Edited"),
                    ("track_slug", "private-track"),
                ],
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]["tracks"][0]
    assert saved["title"] == "Private Track, Edited"
    assert saved["stems"] == original_track["stems"]
    assert saved["music_video"] == original_track["music_video"]


def test_admin_validation_rejects_duplicate_stem_ids():
    record = _record()
    duplicate = copy.deepcopy(record["release"]["tracks"][0]["stems"][0])
    duplicate["path"] = "/private/video-contract/duplicate.wav"
    record["release"]["tracks"][0]["stems"].append(duplicate)

    errors = validate_release_dict(record)

    assert any(
        error["field"] == "release.tracks.0.stems.2.id"
        and "Duplicate stem id" in error["message"]
        for error in errors
    )


def test_admin_release_skeletons_match_single_and_multi_track_cardinality():
    single = _new_release_skeleton("one", "One", "pcbender", "song", "single")
    ep = _new_release_skeleton("two", "Two", "pcbender", "album", "ep")
    album = _new_release_skeleton("many", "Many", "pcbender", "album", "album")

    assert isinstance(single.get("song"), dict)
    assert "tracks" not in single
    for release in (ep, album):
        assert "song" not in release
        assert [track["slug"] for track in release["tracks"]] == ["track-1", "track-2"]
        assert validate_release_dict({"release": release}) == []


def _save_lyrics(tmp_path: Path, monkeypatch, *, raw: str, text: str):
    record = _record()
    track = record["release"]["tracks"][0]
    track["lyrics_raw"] = "[Verse]\nOld words"
    track["lyrics_text"] = "Old words"
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(workspace_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        workspace_routes.track_save(
            _request(
                "/releases/video-contract/tracks/private-track",
                [
                    ("track_title", "Private Track"),
                    ("track_slug", "private-track"),
                    ("track_lyrics_raw", raw),
                    ("track_lyrics_text", text),
                ],
            ),
            "video-contract",
            "private-track",
        )
    )
    assert response.status_code == 200
    return load_structured_record(path)["release"]["tracks"][0]


def test_editing_only_the_raw_lyric_rederives_the_published_one(tmp_path, monkeypatch):
    """The two fields post independently, so a corrected take used to leave the
    public pages showing the old words."""
    saved = _save_lyrics(
        tmp_path,
        monkeypatch,
        raw="[Verse 1]\n[breathy male vocals]\nNew words\nSecond line",
        text="Old words",
    )

    assert saved["lyrics_raw"] == "[Verse 1]\n[breathy male vocals]\nNew words\nSecond line"
    # Structure tags and generator directions alike are stripped from the
    # published lyric.
    assert saved["lyrics_text"] == "New words\nSecond line"


def test_an_explicit_published_lyric_edit_is_not_overwritten(tmp_path, monkeypatch):
    saved = _save_lyrics(
        tmp_path,
        monkeypatch,
        raw="[Verse]\nNew words",
        text="Hand written, oooh",
    )

    assert saved["lyrics_text"] == "Hand written, oooh"


def test_leaving_both_lyric_fields_alone_changes_neither(tmp_path, monkeypatch):
    saved = _save_lyrics(
        tmp_path, monkeypatch, raw="[Verse]\nOld words", text="Old words"
    )

    assert saved["lyrics_raw"] == "[Verse]\nOld words"
    assert saved["lyrics_text"] == "Old words"


def test_section_tags_round_trip_through_the_track_editor(tmp_path, monkeypatch):
    """A one-off structure name the shared vocabulary should not have to carry."""
    record = _record()
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(workspace_routes, "get_repo_root", lambda: tmp_path)

    def _save(value: str) -> dict:
        response = asyncio.run(
            workspace_routes.track_save(
                _request(
                    "/releases/video-contract/tracks/private-track",
                    [
                        ("track_title", "Private Track"),
                        ("track_slug", "private-track"),
                        ("track_section_tags", value),
                    ],
                ),
                "video-contract",
                "private-track",
            )
        )
        assert response.status_code == 200
        return load_structured_record(path)["release"]["tracks"][0]

    saved = _save("Chant,  Whisper   Break ")
    assert saved["section_tags"] == ["Chant", "Whisper Break"]
    assert not validate_release_dict(load_structured_record(path))

    # Clearing the field drops the key rather than storing an empty list.
    assert "section_tags" not in _save("")


def test_a_declared_section_tag_opens_a_section_in_the_video_lyrics(tmp_path):
    from mrp.video.workspace import _lyrics_from_text, track_structure_labels

    track = {"section_tags": ["Chant"], "lyrics_raw": "[Chant]\nHey\n[Chorus]\nHook"}
    lyrics, directions = _lyrics_from_text(
        track["lyrics_raw"],
        instrumental=False,
        extra_labels=track_structure_labels(track),
    )

    assert [section.id for section in lyrics.sections] == ["chant", "chorus"]
    assert directions == ()
