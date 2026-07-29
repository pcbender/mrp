from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
import yaml
from pydantic import ValidationError
from starlette.requests import Request

from mrp.admin import db
from mrp.admin.routes import video as video_routes
from mrp.admin.video_timing import TimingEditorError, load_timing, save_timing
from mrp.core.migrate_site import load_structured_record
from mrp.video.project import AlignedLyricLine, LyricLine

ROOT = Path(__file__).resolve().parents[3]
ENRICHED = ROOT / "tests" / "video" / "fixtures" / "releases" / "enriched-album.yaml"


def _request(path: str, fields: list[tuple[str, str]], *, method: str = "POST") -> Request:
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
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": (
                [(b"content-type", b"application/x-www-form-urlencoded")]
                if method == "POST"
                else []
            ),
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        },
        receive,
    )


def _release() -> dict:
    return yaml.safe_load(ENRICHED.read_text(encoding="utf-8"))["release"]


def _aligned() -> dict:
    return {
        "version": 1,
        "source": "lyrics.yaml",
        "alignment": {
            "algorithm_version": 1,
            "model": "whisper-1",
            "transcription_cache_key": "transcription-key",
            "source_hash": "source-hash",
            "vocals_hash": "vocals-hash",
            "warnings": ["verse line 2 is uncertain"],
        },
        "sections": [
            {
                "id": "verse",
                "type": "verse",
                "label": "Verse 1",
                "start": 0.0,
                "end": 4.0,
                "lines": [
                    {
                        "text": "First lyric",
                        "start": 0.0,
                        "end": 1.5,
                        "confidence": 0.98,
                        "status": "matched",
                    },
                    {
                        "text": "Needs attention",
                        "start": 1.5,
                        "end": 4.0,
                        "confidence": 0.52,
                        "status": "uncertain",
                    },
                ],
            },
            {
                "id": "break",
                "type": "instrumental",
                "label": "Instrumental",
                "start": 4.0,
                "end": 6.0,
                "lines": [],
            },
        ],
    }


def _write_timing(tmp_path: Path, release: dict) -> Path:
    key = f"{release['artist_id']}--{release['tracks'][0]['slug']}"
    path = tmp_path / "assets" / "source" / "video" / key / "lyrics.aligned.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(_aligned(), sort_keys=False), encoding="utf-8")
    preflight = tmp_path / "assets" / "processed" / "video" / key / "logs" / "preflight.json"
    preflight.parent.mkdir(parents=True)
    preflight.write_text(json.dumps({"status": "passed", "master_duration": 6.0}), encoding="utf-8")
    return path


