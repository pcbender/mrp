import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_mrp(*args: str, site_out_root: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if site_out_root is not None:
        env["MRP_SITE_OUT_ROOT"] = str(site_out_root)
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_cli_runs_from_repo_root():
    result = run_mrp("inspect")

    assert result.returncode == 0
    assert "MRP repository inspection" in result.stdout
    assert "Deploy config: present" in result.stdout


def test_inspect_json_output_is_valid():
    result = run_mrp("--json", "inspect")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "inspect"
    assert payload["status"] == "ok"
    assert payload["repo"] == str(ROOT)
    assert payload["content"]["site"] == 1
    assert payload["content"]["artists"] >= 4
    assert payload["content"]["releases"] >= 32
    assert payload["content"]["assets"] >= 38
    assert payload["content"]["records"] >= 38
    assert payload["site_framework"]["detected"] is True
    assert payload["site_framework"]["name"] == "astro"


def test_json_output_is_valid_for_build_command(tmp_path):
    out_root = tmp_path / "site-out"
    result = run_mrp("--json", "build", site_out_root=out_root)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "build"
    assert payload["status"] == "passed"
    build_path = Path(payload["build_path"])
    assert build_path.is_absolute()
    assert out_root in build_path.parents


def test_unknown_command_fails_cleanly():
    result = run_mrp("unknown")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert "Traceback" not in result.stderr


def test_nested_release_create_command_is_registered(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    shutil.copytree(ROOT / "site" / "public" / "assets", repo / "site" / "public" / "assets")
    (repo / "reports" / "validation").mkdir(parents=True)

    result = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "release",
        "create",
        "--artist",
        "pcbender",
        "--title",
        "CLI Smoke Release",
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["command"] == "release create"
