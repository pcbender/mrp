import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import yaml
from PIL import Image
from typer.testing import CliRunner

from mrp.video.cli import app
from mrp.video.project import load_project_manifest
from mrp.video.workspace import (
    MRPVideoAdapterError,
    align_track,
    analyze_track,
    contact_sheet_track,
    prepare_track,
    preview_track,
    render_track,
)
from tests.video.engine.test_alignment import FONT_PATH, _FakeOpenAI, _response

runner = CliRunner()


def _signal(sample_rate: int, duration: float, amplitude: float = 0.2) -> np.ndarray:
    times = np.arange(round(sample_rate * duration)) / sample_rate
    return np.asarray(
        amplitude * np.sin(2 * np.pi * 220 * times),
        dtype=np.float32,
    )


def _write_repo(
    root: Path,
    *,
    stems: list[dict[str, object]] | None = None,
) -> tuple[Path, Path]:
    repo = root / "repo"
    releases = repo / "content" / "releases"
    releases.mkdir(parents=True)
    audio = root / "private-audio"
    audio.mkdir(exist_ok=True)
    master = audio / "master.wav"
    sf.write(master, _signal(8000, 2), 8000)
    cover = repo / "site" / "public" / "assets" / "fixture-cover.jpg"
    cover.parent.mkdir(parents=True)
    Image.new("RGB", (320, 180), (32, 48, 64)).save(cover, quality=95)
    document = {
        "release": {
            "id": "fixture-release",
            "slug": "fixture-release",
            "title": "Fixture Release",
            "artist_id": "fixture-artist",
            "model": "song",
            "release_type": "single",
            "status": "draft",
            "release_date": "2026-07-20",
            "cover_image": "site/public/assets/fixture-cover.jpg",
            "seo": {"title": "Fixture", "description": "Fixture"},
            "song": {
                "number": 1,
                "title": "Fixture Track",
                "slug": "fixture-track",
                "explicit": False,
                "instrumental": False,
                "master_path": str(master),
                "lyrics_raw": (
                    "[Verse | restrained]\n"
                    "A generated fixture\n"
                    "Second line\n"
                    "[Instrumental]\n"
                ),
            },
        }
    }
    if stems is not None:
        document["release"]["song"]["stems"] = stems
    release_path = releases / "fixture-release.yaml"
    release_path.write_text(
        yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )
    return repo, master


def _stem(
    root: Path,
    stem_id: str,
    role: str,
    amplitude: float,
    *,
    sample_rate: int = 8000,
) -> dict[str, object]:
    path = root / "private-audio" / f"{stem_id}.wav"
    path.parent.mkdir(exist_ok=True)
    sf.write(path, _signal(sample_rate, 2, amplitude), sample_rate)
    return {
        "id": stem_id,
        "label": stem_id.replace("-", " ").title(),
        "role": role,
        "path": str(path),
        "enabled": True,
    }


def test_prepare_master_only_track_uses_symbolic_tracked_project(tmp_path: Path) -> None:
    repo, master = _write_repo(tmp_path)

    prepared = prepare_track(
        repo,
        "fixture-release",
        font_path=FONT_PATH,
    )

    assert prepared.track_key == "fixture-artist--fixture-track"
    assert prepared.aggregation == {}
    assert prepared.stem_durations == {}
    assert prepared.workspace.project_path.is_file()
    assert prepared.workspace.runtime_manifest_path.is_file()
    source_text = prepared.workspace.project_path.read_text(encoding="utf-8")
    assert "@mrp/master" in source_text
    assert str(master) not in source_text
    assert "[Verse" not in prepared.workspace.runtime_lyrics_path.read_text(
        encoding="utf-8"
    )
    runtime = load_project_manifest(prepared.runtime_manifest_path)
    assert runtime.audio.stems == {}
    assert (prepared.runtime_manifest_path.parent / runtime.audio.master).resolve() == master
    release = yaml.safe_load(
        (repo / "content" / "releases" / "fixture-release.yaml").read_text(
            encoding="utf-8"
        )
    )
    video = release["release"]["song"]["music_video"]
    assert video == {
        "project": "assets/source/video/fixture-artist--fixture-track/project.yaml",
        "status": "draft",
    }
    assert json.loads(prepared.workspace.preflight_path.read_text())["status"] == "passed"