def _write_transcript(tmp_path: Path, release: dict) -> Path:
    key = f"{release['artist_id']}--{release['tracks'][0]['slug']}"
    path = (
        tmp_path
        / "assets"
        / "processed"
        / "video"
        / key
        / "analysis"
        / "cache"
        / "alignment"
        / "transcriptions"
        / "transcription-key.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "response": {
                    "text": "first lyric needs attention",
                    "segments": [
                        {"start": 0.0, "end": 1.5, "text": "first lyric"},
                        {"start": 1.5, "end": 4.0, "text": "needs attention"},
                    ],
                    "words": [
                        {"word": "first", "start": 0.0, "end": 0.7},
                        {"word": "lyric", "start": 0.7, "end": 1.5},
                        {"word": "needs", "start": 1.6, "end": 2.4},
                        {"word": "attention", "start": 2.4, "end": 4.0},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _fields(*, overlap: bool = False) -> dict[str, list[str]]:
    return {
        "section_id": ["verse", "break"],
        "section_start": ["0", "4"],
        "section_end": ["4", "6"],
        "section_reviewed": ["true", "true"],
        "line_key": ["verse:0", "verse:1"],
        "line_start": ["0", "1" if not overlap else "0.5"],
        "line_end": ["1", "4"],
        "line_reviewed": ["false", "true"],
    }


def _form_fields(fields: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(name, value) for name, values in fields.items() for value in values]


def test_review_markers_are_backward_compatible_and_structure_tags_are_not_cues():
    line = AlignedLyricLine(
        text="A real lyric",
        start=0,
        end=1,
        confidence=1,
        status="matched",
    )
    assert line.reviewed is None
    with pytest.raises(ValidationError, match="section labels"):
        LyricLine(text="[Verse]")


def test_load_timing_reports_confidence_review_and_master_duration(tmp_path: Path):
    release = _release()
    _write_timing(tmp_path, release)

    timing = load_timing(tmp_path, release, release["tracks"][0])

    assert timing["exists"] is True
    assert timing["master_duration"] == 6.0
    assert timing["summary"] == {
        "matched": 1,
        "uncertain": 1,
        "unmatched": 0,
        "sections": 2,
        "reviewed_sections": 0,
        "lines": 2,
        "reviewed_lines": 0,
        "pending_review": 1,
        "review_complete": False,
    }


def test_load_timing_exposes_the_transcript_behind_the_alignment(tmp_path: Path):
    release = _release()
    _write_timing(tmp_path, release)
    _write_transcript(tmp_path, release)

    timing = load_timing(tmp_path, release, release["tracks"][0])

    transcript = timing["transcript"]
    assert transcript is not None
    assert transcript["word_count"] == 4
    assert [segment["text"] for segment in transcript["segments"]] == [
        "first lyric",
        "needs attention",
    ]
    # Words are grouped under the segment whose span contains them.
    assert [word["text"] for word in transcript["segments"][0]["words"]] == [
        "first",
        "lyric",
    ]
    assert [word["text"] for word in transcript["segments"][1]["words"]] == [
        "needs",
        "attention",
    ]


def test_load_timing_survives_a_missing_or_unreadable_transcript(tmp_path: Path):
    release = _release()
    _write_timing(tmp_path, release)

    # No transcript on disk at all.
    assert load_timing(tmp_path, release, release["tracks"][0])["transcript"] is None

    path = _write_transcript(tmp_path, release)
    path.write_text("{not json", encoding="utf-8")
    assert load_timing(tmp_path, release, release["tracks"][0])["transcript"] is None


def test_load_timing_splits_alignment_warnings_per_line(tmp_path: Path):
    release = _release()
    path = _write_timing(tmp_path, release)
    document = _aligned()
    document["alignment"]["warnings"] = [
        "verse line 2 has no recognized audio window — the surrounding cues are "
        "adjacent, so it borrowed a 0.250s window and requires manual timing",
        "transcription returned no timestamps for 3 words",
    ]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    warnings = load_timing(tmp_path, release, release["tracks"][0])["warnings"]

    # Keyed by the zero-based line index the editor posts back as line_key.
    assert list(warnings["lines"]) == ["verse:1"]
    assert warnings["lines"]["verse:1"] == [
        "has no recognized audio window — the surrounding cues are adjacent, so it "
        "borrowed a 0.250s window and requires manual timing"
    ]
    assert warnings["general"] == ["transcription returned no timestamps for 3 words"]
    assert warnings["total"] == 2


def test_load_timing_exposes_provisional_unmatched_line_for_review(tmp_path: Path):
    release = _release()
    path = _write_timing(tmp_path, release)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    provisional = payload["sections"][0]["lines"][1]
    provisional.update(
        {
            "start": 3.5,
            "end": 4.0,
            "confidence": 0,
            "status": "unmatched",
        }
    )
    payload["alignment"]["warnings"] = [
        "verse line 2 received a provisional timing window "
        "and requires manual review"
    ]
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    timing = load_timing(tmp_path, release, release["tracks"][0])

    assert timing["exists"] is True
    assert timing["summary"]["unmatched"] == 1
    assert timing["summary"]["pending_review"] == 1
    assert timing["document"].sections[0].lines[1].start == 3.5


def test_save_timing_atomically_persists_boundaries_and_review(tmp_path: Path):
    release = _release()
    path = _write_timing(tmp_path, release)

    result = save_timing(tmp_path, release, release["tracks"][0], _fields())

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["sections"][0]["reviewed"] is True
    assert saved["sections"][0]["lines"][1]["reviewed"] is True
    assert saved["sections"][0]["lines"][1]["start"] == 1.0
    assert result["summary"]["review_complete"] is True
    assert not list(path.parent.glob(".lyrics.aligned.yaml.*.tmp"))


def test_invalid_overlap_leaves_versioned_timing_unchanged(tmp_path: Path):
    release = _release()
    path = _write_timing(tmp_path, release)
    before = path.read_text(encoding="utf-8")

    with pytest.raises(TimingEditorError, match="non-overlapping"):
        save_timing(tmp_path, release, release["tracks"][0], _fields(overlap=True))

    assert path.read_text(encoding="utf-8") == before


def test_timing_route_marks_only_selected_track_timed(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    release = _release()
    release["tracks"][0]["music_video"]["status"] = "draft"
    untouched = copy.deepcopy(release["tracks"][1])
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"release": release}, sort_keys=False), encoding="utf-8")
    _write_timing(tmp_path, release)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_timing_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                _form_fields(_fields()),
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]
    assert saved["tracks"][0]["music_video"]["status"] == "timed"
    assert saved["tracks"][1] == untouched


