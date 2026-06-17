import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/home/mrose/website-migration/import-artifacts/maricoparecords")


def run_mrp(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def minimal_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    (repo / "reports" / "import").mkdir(parents=True)
    return repo


def test_import_site_generates_review_records_and_report(tmp_path):
    repo = minimal_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "import-site", "--source", str(SOURCE))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["summary"]["artist_candidates"] >= 1
    assert payload["summary"]["release_candidates"] >= 1
    assert payload["summary"]["asset_candidates"] >= 1
    assert (repo / payload["report_path"]).is_file()

    artists = yaml.safe_load((repo / "content/import-review/artists.yaml").read_text())
    releases = yaml.safe_load((repo / "content/import-review/releases.yaml").read_text())
    assert artists["candidates"][0]["artist"]["review_status"] == "needs_review"
    assert releases["candidates"][0]["release"]["status"] == "draft"


def test_import_site_does_not_modify_source_files(tmp_path):
    repo = minimal_repo(tmp_path)
    before = (SOURCE / "IMPORT_REPORT.md").stat().st_mtime_ns

    result = run_mrp("--repo", str(repo), "--json", "import-site", "--source", str(SOURCE))

    assert result.returncode == 0
    after = (SOURCE / "IMPORT_REPORT.md").stat().st_mtime_ns
    assert before == after