def test_prepare_resolves_and_fingerprints_background_images(tmp_path: Path) -> None:
    repo, _master = _write_repo(tmp_path)
    first = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    project_path = first.workspace.project_path
    custom = project_path.parent / "backgrounds" / "verse.png"
    custom.parent.mkdir()
    Image.new("RGB", (64, 64), (90, 20, 120)).save(custom)
    value = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    value["project"]["video"]["background"] = {
        "color": "#101014",
        "image": "@mrp/cover",
    }
    value["project"]["visuals"]["background_overrides"] = {
        "verse_1": {"color": "#050505", "image": "backgrounds/verse.png"}
    }
    project_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    prepared = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    runtime = load_project_manifest(prepared.runtime_manifest_path)
    runtime_root = prepared.runtime_manifest_path.parent

    assert (runtime_root / runtime.video.background.image).resolve() == (
        repo / "site" / "public" / "assets" / "fixture-cover.jpg"
    )
    override = runtime.visuals.background_overrides["verse_1"]
    assert (runtime_root / override.image).resolve() == custom
    assert "video.background.image" in prepared.input_hashes
    assert "visuals.background_overrides.verse_1.image" in prepared.input_hashes

    original_fingerprint = prepared.input_fingerprint
    Image.new("RGB", (64, 64), (20, 90, 120)).save(custom)
    changed = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    assert changed.input_fingerprint != original_fingerprint


def test_multi_stem_roles_are_aggregated_deterministically_and_go_stale(
    tmp_path: Path,
) -> None:
    stems = [
        _stem(tmp_path, "guitar-right", "instruments", 0.2),
        _stem(tmp_path, "keys", "other", 0.4),
        _stem(tmp_path, "guitar-left", "instruments", 0.6),
        _stem(tmp_path, "lead-vocal", "vocals", 0.3, sample_rate=16000),
    ]
    repo, master = _write_repo(tmp_path, stems=stems)

    first = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    runtime = load_project_manifest(first.runtime_manifest_path)
    assert list(runtime.audio.stems) == ["instruments", "vocals"]
    assert first.aggregation == {
        "instruments": ("guitar-left", "guitar-right", "keys"),
        "vocals": ("lead-vocal",),
    }
    aggregate_path = (
        first.runtime_manifest_path.parent / runtime.audio.stems["instruments"]
    ).resolve()
    assert first.workspace.analysis_dir in aggregate_path.parents
    aggregate, _sample_rate = sf.read(aggregate_path, dtype="float32")
    expected = _signal(8000, 2, 0.4)
    assert np.max(np.abs(aggregate - expected)) < 0.002

    release_path = repo / "content" / "releases" / "fixture-release.yaml"
    release = yaml.safe_load(release_path.read_text(encoding="utf-8"))
    release["release"]["song"]["stems"].reverse()
    release_path.write_text(yaml.safe_dump(release, sort_keys=False), encoding="utf-8")
    reordered = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    reordered_runtime = load_project_manifest(reordered.runtime_manifest_path)
    reordered_aggregate = (
        reordered.runtime_manifest_path.parent
        / reordered_runtime.audio.stems["instruments"]
    ).resolve()
    assert reordered_aggregate == aggregate_path
    assert reordered.input_fingerprint == first.input_fingerprint

    analysis = analyze_track(repo, "fixture-release", font_path=FONT_PATH)
    assert set(analysis["analysis"]["tracks"]) == {
        "master",
        "instruments",
        "vocals",
    }
    sf.write(master, _signal(8000, 2, 0.35), 8000)
    changed = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    assert changed.input_fingerprint != first.input_fingerprint
    assert [artifact["kind"] for artifact in changed.stale_artifacts] == [
        "analysis"
    ]


