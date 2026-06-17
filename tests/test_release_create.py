import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def run_mrp(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    shutil.copytree(ROOT / "site" / "public" / "assets", repo / "site" / "public" / "assets")
    (repo / "reports" / "validation").mkdir(parents=True)
    return repo


def test_release_create_single_writes_valid_draft_manifest(tmp_path):
    repo = content_repo(tmp_path)

    result = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "release",
        "create",
        "--artist",
        "pcbender",
        "--title",
        "Signal Path",
        "--type",
        "single",
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "created"
    assert payload["slug"] == "signal-path"
    assert (repo / "content/releases/signal-path.yaml").is_file()
    assert (repo / "assets/releases/signal-path/.gitkeep").is_file()
    assert payload["validation_report_path"].startswith("reports/validation/")

    release = yaml.safe_load((repo / "content/releases/signal-path.yaml").read_text())["release"]
    assert release["model"] == "song"
    assert release["release_type"] == "single"
    assert release["status"] == "draft"
    assert release["automation"]["allow_auto_publish"] is False


def test_release_create_ep_adds_template_tracks(tmp_path):
    repo = content_repo(tmp_path)

    result = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "release",
        "create",
        "--artist",
        "pcbender",
        "--title",
        "Two Signals",
        "--type",
        "ep",
    )

    assert result.returncode == 0
    release = yaml.safe_load((repo / "content/releases/two-signals.yaml").read_text())["release"]
    assert release["model"] == "album"
    assert release["release_type"] == "ep"
    assert len(release["tracks"]) == 2
    assert release["tracks"][0]["slug"] == "track-1"


def test_release_create_refuses_overwrite(tmp_path):
    repo = content_repo(tmp_path)

    first = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "release",
        "create",
        "--artist",
        "pcbender",
        "--title",
        "Signal Path",
    )
    second = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "release",
        "create",
        "--artist",
        "pcbender",
        "--title",
        "Signal Path",
    )

    assert first.returncode == 0
    assert second.returncode == 2
    payload = json.loads(second.stdout)
    assert payload["status"] == "failed"
    assert "already exists" in payload["message"]
