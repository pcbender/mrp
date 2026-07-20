from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mrp.video.cli import app
from mrp.video.encoder import SpirophonicCancelledError, plan_output_timeline
from mrp.video.pipeline import diagnose_render, render_project_video
from mrp.video.renderer import build_render_context
from tests.video.engine.test_choreography import _aligned_sections, _analysis_bundle
from tests.video.engine.test_encoding import _write_video_project
from tests.video.engine.test_renderer import FONT_PATH, _project

runner = CliRunner()


def test_long_song_planning_is_constant_memory_and_diagnostic() -> None:
    duration = 3 * 60 * 60
    analysis = replace(_analysis_bundle(), duration=duration)
    project = _project()
    video = project.video.model_copy(
        update={"width": 1920, "height": 1080, "fps": 30}
    )
    project = project.model_copy(update={"video": video})
    context = build_render_context(
        project,
        analysis,
        _aligned_sections(),
        root=FONT_PATH.parent,
    )

    timeline = plan_output_timeline(context)
    diagnostics = diagnose_render(context, timeline)

    assert timeline.song_frames == 324_000
    assert timeline.total_frames == 324_060
    assert diagnostics.raw_stream_bytes == 324_060 * 1920 * 1080 * 3
    assert any("long render" in warning for warning in diagnostics.warnings)
    assert any("piped, not stored" in warning for warning in diagnostics.warnings)


@pytest.mark.skipif(not FONT_PATH.is_file(), reason="target Ubuntu font unavailable")
def test_cancellation_removes_partial_outputs(tmp_path) -> None:
    manifest = _write_video_project(tmp_path)
    output = tmp_path / "build" / "cancelled.mp4"
    checks = 0
    progress: list[str] = []

    def cancel_after_two_frames() -> bool:
        nonlocal checks
        checks += 1
        return checks > 2

    with pytest.raises(SpirophonicCancelledError, match="frame 3"):
        render_project_video(
            manifest,
            output,
            progress=progress.append,
            cancel_check=cancel_after_two_frames,
        )

    assert not output.exists()
    assert not output.with_suffix(".render.json").exists()
    assert not list(output.parent.glob(".*cancelled*.tmp*"))
    assert any(message.startswith("Render plan:") for message in progress)
    assert any("Encoded frame 1" in message for message in progress)


@pytest.mark.parametrize(
    ("relative_path", "diagnostic"),
    [
        ("cards/opening.jpg", "cannot load card image"),
        ("assets/font.ttf", "cannot load lyric font"),
    ],
)
def test_dry_run_rejects_unusable_visual_assets(
    tmp_path: Path,
    relative_path: str,
    diagnostic: str,
) -> None:
    root = tmp_path / relative_path.replace("/", "-")
    root.mkdir()
    manifest = _write_video_project(root)
    (root / relative_path).write_bytes(b"not a usable visual asset")
    output = root / "build" / "should-not-exist.mp4"

    result = runner.invoke(
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

    assert result.exit_code == 1
    assert diagnostic in result.output
    assert not output.exists()