def test_track_cli_prepares_release_owned_artifacts(tmp_path: Path) -> None:
    repo, _master = _write_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "track",
            "prepare",
            "fixture-release",
            "--repo",
            str(repo),
            "--font",
            str(FONT_PATH),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["track_key"] == "fixture-artist--fixture-track"
    assert payload["project"].endswith("/project.yaml")
    help_result = runner.invoke(app, ["track", "--help"])
    assert help_result.exit_code == 0
    for command in ("prepare", "preflight", "analyze", "align", "preview", "render"):
        assert command in help_result.stdout


def test_album_adapter_updates_only_the_selected_track(tmp_path: Path) -> None:
    repo, _master = _write_repo(tmp_path)
    release_path = repo / "content" / "releases" / "fixture-release.yaml"
    document = yaml.safe_load(release_path.read_text(encoding="utf-8"))
    release = document["release"]
    selected = release.pop("song")
    release["model"] = "album"
    release["release_type"] = "album"
    release["tracks"] = [
        selected,
        {
            "number": 2,
            "title": "Other Track",
            "slug": "other-track",
            "explicit": False,
            "instrumental": True,
        },
    ]
    release_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    with pytest.raises(MRPVideoAdapterError, match="--track is required"):
        prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    prepared = prepare_track(
        repo,
        "fixture-release",
        "fixture-track",
        font_path=FONT_PATH,
    )

    assert prepared.track_key == "fixture-artist--fixture-track"
    saved = yaml.safe_load(release_path.read_text(encoding="utf-8"))["release"]
    assert "music_video" in saved["tracks"][0]
    assert "music_video" not in saved["tracks"][1]


def test_failed_duration_preflight_does_not_link_release(tmp_path: Path) -> None:
    stem = _stem(tmp_path, "short-vocal", "vocals", 0.2)
    sf.write(Path(str(stem["path"])), _signal(8000, 1, 0.2), 8000)
    repo, _master = _write_repo(tmp_path, stems=[stem])

    with pytest.raises(MRPVideoAdapterError, match="duration differs"):
        prepare_track(repo, "fixture-release", font_path=FONT_PATH)

    release = yaml.safe_load(
        (repo / "content" / "releases" / "fixture-release.yaml").read_text()
    )
    assert "music_video" not in release["release"]["song"]


def test_full_render_rejects_inputs_changed_after_preflight(tmp_path: Path) -> None:
    repo, _master = _write_repo(tmp_path)
    prepared = prepare_track(repo, "fixture-release", font_path=FONT_PATH)

    with pytest.raises(MRPVideoAdapterError, match="inputs changed"):
        render_track(
            repo,
            "fixture-release",
            font_path=FONT_PATH,
            dry_run=True,
            expected_fingerprint=f"{prepared.input_fingerprint}-stale",
        )


@pytest.mark.video_ffmpeg
def test_track_alignment_preview_and_render_use_mrp_artifact_paths(
    tmp_path: Path,
) -> None:
    stems = [_stem(tmp_path, "lead-vocal", "vocals", 0.2, sample_rate=16000)]
    repo, _master = _write_repo(tmp_path, stems=stems)
    client = _FakeOpenAI(_response())

    aligned = align_track(
        repo,
        "fixture-release",
        font_path=FONT_PATH,
        client=client,
    )
    aligned_path = repo / aligned["preflight"]["aligned_lyrics"]
    assert aligned_path.is_file()
    preview = preview_track(
        repo,
        "fixture-release",
        font_path=FONT_PATH,
        time_seconds=0.25,
        force=True,
    )
    preview_path = Path(preview["preview"]["output_path"])
    assert preview_path.is_file()
    assert "assets/processed/video/fixture-artist--fixture-track/previews" in str(
        preview_path
    )
    contact = contact_sheet_track(
        repo,
        "fixture-release",
        font_path=FONT_PATH,
        force=True,
    )
    contact_path = Path(contact["contact_sheet"]["output_path"])
    first_contact = contact_path.read_bytes()
    repeated_contact = contact_sheet_track(
        repo,
        "fixture-release",
        font_path=FONT_PATH,
        force=True,
    )
    assert (
        Path(repeated_contact["contact_sheet"]["output_path"]).read_bytes()
        == first_contact
    )
    assert contact["contact_sheet"]["section_count"] == 2
    assert contact_path.name == "contact-sheet.png"
    rendered = render_track(
        repo,
        "fixture-release",
        font_path=FONT_PATH,
        draft=True,
        start_seconds=0.2,
        end_seconds=0.4,
        render_id="draft-1",
        force=True,
    )
    output = Path(rendered["render"]["output_path"])
    assert output.is_file()
    assert "assets/processed/video/fixture-artist--fixture-track/renders" in str(
        output
    )
    assert output.as_posix().endswith("/renders/drafts/draft-1.mp4")
    assert output.with_suffix(".render.json").is_file()
    artifact_index = json.loads(
        (
            repo
            / "assets/processed/video/fixture-artist--fixture-track/logs/artifacts.json"
        ).read_text()
    )
    assert {artifact["kind"] for artifact in artifact_index["artifacts"]} == {
        "alignment",
        "draft",
        "preview",
    }