def _lyric_release(tmp_path: Path, *, gap: bool = False) -> tuple[dict, Path]:
    """A release whose track carries both lyric fields, 1:1 with the aligned doc.

    With gap=True the two cues leave room at 1.0-1.5s and 3.5-4.0s, so a new
    cue has somewhere to land.
    """
    release = _release()
    track = release["tracks"][0]
    track["lyrics_raw"] = "[Verse]\nFirst lyric\nNeeds attention"
    track["lyrics_text"] = "First lyric\nNeeds attention"
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"release": release}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    written = _write_timing(tmp_path, release)
    if gap:
        document = _aligned()
        document["sections"][0]["lines"][0]["end"] = 1.0
        document["sections"][0]["lines"][1]["start"] = 1.5
        document["sections"][0]["lines"][1]["end"] = 3.5
        written.write_text(
            yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
        )
    return release, path


def test_editing_a_cue_writes_the_lyric_back_to_both_fields(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    release, path = _lyric_release(tmp_path)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    fields = _fields()
    # Musixmatch wants every vocal sound in the lyric, including the oohs.
    fields["line_text"] = ["First lyric", "Needs attention, oooh"]

    response = asyncio.run(
        video_routes.video_timing_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                _form_fields(fields),
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]["tracks"][0]
    # The section marker survives; only the sung line changed.
    assert saved["lyrics_raw"] == "[Verse]\nFirst lyric\nNeeds attention, oooh"
    assert saved["lyrics_text"] == "First lyric\nNeeds attention, oooh"
    # And the aligned document the renderer reads agrees.
    document = load_timing(tmp_path, release, release["tracks"][0])["document"]
    assert document.sections[0].lines[1].text == "Needs attention, oooh"


def test_editing_the_very_first_cue_writes_back(tmp_path: Path, monkeypatch):
    """The first line maps to source offset 0, which is easy to treat as absent."""
    db.init(tmp_path / "admin.db")
    release, path = _lyric_release(tmp_path)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    assert load_timing(tmp_path, release, release["tracks"][0])["lyric_source"][
        "lines"
    ]["verse:0"] == 0

    fields = _fields()
    fields["line_text"] = ["Ooooh, first lyric", "Needs attention"]

    response = asyncio.run(
        video_routes.video_timing_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                _form_fields(fields),
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]["tracks"][0]
    assert saved["lyrics_raw"] == "[Verse]\nOoooh, first lyric\nNeeds attention"
    assert saved["lyrics_text"] == "Ooooh, first lyric\nNeeds attention"


def _add_cue(tmp_path: Path, **overrides) -> object:
    fields = {
        "section_id": "verse",
        "line_text": "Oooh",
        "line_start": "1.2",
        "line_end": "1.45",
    }
    fields.update(overrides)
    return asyncio.run(
        video_routes.video_timing_add_line(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing/line",
                list(fields.items()),
            ),
            "video-contract",
            "private-track",
        )
    )


def test_adding_a_cue_writes_it_into_the_document_and_the_lyric(
    tmp_path: Path, monkeypatch
):
    db.init(tmp_path / "admin.db")
    release, path = _lyric_release(tmp_path, gap=True)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    # Into the gap between "First lyric" (0-1.0) and "Needs attention" (1.5-3.5).
    response = _add_cue(tmp_path, line_start="1.1", line_end="1.4")

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]["tracks"][0]
    assert saved["lyrics_raw"] == "[Verse]\nFirst lyric\nOooh\nNeeds attention"
    assert saved["lyrics_text"] == "First lyric\nOooh\nNeeds attention"
    lines = load_timing(tmp_path, release, release["tracks"][0])["document"].sections[
        0
    ].lines
    assert [line.text for line in lines] == ["First lyric", "Oooh", "Needs attention"]
    # Hand-added cues are reviewed by definition and carry no aligner status.
    assert lines[1].reviewed is True
    assert lines[1].status is None


