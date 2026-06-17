import json
import shutil
import subprocess
import sys
from pathlib import Path

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
    (repo / "reports" / "migration").mkdir(parents=True)
    (repo / "reports" / "validation").mkdir(parents=True)
    return repo


def test_migrate_site_dry_run_reports_planned_writes_without_content_mutation(tmp_path):
    repo = tmp_path / "repo"

    result = run_mrp("--repo", str(repo), "--json", "--dry-run", "migrate-site", "--source", str(SOURCE))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "migrate-site"
    assert payload["status"] == "planned"
    assert payload["stage"] == "dry_run"
    assert payload["planned_writes"]["pages"] == 48
    assert payload["planned_writes"]["posts"] == 3
    assert payload["planned_writes"]["artist_records"] == 4
    assert payload["planned_writes"]["release_records"] == 33
    assert payload["planned_writes"]["assets"] == 594
    assert payload["exclusions"]["commerce"] == 12
    assert payload["exclusions"]["feedback"] == 136
    assert (repo / payload["report_path"]).is_file()
    assert not (repo / "content").exists()
    assert not (repo / "site/public/assets/migrated").exists()


def test_migrate_site_missing_source_fails_cleanly(tmp_path):
    repo = tmp_path / "repo"
    missing_source = tmp_path / "missing-source"

    result = run_mrp("--repo", str(repo), "--json", "--dry-run", "migrate-site", "--source", str(missing_source))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "config"
    assert "Could not find website migration artifacts" in payload["message"]
    assert (repo / payload["report_path"]).is_file()


def test_migrate_site_generates_staging_content_records(tmp_path):
    repo = content_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "migrate-site", "--source", str(SOURCE))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["stage"] == "content_generation"
    assert (repo / payload["report_path"]).is_file()
    assert (repo / "content/pages/music-licensing.yaml").is_file()
    assert (repo / "content/posts/the-future-of-ai-in-music.yaml").is_file()
    assert (repo / "content/artists/4castle.yaml").is_file()
    assert (repo / "content/releases/distance-not-safety.yaml").is_file()
    assert (repo / "content/redirects.yaml").is_file()
    assert any(item["path"] == "content/artists/pcbender.yaml" for item in payload["skipped"])

    validation = run_mrp("--repo", str(repo), "--json", "validate")
    assert validation.returncode == 0
    validation_payload = json.loads(validation.stdout)
    assert validation_payload["summary"]["pages"] >= 1
    assert validation_payload["summary"]["posts"] == 3


def test_migrate_site_is_idempotent_and_does_not_overwrite(tmp_path):
    repo = content_repo(tmp_path)

    first = run_mrp("--repo", str(repo), "--json", "migrate-site", "--source", str(SOURCE))
    second = run_mrp("--repo", str(repo), "--json", "migrate-site", "--source", str(SOURCE))

    assert first.returncode == 0
    assert second.returncode == 0
    payload = json.loads(second.stdout)
    assert payload["status"] == "completed"
    assert payload["skipped"]
    assert any(item["reason"] == "Existing record was not overwritten." for item in payload["skipped"])
    assert (repo / payload["report_path"]).is_file()
