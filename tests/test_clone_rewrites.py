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


def test_clone_rewrites_reports_static_url_review_metadata():
    result = run_mrp("--json", "clone-rewrites")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "clone-rewrites"
    assert payload["status"] == "completed"
    assert payload["summary"]["clone_records"] == 50
    assert payload["summary"]["local_references"] > 0
    assert payload["summary"]["wordpress_asset_references"] > 0
    assert payload["summary"]["external_references_preserved"] > 0
    assert payload["summary"]["unresolved_local_urls"] == len(payload["unresolved_local_urls"])
    assert payload["summary"]["missing_assets"] == len(payload["missing_assets"])
    assert "https://open.spotify.com" not in json.dumps(payload["unresolved_local_urls"])
    assert "https://music.apple.com" not in json.dumps(payload["unresolved_local_urls"])
    assert (ROOT / payload["report_path"]).is_file()
