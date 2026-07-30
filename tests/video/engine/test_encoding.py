import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
import soundfile as sf
import yaml
from PIL import Image
from typer.testing import CliRunner

from mrp.video.cards import blend_frames, render_card
from mrp.video.cli import app
from mrp.video.encoder import build_ffmpeg_command, plan_output_timeline
from mrp.video.project import CardConfig
from mrp.video.verification import (
    SpirophonicVerificationError,
    verify_with_render_manifest,
)
from tests.video.engine.test_renderer import FONT_PATH, _context

runner = CliRunner()


def _signal(sample_rate: int, duration: float) -> np.ndarray:
    times = np.arange(round(sample_rate * duration)) / sample_rate
    fade = np.minimum(1, np.minimum(times / 0.03, (duration - times) / 0.03))
    return np.asarray(
        0.3 * fade * np.sin(2 * np.pi * 220 * times),
        dtype=np.float32,
    )


def _write_video_project(root: Path) -> Path:
    duration = 0.6
    project = {
        "version": 1,
        "title": "Encoded Fixture",
        "audio": {
            "master": "audio/master.wav",
            "stems": {"vocals": "audio/vocals.wav"},
        },
        "lyrics": {
            "source": "lyrics.yaml",
            "aligned": "build/lyrics.aligned.yaml",
            "language": "en",
        },
        "cards": {
            "opening": {
                "file": "cards/opening.jpg",
                "duration": 0.2,
                "fade": 0.1,
            },
            "closing": {
                "file": "cards/closing.jpg",
                "duration": 0.2,
                "fade": 0.1,
            },
        },
        "video": {"width": 320, "height": 180, "fps": 10, "seed": 73},
        "encoding": {"preset": "ultrafast", "crf": 28, "threads": 1},
        "text": {"font": "assets/font.ttf", "size": 28},
        "analysis": {
            "sample_rate": 8000,
            "frame_length": 512,
            "hop_length": 128,
            "low_cutoff_hz": 200,
            "high_cutoff_hz": 1500,
            "attack_seconds": 0.02,
            "release_seconds": 0.1,
            "cache_dir": "build/test-analysis",
        },
    }
    cards = root / "cards"
    cards.mkdir()
    Image.new("RGB", (160, 90), (220, 24, 24)).save(
        cards / "opening.jpg",
        quality=95,
    )
    Image.new("RGB", (160, 90), (24, 48, 220)).save(
        cards / "closing.jpg",
        quality=95,
    )
    font = root / "assets" / "font.ttf"
    font.parent.mkdir()
    shutil.copyfile(FONT_PATH, font)
    (root / "lyrics.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sections": [
                    {
                        "id": "verse",
                        "type": "verse",
                        "label": "Verse",
                        "lines": [{"text": "Encoded lyric"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    aligned = root / "build" / "lyrics.aligned.yaml"
    aligned.parent.mkdir()
    aligned.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "source": "lyrics.yaml",
                "sections": [
                    {
                        "id": "verse",
                        "type": "verse",
                        "label": "Verse",
                        "start": 0,
                        "end": duration,
                        "lines": [
                            {
                                "text": "Encoded lyric",
                                "start": 0.1,
                                "end": 0.5,
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    audio = root / "audio"
    audio.mkdir()
    sf.write(audio / "master.wav", _signal(8000, duration), 8000)
    sf.write(audio / "vocals.wav", _signal(16000, duration), 16000)
    manifest = root / "project.yaml"
    manifest.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")
    return manifest


def _decode_audio(path: Path) -> np.ndarray:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32)


def test_cards_preserve_aspect_ratio_and_crossfade(tmp_path: Path) -> None:
    source = tmp_path / "wide.png"
    Image.new("RGB", (100, 50), (240, 20, 10)).save(source)
    contain = render_card(
        CardConfig(file=Path("wide.png"), duration=1, background="#000000"),
        source,
        width=100,
        height=100,
    )
    cover = render_card(
        CardConfig(file=Path("wide.png"), duration=1, fit="cover"),
        source,
        width=100,
        height=100,
    )

    assert tuple(contain[0, 0]) == (0, 0, 0)
    assert tuple(contain[50, 50]) == (240, 20, 10)
    assert tuple(cover[0, 0]) == (240, 20, 10)
    midpoint = blend_frames(
        np.zeros((1, 1, 3), dtype=np.uint8),
        np.full((1, 1, 3), 200, dtype=np.uint8),
        0.5,
    )
    assert tuple(midpoint[0, 0]) == (100, 100, 100)


def test_full_timeline_includes_cards_and_excerpt_omits_them() -> None:
    context = _context()

    full = plan_output_timeline(context)
    excerpt = plan_output_timeline(context, start_seconds=1, end_seconds=2)

    assert full.include_cards
    assert full.opening_frames == 10
    assert full.song_frames == 60
    assert full.closing_frames == 10
    assert full.total_frames == 80
    assert full.output_duration == 8
    assert full.audio_post_padding == pytest.approx(1)
    assert not excerpt.include_cards
    assert excerpt.opening_frames == 0
    assert excerpt.song_frames == 10
    assert excerpt.closing_frames == 0
    assert excerpt.source_audio_start == 1
    assert excerpt.source_audio_end == 2


def test_ffmpeg_command_maps_only_raw_video_and_master_audio(tmp_path: Path) -> None:
    context = _context()
    timeline = plan_output_timeline(context)
    master = tmp_path / "master.wav"
    output = tmp_path / "output.mp4"

    command = build_ffmpeg_command(
        context,
        timeline,
        master_path=master,
        output_path=output,
    )
    joined = " ".join(command)

    assert command.count("-i") == 2
    assert "pipe:0" in command
    assert str(master) in command
    assert command[command.index("-map") + 1] == "0:v:0"
    second_map = command.index("-map", command.index("-map") + 1)
    assert command[second_map + 1] == "[aout]"
    assert "atrim=start=0.000000000:end=6.000000000" in joined
    assert "adelay=1000:all=1" in joined
    assert "apad=pad_dur=1.000000000" in joined
    assert "+faststart" in command
    assert command[-1] == str(output)


@pytest.mark.video_ffmpeg
@pytest.mark.skipif(not FONT_PATH.is_file(), reason="target Ubuntu font unavailable")
def test_render_and_verify_cli_publish_master_only_timeline(tmp_path: Path) -> None:
    manifest = _write_video_project(tmp_path)
    output = tmp_path / "build" / "fixture.mp4"

    dry_run = runner.invoke(
        app,
        [
            "render",
            str(manifest),
            "--output",
            str(output),
            "--dry-run",
            "--json",
        ],
    )
    assert dry_run.exit_code == 0, dry_run.output
    dry_summary = json.loads(dry_run.stdout)
    assert dry_summary["frame_count"] == 10
    assert dry_summary["diagnostics"]["raw_stream_bytes"] == 10 * 320 * 180 * 3
    assert not output.exists()

    rendered = runner.invoke(
        app,
        ["render", str(manifest), "--output", str(output), "--json"],
    )

    assert rendered.exit_code == 0, rendered.output
    summary = json.loads(rendered.stdout)
    assert summary["verified"] is True
    assert summary["frame_count"] == 10
    assert summary["duration"] == pytest.approx(1, abs=0.1)
    assert summary["video_codec"] == "h264"
    assert summary["pixel_format"] == "yuv420p"
    assert summary["audio_codec"] == "aac"
    assert summary["audio_sample_rate"] == 48000
    assert summary["audio_channels"] == 2
    assert summary["performance"]["frames_per_second"] > 0
    assert summary["performance"]["realtime_factor"] > 0
    assert output.is_file()

    render_manifest = output.with_suffix(".render.json")
    payload = json.loads(render_manifest.read_text(encoding="utf-8"))
    assert payload["timeline"]["cards_included"] is True
    assert payload["timeline"]["opening_duration"] == pytest.approx(0.2)
    assert payload["timeline"]["closing_duration"] == pytest.approx(0.2)
    assert payload["output"]["sha256"]
    assert payload["output"]["metadata"]["stream_count"] == 2
    assert payload["output"]["metadata"]["faststart"] is True
    assert payload["artistic_presets"] == {
        "mapping": "balanced",
        "palette": "layer",
        "custom_palette": [],
    }
    # This project casts nothing, so the manifest records the scene as uncast
    # and carrying no traces. It used to be filled in with the deterministic
    # look, which put shapes in the render nobody had chosen.
    assert payload["casting"]["sections"]["verse"]["key"] == "uncast:empty"
    assert payload["casting"]["sections"]["verse"]["traces"] == []
    assert payload["performance"]["frames_per_second"] > 0
    assert "audio.master" in payload["inputs"]
    assert "audio.vocals" in payload["inputs"]
    assert payload["warnings"]

    report = verify_with_render_manifest(output)
    assert report.metadata.stream_count == 2
    verified = runner.invoke(app, ["verify", str(output), "--json"])
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.stdout)["valid"] is True

    original_manifest = render_manifest.read_text(encoding="utf-8")
    altered = json.loads(original_manifest)
    altered["output"]["sha256"] = "0" * 64
    render_manifest.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(SpirophonicVerificationError, match="hash does not match"):
        verify_with_render_manifest(output)
    render_manifest.write_text(original_manifest, encoding="utf-8")

    audio = _decode_audio(output)
    assert np.sqrt(np.mean(np.square(audio[:800]))) < 0.002
    assert np.sqrt(np.mean(np.square(audio[2400:4000]))) > 0.05
    assert np.sqrt(np.mean(np.square(audio[-800:]))) < 0.002

    capture = cv2.VideoCapture(str(output))
    frames: list[np.ndarray] = []
    while True:
        success, frame = capture.read()
        if not success:
            break
        frames.append(frame)
    capture.release()
    assert len(frames) == 10
    opening_mean = frames[0].mean(axis=(0, 1))
    closing_mean = frames[-1].mean(axis=(0, 1))
    assert opening_mean[2] > opening_mean[0] * 3
    assert closing_mean[0] > closing_mean[2] * 3

    excerpt = tmp_path / "build" / "excerpt.mp4"
    excerpt_result = runner.invoke(
        app,
        [
            "render",
            str(manifest),
            "--output",
            str(excerpt),
            "--from",
            "0.2",
            "--to",
            "0.4",
            "--json",
        ],
    )
    assert excerpt_result.exit_code == 0, excerpt_result.output
    excerpt_summary = json.loads(excerpt_result.stdout)
    assert excerpt_summary["cards_included"] is False
    assert excerpt_summary["frame_count"] == 2
    assert excerpt_summary["duration"] == pytest.approx(0.2, abs=0.1)

    refused = runner.invoke(
        app,
        ["render", str(manifest), "--output", str(output), "--json"],
    )
    assert refused.exit_code == 1
    assert "--force" in refused.output
