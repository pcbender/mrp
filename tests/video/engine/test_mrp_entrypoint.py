import json
import subprocess
import sys

from mrp.cli.main import main


def test_root_help_registers_video_without_loading_renderer() -> None:
    script = (
        "import sys; "
        "from mrp.cli.main import build_parser; "
        "help_text = build_parser().format_help(); "
        "assert 'mrp.video.cli' not in sys.modules; "
        "print(help_text)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "video" in result.stdout


def test_video_entrypoint_dispatches_to_renderer(capsys) -> None:
    result = main(["video", "presets", "--json"])

    assert result == 0
    catalog = json.loads(capsys.readouterr().out)
    assert catalog["mapping"]
    assert catalog["palette"]
