import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from mrp.core.migrate_site import copy_referenced_assets
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
    shutil.rmtree(repo / "site/public/assets/migrated", ignore_errors=True)

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
    artifact_report = repo / "migration/reports/unresolved-artifacts.json"
    assert artifact_report.is_file()
    assert payload["normalization"]["report_path"] == "migration/reports/unresolved-artifacts.json"
    assert payload["normalization"]["unresolved_count"] == 0
    migrated_page_text = (repo / "content/pages/music-licensing.yaml").read_text()
    assert "wp-block" not in migrated_page_text
    assert "stk-" not in migrated_page_text
    assert "wp:" not in migrated_page_text
    migrated_page = yaml.safe_load(migrated_page_text)["page"]
    assert migrated_page["content_markdown"]
    assert isinstance(migrated_page["sections"], list)
    assert isinstance(migrated_page["images"], list)
    assert isinstance(migrated_page["socials"], dict)
    assert payload["assets"]["referenced"] > 0
    assert payload["assets"]["copied"] > 0
    assert payload["assets"]["referenced"] < payload["planned_writes"]["assets"]
    assert payload["assets"]["manifest_records"] > 0
    assert all(item["source_url"] and item["page_references"] for item in payload["assets"]["missing"])
    assert all(item["bytes"] > item["threshold"] for item in payload["assets"]["oversized"])
    assert any((repo / item["path"]).is_file() for item in payload["assets"]["copied_files"])
    manifest = yaml.safe_load((repo / "content/assets/manifest.yaml").read_text())
    migrated_assets = [item for item in manifest["assets"] if item["id"].startswith("migrated-")]
    assert migrated_assets
    assert all((repo / item["path"]).is_file() for item in migrated_assets)
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
    assert payload["assets"]["copied"] == 0
    assert payload["assets"]["skipped_existing"] > 0
    assert (repo / payload["report_path"]).is_file()


def test_copy_referenced_assets_reports_missing_source_with_page_reference(tmp_path):
    repo = tmp_path / "repo"
    (repo / "content/pages").mkdir(parents=True)
    (repo / "content/assets").mkdir(parents=True)
    (repo / "content/pages/missing.yaml").write_text(
        yaml.safe_dump(
            {
                "page": {
                    "id": "missing",
                    "content_html": '<img src="https://www.maricoparecords.com/wp-content/uploads/missing.jpg">',
                }
            },
            sort_keys=False,
        )
    )
    source = tmp_path / "source/live-capture"
    source.mkdir(parents=True)
    capture_manifest = source / "capture-manifest.json"
    capture_manifest.write_text(json.dumps({"assets": []}) + "\n")
    result = copy_referenced_assets(
        repo,
        {
            "source_files": {"capture_manifest": str(capture_manifest)},
            "assets": [],
        },
    )

    assert result["copied"] == 0
    assert result["missing"] == [
        {
            "source_url": "https://www.maricoparecords.com/wp-content/uploads/missing.jpg",
            "page_references": ["content/pages/missing.yaml"],
            "reason": "Referenced asset was not found in the capture manifest.",
        }
    ]
    assert not (repo / "site/public/assets/migrated").exists()
