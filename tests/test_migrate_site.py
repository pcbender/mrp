import json
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


def test_migrate_site_mutation_mode_is_reserved_for_later_packet(tmp_path):
    repo = tmp_path / "repo"

    result = run_mrp("--repo", str(repo), "--json", "migrate-site", "--source", str(SOURCE))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "config"
    assert "MRP-104" in payload["message"]
    assert (repo / payload["report_path"]).is_file()
