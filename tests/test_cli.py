import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_mrp(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_runs_from_repo_root():
    result = run_mrp("inspect")

    assert result.returncode == 0
    assert "MRP repository inspection" in result.stdout
    assert "Warnings:" in result.stdout


def test_inspect_json_output_is_valid():
    result = run_mrp("--json", "inspect")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "inspect"
    assert payload["status"] == "ok"
    assert payload["repo"] == str(ROOT)
    assert payload["content"]["site"] == 1
    assert payload["content"]["artists"] == 0
    assert payload["site_framework"]["detected"] is False


def test_json_output_is_valid_for_placeholder_command():
    result = run_mrp("--json", "validate")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "validate"
    assert payload["status"] == "not_implemented"


def test_unknown_command_fails_cleanly():
    result = run_mrp("unknown")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert "Traceback" not in result.stderr


def test_nested_release_create_command_is_registered():
    result = run_mrp("--json", "release", "create", "--artist", "pcbender", "--title", "Circuiting")

    assert result.returncode == 0
    assert json.loads(result.stdout)["command"] == "release create"