def test_a_cue_added_at_the_end_of_a_section_lands_before_the_next_marker(
    tmp_path: Path, monkeypatch
):
    db.init(tmp_path / "admin.db")
    release, path = _lyric_release(tmp_path, gap=True)
    # A second section follows, so a naive offset would insert after its marker.
    release["tracks"][0]["lyrics_raw"] = (
        "[Verse]\nFirst lyric\nNeeds attention\n[Chorus]\nHook line"
    )
    release["tracks"][0]["lyrics_text"] = "First lyric\nNeeds attention\nHook line"
    path.write_text(
        yaml.safe_dump({"release": release}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = _add_cue(tmp_path, line_start="3.6", line_end="3.9")

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]["tracks"][0]
    assert saved["lyrics_raw"] == (
        "[Verse]\nFirst lyric\nNeeds attention\nOooh\n[Chorus]\nHook line"
    )
    assert saved["lyrics_text"] == "First lyric\nNeeds attention\nOooh\nHook line"


def test_adding_a_cue_at_the_head_of_a_section_precedes_its_first_line(
    tmp_path: Path, monkeypatch
):
    db.init(tmp_path / "admin.db")
    release, path = _lyric_release(tmp_path, gap=True)
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = _add_cue(tmp_path, line_start="0.0", line_end="0.4")

    assert response.status_code == 422
    # 0-0.4 overlaps "First lyric" at 0-1.5, so it is refused rather than guessed.
    assert "overlaps" in response.body.decode()


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"line_text": "  "}, "lyric text is required"),
        ({"line_text": "[Chorus]"}, "cannot be a [section] marker"),
        ({"line_start": "3.0", "line_end": "2.0"}, "must be greater than"),
        ({"line_start": "5.5", "line_end": "5.9"}, "falls outside section"),
        ({"line_start": "0.5", "line_end": "0.9"}, "overlaps"),
        ({"section_id": "nope"}, "unknown section"),
        ({"section_id": "break"}, "no existing cue to anchor against"),
    ],
)
def test_adding_a_cue_is_refused_and_changes_nothing(
    tmp_path: Path, monkeypatch, overrides, expected
):
    db.init(tmp_path / "admin.db")
    release, path = _lyric_release(tmp_path, gap=True)
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = _add_cue(tmp_path, **overrides)

    assert response.status_code == 422
    assert expected in response.body.decode()
    assert path.read_text(encoding="utf-8") == before
    document = load_timing(tmp_path, release, release["tracks"][0])["document"]
    assert [line.text for line in document.sections[0].lines] == [
        "First lyric",
        "Needs attention",
    ]


