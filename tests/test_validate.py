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


def write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def minimal_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    (repo / "reports" / "validation").mkdir(parents=True)
    return repo


def test_validate_current_repo_writes_json_report():
    result = run_mrp("--json", "validate")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["report_path"].startswith("reports/validation/")
    assert (ROOT / payload["report_path"]).is_file()


def test_validate_release_filter_unknown_release_fails(tmp_path):
    repo = minimal_repo(tmp_path)
    result = run_mrp("--repo", str(repo), "--json", "validate", "--release", "missing")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["field"] == "release"


def test_missing_artist_reference_fails(tmp_path):
    repo = minimal_repo(tmp_path)
    release = yaml.safe_load((ROOT / "tests/fixtures/content/valid/release-song.yaml").read_text())
    release["release"]["artist_id"] = "missing-artist"
    write_yaml(repo / "content/releases/circuiting.yaml", release)

    result = run_mrp("--repo", str(repo), "--json", "validate")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(error["field"] == "release.artist_id" for error in payload["errors"])


def test_missing_cover_image_fails_for_publishable_release(tmp_path):
    repo = minimal_repo(tmp_path)
    artist = yaml.safe_load((ROOT / "tests/fixtures/content/valid/artist.yaml").read_text())
    release = yaml.safe_load((ROOT / "tests/fixtures/content/valid/release-song.yaml").read_text())
    release["release"]["status"] = "approved"
    write_yaml(repo / "content/artists/pcbender.yaml", artist)
    write_yaml(repo / "content/releases/circuiting.yaml", release)

    result = run_mrp("--repo", str(repo), "--json", "validate", "--release", "circuiting")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(error["field"] == "release.cover_image" for error in payload["errors"])