def _write_library_actor(repo: Path, actor_id: str, name: str) -> None:
    directory = repo / "assets" / "source" / "video" / "actors"
    directory.mkdir(parents=True, exist_ok=True)
    document = {
        "version": 1,
        "actor": {
            "id": actor_id,
            "name": name,
            "kind": "spirogram",
            "components": [
                {
                    "id": "shape",
                    "role": "vocals",
                    "geometry": {
                        "family": "spirogram",
                        "fixed_radius": 180,
                        "moving_radius": 60,
                        "pen_offset": 100,
                    },
                    "color": "#ffcc00",
                }
            ],
        },
    }
    (directory / f"{actor_id}.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )


def _project_actors(project_path: Path) -> dict:
    value = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    return value["project"].get("visuals", {}).get("actors", {})


def test_prepare_seeds_branding_actors_from_library(tmp_path: Path) -> None:
    from mrp.video.actor_library import actor_revision, load_library_actor

    repo, _ = _write_repo(tmp_path)
    _write_library_actor(repo, "maricopa-records", "Maricopa Records")
    _write_library_actor(repo, "artist-fixture-artist", "Fixture Artist")

    prepared = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    actors = _project_actors(prepared.workspace.project_path)

    assert set(actors) == {"maricopa-records", "artist-fixture-artist"}
    # Each is pinned to its current library revision (parity with the admin).
    for actor_id in actors:
        expected = actor_revision(load_library_actor(repo, actor_id))
        assert actors[actor_id]["library_source"] == {
            "actor_id": actor_id,
            "revision": expected,
        }
        assert actors[actor_id]["character"] == "vocals"


def test_prepare_skips_missing_branding_actors(tmp_path: Path) -> None:
    repo, _ = _write_repo(tmp_path)
    _write_library_actor(repo, "maricopa-records", "Maricopa Records")
    # No artist-fixture-artist in the library.

    prepared = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    actors = _project_actors(prepared.workspace.project_path)
    assert set(actors) == {"maricopa-records"}


def test_prepare_without_branding_library_succeeds(tmp_path: Path) -> None:
    repo, _ = _write_repo(tmp_path)
    prepared = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    assert _project_actors(prepared.workspace.project_path) == {}


def test_reprepare_does_not_readd_deleted_branding(tmp_path: Path) -> None:
    repo, _ = _write_repo(tmp_path)
    _write_library_actor(repo, "maricopa-records", "Maricopa Records")
    _write_library_actor(repo, "artist-fixture-artist", "Fixture Artist")

    prepared = prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    project_path = prepared.workspace.project_path

    # Simulate the user deleting the label actor from the roster.
    value = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    del value["project"]["visuals"]["actors"]["maricopa-records"]
    project_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    # Re-prepare (not force): re-normalizes but must not re-add the deletion.
    prepare_track(repo, "fixture-release", font_path=FONT_PATH)
    actors = _project_actors(project_path)
    assert set(actors) == {"artist-fixture-artist"}


def test_generator_directions_do_not_become_sections_or_cues() -> None:
    """Suno brackets both song structure and performance notes.

    "[breathy male vocals]" is an instruction to the generator, never sung, and
    must not open a section or become a lyric cue.
    """
    from mrp.video.workspace import _lyrics_from_text

    lyrics, directions = _lyrics_from_text(
        "\n".join(
            [
                "[Intro]",
                "[clean electric guitar arpeggios]",
                "[Verse 1]",
                "[breathy male vocals]",
                "Moon low in the eastern sky",
                "[Chorus]",
                "[full band, high energy]",
                "Darkness takes the shadows",
                "[Verse 2]",
                "Wind lifts sand and leaves",
                "[Chorus]",
                "Darkness takes the shadows",
            ]
        ),
        instrumental=False,
    )

    # Ids stay distinct while the type groups them, so per-type scene styling
    # and transitions still match every chorus. The lyric-less [Intro] is kept
    # for alignment to size from the music before the first word.
    assert [section.id for section in lyrics.sections] == [
        "intro",
        "verse-1",
        "chorus",
        "verse-2",
        "chorus-2",
    ]
    assert [section.type for section in lyrics.sections] == [
        "intro",
        "verse",
        "chorus",
        "verse",
        "chorus",
    ]
    # No direction leaked into a sung cue.
    every_line = [line.text for section in lyrics.sections for line in section.lines]
    assert every_line == [
        "Moon low in the eastern sky",
        "Darkness takes the shadows",
        "Wind lifts sand and leaves",
        "Darkness takes the shadows",
    ]
    assert directions == (
        "[clean electric guitar arpeggios]",
        "[breathy male vocals]",
        "[full band, high energy]",
    )


def test_a_one_off_structure_label_can_be_declared_per_track() -> None:
    from mrp.video.workspace import _lyrics_from_text, track_structure_labels

    text = "[Chant]\nHey\n[Chorus]\nDarkness takes the shadows"

    # Unknown marker dropped, but its line is not lost: it lands in the default
    # opening verse rather than disappearing.
    without, dropped = _lyrics_from_text(text, instrumental=False)
    assert [section.id for section in without.sections] == ["verse", "chorus"]
    assert [line.text for line in without.sections[0].lines] == ["Hey"]
    assert dropped == ("[Chant]",)

    labels = track_structure_labels({"section_tags": ["Chant"]})
    with_tag, kept = _lyrics_from_text(text, instrumental=False, extra_labels=labels)
    assert [section.id for section in with_tag.sections] == ["chant", "chorus"]
    assert kept == ()


def test_a_piped_label_is_always_structure() -> None:
    """The escape hatch for a name the vocabulary does not know.

    The type still comes from the part before the pipe, as it always has.
    """
    from mrp.video.workspace import _lyrics_from_text

    lyrics, directions = _lyrics_from_text(
        "[Whisper Break|quiet]\nSoftly now", instrumental=False
    )

    assert directions == ()
    assert lyrics.sections[0].id == "whisper-break"
    assert lyrics.sections[0].type == "whisper-break"
    assert [line.text for line in lyrics.sections[0].lines] == ["Softly now"]


def test_an_empty_intro_or_outro_survives_but_an_empty_verse_does_not() -> None:
    """A structural marker with no sung line still earns a scene at the edges."""
    from mrp.video.workspace import _lyrics_from_text

    lyrics, directions = _lyrics_from_text(
        "\n".join(
            [
                "[Intro]",
                "[clean guitar arpeggios]",
                "[Verse 1]",
                "Moon low in the eastern sky",
                "[Bridge]",
                "[bass and drums only]",
                "[Outro]",
                "[feedback fade]",
            ]
        ),
        instrumental=False,
    )

    # Intro and outro are kept for alignment to size; the lyric-less bridge is
    # dropped, as it always was.
    assert [(section.id, len(section.lines)) for section in lyrics.sections] == [
        ("intro", 0),
        ("verse-1", 1),
        ("outro", 0),
    ]
    assert len(directions) == 3
