from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from mrp.core.migrate_site import load_structured_record, serialize_structured_record
from mrp.core.release import release_record
from mrp.core.validate import validate_repository


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "mrp" / "schemas" / "release.schema.json"
ENRICHED = ROOT / "tests" / "video" / "fixtures" / "releases" / "enriched-album.yaml"
ENRICHED_SINGLE = ROOT / "tests" / "video" / "fixtures" / "releases" / "enriched-single.yaml"
LEGACY_FIXTURES = [
    ROOT / "tests" / "fixtures" / "content" / "valid" / "release-song.yaml",
    ROOT / "tests" / "fixtures" / "content" / "valid" / "release-album.yaml",
]


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _errors(record: dict) -> list:
    return list(_validator().iter_errors(record))


@pytest.mark.parametrize("fixture", LEGACY_FIXTURES, ids=["song", "album"])
def test_legacy_release_shapes_validate_without_backfill(fixture: Path):
    record = _load(fixture)

    assert _errors(record) == []
    tracks = [record["release"].get("song"), *(record["release"].get("tracks") or [])]
    for track in filter(None, tracks):
        assert "stems" not in track
        assert "music_video" not in track


@pytest.mark.parametrize("fixture", [ENRICHED_SINGLE, ENRICHED], ids=["single", "album"])
def test_enriched_release_shapes_validate(fixture: Path):
    assert _errors(_load(fixture)) == []


def test_single_and_multi_track_release_containers_are_exclusive():
    single = _load(LEGACY_FIXTURES[0])
    single["release"]["tracks"] = [
        copy.deepcopy(single["release"]["song"]),
        copy.deepcopy(single["release"]["song"]),
    ]
    album = _load(LEGACY_FIXTURES[1])
    album["release"]["song"] = copy.deepcopy(album["release"]["tracks"][0])

    assert _errors(single)
    assert _errors(album)


@pytest.mark.parametrize("release_type", ["ep", "album"])
def test_ep_and_album_require_more_than_one_track(release_type: str):
    record = _load(LEGACY_FIXTURES[1])
    record["release"]["release_type"] = release_type
    record["release"]["tracks"] = record["release"]["tracks"][:1]

    assert any("is too short" in error.message for error in _errors(record))


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        (lambda stem, video: stem.update(role="strings"), "is not one of"),
        (lambda stem, video: stem.pop("path"), "is a required property"),
        (lambda stem, video: video.update(project="/private/project.yaml"), "does not match"),
        (lambda stem, video: video.update(public_url="assets/processed/video/render.mp4"), "is not valid"),
        (lambda stem, video: video.update(public_url="/assets/processed/video/render.mp4"), "is not valid"),
        (lambda stem, video: video.update(status="processing"), "is not one of"),
        (lambda stem, video: video.update(opt_in="yes"), "is not of type"),
    ],
)
def test_enriched_contract_rejects_invalid_private_state(mutation, expected_fragment: str):
    record = _load(ENRICHED)
    track = record["release"]["tracks"][0]
    mutation(track["stems"][0], track["music_video"])

    messages = [error.message for error in _errors(record)]

    assert any(expected_fragment in message for message in messages), messages


@pytest.mark.parametrize("release_type", ["single", "ep", "album"])
def test_release_creation_remains_valid_without_video_backfill(release_type: str):
    record = release_record("pcbender", "No Backfill", "no-backfill", release_type)

    assert _errors(record) == []
    release = record["release"]
    tracks = [release.get("song"), *(release.get("tracks") or [])]
    for track in filter(None, tracks):
        assert "stems" not in track
        assert "music_video" not in track
    if release_type == "single":
        assert isinstance(release.get("song"), dict)
        assert "tracks" not in release
    else:
        assert len(release["tracks"]) >= 2
        assert "song" not in release


def test_public_video_requires_explicit_opt_in_and_published_public_media():
    record = _load(ENRICHED)
    video = record["release"]["tracks"][0]["music_video"]
    video["opt_in"] = True

    assert any("published" in error.message for error in _errors(record))

    video.update(
        status="published",
        public_url="/media/music-videos/pcbender--private-track/video.mp4",
        poster="/media/music-videos/pcbender--private-track/poster.jpg",
    )
    assert _errors(record) == []

    video["opt_in"] = False
    assert _errors(record) == []

    video.pop("opt_in")
    assert _errors(record) == []


@pytest.mark.parametrize("fixture", [ENRICHED_SINGLE, ENRICHED], ids=["single", "album"])
def test_enriched_fields_survive_yaml_serialization_round_trip(tmp_path: Path, fixture: Path):
    source = _load(fixture)
    path = tmp_path / fixture.name

    path.write_text(serialize_structured_record(path, source), encoding="utf-8")
    restored = load_structured_record(path)

    original_release = source["release"]
    restored_release = restored["release"]
    original_track = original_release.get("song") or original_release["tracks"][0]
    restored_track = restored_release.get("song") or restored_release["tracks"][0]
    assert restored_track["stems"] == original_track["stems"]
    assert restored_track["music_video"] == original_track["music_video"]


def test_repository_validation_rejects_duplicate_stem_ids(tmp_path: Path):
    record = _load(ENRICHED)
    track = record["release"]["tracks"][0]
    duplicate = copy.deepcopy(track["stems"][0])
    duplicate["path"] = "/private/video-contract/second-vocal.wav"
    track["stems"].append(duplicate)

    content = tmp_path / "content"
    (content / "artists").mkdir(parents=True)
    (content / "releases").mkdir(parents=True)
    (content / "site.yaml").write_text(
        (ROOT / "tests" / "fixtures" / "content" / "valid" / "site.yaml").read_text(),
        encoding="utf-8",
    )
    (content / "artists" / "pcbender.yaml").write_text(
        (ROOT / "tests" / "fixtures" / "content" / "valid" / "artist.yaml").read_text(),
        encoding="utf-8",
    )
    (content / "releases" / "video-contract.yaml").write_text(
        yaml.safe_dump(record, sort_keys=False), encoding="utf-8"
    )

    result = validate_repository(tmp_path)

    assert result["status"] == "failed"
    duplicate_errors = [
        error for error in result["errors"]
        if error["field"] == "release.tracks.0.stems.2.id"
    ]
    assert len(duplicate_errors) == 1
    assert "Duplicate stem id" in duplicate_errors[0]["message"]
