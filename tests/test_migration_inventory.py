from pathlib import Path

from mrp.core.migration_inventory import DEFAULT_MIGRATION_SOURCE, migration_inventory


ROOT = Path(__file__).resolve().parents[1]
SOURCE = DEFAULT_MIGRATION_SOURCE


def test_migration_inventory_writes_report_and_known_counts(tmp_path):
    repo = tmp_path / "repo"

    result = migration_inventory(repo, SOURCE)

    assert result["status"] == "passed"
    assert result["command"] == "migration-inventory"
    assert result["summary"]["source_posts"] == 375
    assert result["summary"]["captured_pages"] == 52
    assert result["summary"]["captured_assets"] == 664
    assert result["summary"]["post_types"]["feedback"] == 136
    assert result["summary"]["post_types"]["product"] == 8
    assert result["summary"]["categories"]["excluded_feedback"] == 136
    assert result["summary"]["categories"]["excluded_commerce"] == 12
    assert result["summary"]["categories"]["blog_news_post"] == 3
    assert result["summary"]["route_categories"]["release"] >= 1
    assert result["summary"]["artist_routes"] >= 1
    assert result["summary"]["release_routes"] >= 1
    assert (repo / result["report_path"]).is_file()


def test_migration_inventory_exclusions_are_explicit(tmp_path):
    repo = tmp_path / "repo"

    result = migration_inventory(repo, SOURCE)

    commerce = result["exclusions"]["commerce"]
    feedback = result["exclusions"]["feedback"]
    assert commerce
    assert feedback
    assert all(item["category"] == "excluded_commerce" for item in commerce)
    assert all("WooCommerce" in item["reason"] for item in commerce)
    assert all(item["category"] == "excluded_feedback" for item in feedback)
    assert all("Historical feedback" in item["reason"] for item in feedback)


def test_migration_inventory_accepts_artifact_root(tmp_path):
    repo = tmp_path / "repo"
    artifact_root = SOURCE / "import-artifacts" / "maricoparecords"

    result = migration_inventory(repo, artifact_root)

    assert result["status"] == "passed"
    assert result["artifact_root"] == str(artifact_root)
    assert result["source"] == str(SOURCE)


def test_migration_inventory_does_not_modify_source_files(tmp_path):
    repo = tmp_path / "repo"
    source_file = SOURCE / "import-artifacts/maricoparecords/IMPORT_REPORT.md"
    before = source_file.stat().st_mtime_ns

    result = migration_inventory(repo, SOURCE)

    assert result["status"] == "passed"
    assert source_file.stat().st_mtime_ns == before
