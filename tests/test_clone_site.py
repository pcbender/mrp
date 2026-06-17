import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE


ROOT = Path(__file__).resolve().parents[1]
SOURCE = DEFAULT_MIGRATION_SOURCE


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
    shutil.rmtree(repo / "content" / "clone", ignore_errors=True)
    (repo / "content" / "clone" / "pages").mkdir(parents=True)
    (repo / "content" / "clone" / "posts").mkdir(parents=True)
    (repo / "content" / "clone" / "assets").mkdir(parents=True)
    (repo / "reports" / "migration").mkdir(parents=True)
    (repo / "reports" / "validation").mkdir(parents=True)
    return repo


def test_clone_site_generates_wxr_clone_records(tmp_path):
    repo = content_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "clone-site", "--source", str(SOURCE))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "clone-site"
    assert payload["status"] == "completed"
    assert payload["summary"]["renderable_records"] == 51
    assert payload["summary"]["pages"] == 48
    assert payload["summary"]["posts"] == 3
    assert payload["summary"]["created"] == 51
    assert payload["summary"]["skipped"] == 0
    assert (repo / payload["report_path"]).is_file()

    pcbender = yaml.safe_load((repo / "content/clone/pages/artists-pcbender.yaml").read_text())
    assert pcbender["clone"]["kind"] == "artist_page"
    assert pcbender["clone"]["route"]["canonical_path"] == "/artists/pcbender/"
    assert "mystique" in pcbender["clone"]["content_html"]
    assert "wp-block-stackable-column" in pcbender["clone"]["content_html"]

    first_release = repo / "content/clone/pages/artists-4castle-here-comes-the-rain.yaml"
    second_release = repo / "content/clone/pages/artists-stab-here-comes-the-rain.yaml"
    assert first_release.is_file()
    assert second_release.is_file()

    post = repo / "content/clone/posts/2025-02-26-the-future-of-ai-in-music.yaml"
    assert yaml.safe_load(post.read_text())["clone"]["kind"] == "blog_post"

    validation = run_mrp("--repo", str(repo), "--json", "validate")
    assert validation.returncode == 0
    validation_payload = json.loads(validation.stdout)
    assert validation_payload["summary"]["clone_pages"] == 48
    assert validation_payload["summary"]["clone_posts"] == 3


def test_clone_site_records_capture_aliases(tmp_path):
    repo = content_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "clone-site", "--source", str(SOURCE))

    assert result.returncode == 0
    contact = yaml.safe_load((repo / "content/clone/pages/contact.yaml").read_text())
    assert "/contact" in contact["clone"]["route"]["aliases"]
    assert "/Contact/" in contact["clone"]["route"]["aliases"]
    assert "/Contact" in contact["clone"]["route"]["aliases"]
    assert contact["clone"]["source"]["captured_path"] == "raw/pages/www.maricoparecords.com/contact/index.html"


def test_clone_site_is_idempotent_and_preserves_existing_records(tmp_path):
    repo = content_repo(tmp_path)

    first = run_mrp("--repo", str(repo), "--json", "clone-site", "--source", str(SOURCE))
    second = run_mrp("--repo", str(repo), "--json", "clone-site", "--source", str(SOURCE))

    assert first.returncode == 0
    assert second.returncode == 0
    payload = json.loads(second.stdout)
    assert payload["summary"]["created"] == 0
    assert payload["summary"]["skipped"] == 51
    assert all(item["reason"] == "Existing clone record was not overwritten." for item in payload["skipped"])


def test_clone_site_regenerate_overwrites_existing_records(tmp_path):
    repo = content_repo(tmp_path)
    result = run_mrp("--repo", str(repo), "--json", "clone-site", "--source", str(SOURCE))
    assert result.returncode == 0
    target = repo / "content/clone/pages/artists-pcbender.yaml"
    target.write_text("clone:\n  id: artists-pcbender\n")

    regenerated = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "clone-site",
        "--source",
        str(SOURCE),
        "--regenerate",
    )

    assert regenerated.returncode == 0
    payload = json.loads(regenerated.stdout)
    assert payload["summary"]["overwritten"] == 51
    assert "mystique" in yaml.safe_load(target.read_text())["clone"]["content_html"]


def test_clone_site_missing_source_fails_cleanly(tmp_path):
    repo = content_repo(tmp_path)
    missing_source = tmp_path / "missing"

    result = run_mrp("--repo", str(repo), "--json", "clone-site", "--source", str(missing_source))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "config"
    assert "Could not find website migration artifacts" in payload["message"]
    assert (repo / payload["report_path"]).is_file()
