from typer.testing import CliRunner

from mrp.video.cli import app

runner = CliRunner()


def test_help_lists_validate_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "align" in result.stdout
    assert "analyze" in result.stdout
    assert "frame" in result.stdout
    assert "frames" in result.stdout
    assert "presets" in result.stdout
    assert "render" in result.stdout
    assert "verify" in result.stdout
    assert "validate" in result.stdout
    assert "deterministic music videos" in result.stdout


def test_validate_reports_missing_manifest() -> None:
    result = runner.invoke(app, ["validate", "missing-project.yaml"])

    assert result.exit_code == 1
    assert "Project validation failed" in result.output
    assert "project manifest does not exist" in result.output