def test_editing_a_cue_is_refused_when_the_section_does_not_map_one_to_one(
    tmp_path: Path, monkeypatch
):
    db.init(tmp_path / "admin.db")
    release, path = _lyric_release(tmp_path)
    # Display segmentation would split a line into extra cues, so the aligned
    # document no longer lines up with the source.
    release["tracks"][0]["lyrics_raw"] = "[Verse]\nFirst lyric"
    release["tracks"][0]["lyrics_text"] = "First lyric"
    path.write_text(
        yaml.safe_dump({"release": release}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    fields = _fields()
    fields["line_text"] = ["First lyric", "Rewritten"]

    response = asyncio.run(
        video_routes.video_timing_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                _form_fields(fields),
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 422
    assert "cannot be edited here" in response.body.decode()
    # Nothing was written to either artifact.
    saved = load_structured_record(path)["release"]["tracks"][0]
    assert saved["lyrics_text"] == "First lyric"
    document = load_timing(tmp_path, release, release["tracks"][0])["document"]
    assert document.sections[0].lines[1].text == "Needs attention"


def test_unchanged_lyric_text_touches_neither_the_release_nor_the_document(
    tmp_path: Path, monkeypatch
):
    db.init(tmp_path / "admin.db")
    release, path = _lyric_release(tmp_path, gap=True)
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    fields = _fields()
    fields["line_text"] = ["First lyric", "Needs attention"]

    response = asyncio.run(
        video_routes.video_timing_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                _form_fields(fields),
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 200
    saved = load_structured_record(path)["release"]["tracks"][0]
    assert saved["lyrics_raw"] == "[Verse]\nFirst lyric\nNeeds attention"
    assert saved["lyrics_text"] == "First lyric\nNeeds attention"
    # No write-back happened, so the flash does not mention lyric lines.
    assert "lyric line" not in response.body.decode()
    assert "First lyric" in before


def test_lyric_source_file_makes_text_read_only(tmp_path: Path):
    release, _ = _lyric_release(tmp_path)
    track = release["tracks"][0]
    track["lyrics_source"] = "content/lyrics/private-track.yaml"

    timing = load_timing(tmp_path, release, track)

    assert timing["lyric_source"]["editable"] is False
    assert "external lyric file" in timing["lyric_source"]["reason"]
    assert timing["lyric_source"]["lines"] == {}


def test_timing_route_rejection_does_not_partially_persist_timing(
    tmp_path: Path,
    monkeypatch,
):
    db.init(tmp_path / "admin.db")
    release = _release()
    release["tracks"][0]["music_video"]["status"] = "draft"
    release_path = tmp_path / "content" / "releases" / "video-contract.yaml"
    release_path.parent.mkdir(parents=True)
    release_path.write_text(
        yaml.safe_dump({"release": release}, sort_keys=False),
        encoding="utf-8",
    )
    timing_path = _write_timing(tmp_path, release)
    before = timing_path.read_text(encoding="utf-8")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        video_routes,
        "validate_release_dict",
        lambda _data: [
            {
                "field": "release.song.music_video.status",
                "message": "test rejection",
                "severity": "error",
            }
        ],
    )

    response = asyncio.run(
        video_routes.video_timing_save(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                _form_fields(_fields()),
            ),
            "video-contract",
            "private-track",
        )
    )

    assert response.status_code == 422
    assert "test rejection" in response.body.decode()
    assert timing_path.read_text(encoding="utf-8") == before


def test_timing_page_renders_scrubbing_boundaries_and_no_structure_cues(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    release = _release()
    master = tmp_path / "private" / "master.wav"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"audio")
    release["tracks"][0]["master_path"] = str(master)
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"release": release}, sort_keys=False), encoding="utf-8")
    timing_path = _write_timing(tmp_path, release)
    timing_payload = yaml.safe_load(timing_path.read_text(encoding="utf-8"))
    timing_payload["sections"][0]["lines"][0]["end"] = 1.590567
    timing_payload["sections"][0]["lines"][1]["start"] = 1.590567
    timing_payload["sections"][0]["lines"][1]["reviewed"] = True
    timing_path.write_text(
        yaml.safe_dump(timing_payload, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(
        video_routes.video_timing(
            _request(
                "/releases/video-contract/tracks/private-track/video/timing",
                [],
                method="GET",
            ),
            "video-contract",
            "private-track",
        )
    )
    body = response.body.decode()

    assert response.status_code == 200
    assert "Audio playhead" in body
    assert "Use playhead" in body
    assert "Needs attention" in body
    assert "52.0%" in body
    assert 'timing-status-manual">manual' in body
    assert 'step="0.001" value="1.591"' in body
    assert "1.590567" not in body
    assert "htmx:beforeSwap" in body
    assert "event.detail.shouldSwap = true" in body
    assert "[Verse]" not in body


def test_video_audio_serves_the_selected_track_master(tmp_path: Path, monkeypatch):
    db.init(tmp_path / "admin.db")
    release = _release()
    master = tmp_path / "private" / "master.wav"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"audio")
    release["tracks"][0]["master_path"] = str(master)
    path = tmp_path / "content" / "releases" / "video-contract.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"release": release}, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(video_routes, "get_repo_root", lambda: tmp_path)

    response = asyncio.run(video_routes.video_audio("video-contract", "private-track"))

    assert Path(response.path) == master
    assert response.media_type == "audio/wav"
