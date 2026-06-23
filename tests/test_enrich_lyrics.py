from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from mrp.core.enrich_lyrics import enrich_lyrics

ROOT = Path(__file__).resolve().parents[1]


def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    return repo


def reset_lyrics(path: Path) -> None:
    """Force a clean (no lyrics_text) starting state, independent of
    whatever a real enrichment run may have already written here."""
    data = yaml.safe_load(path.read_text())
    release = data["release"]
    song = release.get("song")
    if isinstance(song, dict):
        song["lyrics_text"] = None
        song["lyrics_source"] = None
    for track in release.get("tracks") or []:
        if isinstance(track, dict):
            track["lyrics_text"] = None
            track["lyrics_source"] = None
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_enrich_lyrics_backfills_a_single_track_by_title(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    reset_lyrics(path)

    docs = [{"id": "doc1", "title": "Made By Moving", "content": "[Verse]\n\nHello world, this is the song."}]
    report = enrich_lyrics(repo, docs=docs)

    assert report["summary"]["songs_or_tracks_patched"] == 1
    after = yaml.safe_load(path.read_text())["release"]
    track = next(t for t in after["tracks"] if t["slug"] == "made-by-moving")
    assert track["lyrics_text"] == "Hello world, this is the song"
    assert track["lyrics_source"] == "https://docs.google.com/document/d/doc1/edit"


def test_enrich_lyrics_never_overwrites_existing_value(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    data = yaml.safe_load(path.read_text())
    track = next(t for t in data["release"]["tracks"] if t["slug"] == "made-by-moving")
    track["lyrics_text"] = "already here"
    track["lyrics_source"] = "https://docs.google.com/document/d/already/edit"
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    docs = [{"id": "doc1", "title": "Made By Moving", "content": "[Verse]\n\nNew text that should not land."}]
    report = enrich_lyrics(repo, docs=docs)

    assert report["summary"]["skipped_already_set"] == 1
    after = yaml.safe_load(path.read_text())["release"]
    after_track = next(t for t in after["tracks"] if t["slug"] == "made-by-moving")
    assert after_track["lyrics_text"] == "already here"


def test_enrich_lyrics_applies_one_doc_to_multiple_matching_targets(tmp_path):
    repo = content_repo(tmp_path)
    made_by_moving = repo / "content/releases/made-by-moving.yaml"
    winds_of_change = repo / "content/releases/winds-of-change.yaml"
    reset_lyrics(made_by_moving)
    reset_lyrics(winds_of_change)

    # Same normalized title ("Joni") appears as a track in both fixtures
    # once we relabel one -- simulate the real "shared lyrics across a
    # single and a compilation track" pattern with two distinct titles
    # that happen to collide.
    data = yaml.safe_load(made_by_moving.read_text())
    data["release"]["tracks"][0]["title"] = "Shared Title"
    data["release"]["tracks"][0]["slug"] = "shared-title"
    made_by_moving.write_text(yaml.safe_dump(data, sort_keys=False))

    data2 = yaml.safe_load(winds_of_change.read_text())
    data2["release"]["tracks"][0]["title"] = "Shared Title"
    data2["release"]["tracks"][0]["slug"] = "shared-title"
    winds_of_change.write_text(yaml.safe_dump(data2, sort_keys=False))

    docs = [{"id": "doc1", "title": "Shared Title", "content": "[Verse]\n\nOne lyric, two homes."}]
    report = enrich_lyrics(repo, docs=docs)

    assert report["summary"]["docs_applied_to_multiple_targets"] == 1
    assert report["summary"]["songs_or_tracks_patched"] == 2
    for path in (made_by_moving, winds_of_change):
        after = yaml.safe_load(path.read_text())["release"]
        assert after["tracks"][0]["lyrics_text"] == "One lyric, two homes"


def test_enrich_lyrics_reports_unmatched_doc(tmp_path):
    repo = content_repo(tmp_path)
    docs = [{"id": "doc1", "title": "Some Cut Song Nobody Released", "content": "[Verse]\n\nNever made the album."}]
    report = enrich_lyrics(repo, docs=docs)

    assert report["unmatched_docs"] == [{"id": "doc1", "title": "Some Cut Song Nobody Released"}]


def test_enrich_lyrics_reports_unmatched_songs_and_tracks(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    reset_lyrics(path)

    report = enrich_lyrics(repo, docs=[])

    unmatched_slugs = {u["slug"] for u in report["unmatched_songs_or_tracks"]}
    assert "made-by-moving" in unmatched_slugs


def test_enrich_lyrics_skips_non_lyric_reference_docs(tmp_path):
    repo = content_repo(tmp_path)
    docs = [{"id": "doc1", "title": "Suno Template", "content": "not a song"}]
    report = enrich_lyrics(repo, docs=docs)

    assert report["summary"]["skipped_non_lyric_doc"] == 1
    assert report["unmatched_docs"] == []


def test_enrich_lyrics_dry_run_does_not_write(tmp_path):
    repo = content_repo(tmp_path)
    path = repo / "content/releases/made-by-moving.yaml"
    reset_lyrics(path)
    before_text = path.read_text()

    docs = [{"id": "doc1", "title": "Made By Moving", "content": "[Verse]\n\nHello world, this is the song."}]
    report = enrich_lyrics(repo, docs=docs, dry_run=True)

    assert report["summary"]["songs_or_tracks_patched"] == 1
    assert path.read_text() == before_text
    assert "report_path" not in report
