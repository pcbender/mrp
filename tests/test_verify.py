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


def verified_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    target = repo / "builds" / "local-staging"
    shutil.copytree(ROOT / "content", repo / "content")
    (repo / "deploy").mkdir(parents=True)
    (repo / "reports" / "verification").mkdir(parents=True)
    target.mkdir(parents=True)

    (repo / "deploy" / "targets.yaml").write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "local-staging": {
                        "type": "local",
                        "environment": "staging",
                        "path": "builds/local-staging",
                        "require_marker": True,
                    }
                }
            },
            sort_keys=False,
        )
    )
    (target / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")
    write_file(target / "index.html", '<a href="/artists/pcbender/">PCBender</a>\n')
    write_file(target / "artists/index.html", '<a href="/artists/pcbender/">PCBender</a>\n')
    write_file(target / "artists/pcbender/index.html", '<a href="/releases/circuiting/">Circuiting</a>\n')
    write_file(target / "releases/index.html", '<a href="/releases/circuiting/">Circuiting</a>\n')
    write_file(target / "releases/circuiting/index.html", '<img src="/assets/releases/circuiting-cover.svg">\n')
    write_file(target / "assets/releases/circuiting-cover.svg", "<svg></svg>\n")
    write_file(target / "sitemap.xml", "<urlset></urlset>\n")
    write_file(target / "feed.xml", "<rss></rss>\n")
    return repo


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_verify_staging_passes_for_valid_local_target(tmp_path):
    repo = verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["target"] == "local-staging"
    assert payload["summary"]["errors"] == 0
    assert (repo / payload["report_path"]).is_file()


def test_verify_missing_release_page_fails(tmp_path):
    repo = verified_repo(tmp_path)
    (repo / "builds/local-staging/releases/circuiting/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("releases/circuiting/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_cover_image_fails(tmp_path):
    repo = verified_repo(tmp_path)
    (repo / "builds/local-staging/assets/releases/circuiting-cover.svg").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("assets/releases/circuiting-cover.svg" in error["message"] for error in payload["errors"])


def test_verify_placeholder_token_fails(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(repo / "builds/local-staging/about-us/index.html", "TODO\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "placeholder" for error in payload["errors"])
