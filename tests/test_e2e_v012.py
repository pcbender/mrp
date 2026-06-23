import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/home/mrose/website-migration")


def run_mrp(*args: str, repo: Path, site_out_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MRP_SITE_OUT_ROOT"] = str(site_out_root)
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", "--repo", str(repo), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def json_command(*args: str, repo: Path, site_out_root: Path) -> dict:
    result = run_mrp("--json", *args, repo=repo, site_out_root=site_out_root)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def ensure_staging_marker(site_out_root: Path) -> None:
    staging = site_out_root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")


def test_v012_wxr_static_clone_end_to_end(tmp_path, isolated_repo):
    site_out_root = tmp_path / "site-out"
    ensure_staging_marker(site_out_root)

    clone_site = json_command("clone-site", "--source", str(SOURCE), "--regenerate", repo=isolated_repo, site_out_root=site_out_root)
    clone_assets = json_command("clone-assets", "--source", str(SOURCE), repo=isolated_repo, site_out_root=site_out_root)
    clone_head = json_command("clone-head", "--source", str(SOURCE), repo=isolated_repo, site_out_root=site_out_root)
    clone_rewrites = json_command("clone-rewrites", repo=isolated_repo, site_out_root=site_out_root)
    validation = json_command("validate", repo=isolated_repo, site_out_root=site_out_root)
    build = json_command("build", repo=isolated_repo, site_out_root=site_out_root)
    stage = json_command("stage", "--target", "local-staging", "--build", build["build_id"], repo=isolated_repo, site_out_root=site_out_root)
    verification = json_command("verify", "--target", "local-staging", repo=isolated_repo, site_out_root=site_out_root)
    comparison = json_command("clone-compare", "--target", "local-staging", "--source", str(SOURCE), repo=isolated_repo, site_out_root=site_out_root)

    report = {
        "command": "v0.1.2-wxr-static-clone-e2e",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": str(SOURCE),
        "status": "passed",
        "steps": {
            "clone_site": clone_site["status"],
            "clone_assets": clone_assets["status"],
            "clone_head": clone_head["status"],
            "clone_rewrites": clone_rewrites["status"],
            "validation": validation["status"],
            "build": build["status"],
            "stage": stage["status"],
            "verification": verification["status"],
            "comparison": comparison["status"],
        },
        "summary": {
            "clone_pages": validation["summary"]["clone_pages"],
            "clone_posts": validation["summary"]["clone_posts"],
            "artists": validation["summary"]["artists"],
            "releases": validation["summary"]["releases"],
            "mirrored_assets": clone_assets["summary"]["mirrored"],
            "missing_asset_review_items": clone_assets["summary"]["missing"],
            "unresolved_local_urls": clone_rewrites["summary"]["unresolved_local_urls"],
            "verification_clone_routes": verification["clone"]["routes_checked"],
            "verification_rendered_wp_asset_refs": verification["clone"]["rendered_wp_asset_refs_checked"],
            "comparison_routes": comparison["summary"]["routes_compared"],
            "comparison_warnings": comparison["summary"]["warnings"],
            "excluded_paths": verification["clone"]["excluded_paths_checked"],
        },
        "warnings": {
            "missing_assets": clone_assets["missing"],
            "oversized_assets": clone_assets["oversized"],
            "unsupported_assets": clone_assets["unsupported"],
            "rewrite_missing_assets": clone_rewrites["missing_assets"],
            "comparison": comparison["warnings"],
        },
        "failures": {
            "validation": validation["errors"],
            "verification": verification["errors"],
            "comparison": comparison["failures"],
        },
        "reports": {
            "clone_site": clone_site["report_path"],
            "clone_assets": clone_assets["report_path"],
            "clone_head": clone_head["report_path"],
            "clone_rewrites": clone_rewrites["report_path"],
            "validation": validation["report_path"],
            "build": build["report_path"],
            "deployment": stage["report_path"],
            "verification": verification["report_path"],
            "comparison": comparison["report_path"],
        },
    }
    report_path = isolated_repo / "reports/migration/v012-wxr-static-clone-e2e.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    assert clone_site["status"] == "completed"
    assert clone_assets["status"] == "completed"
    assert clone_head["status"] == "completed"
    assert clone_rewrites["status"] == "completed"
    assert validation["status"] == "passed"
    assert build["status"] == "passed"
    assert stage["status"] == "passed"
    assert verification["status"] == "passed"
    assert comparison["status"] == "completed"
    assert report["summary"]["clone_pages"] == 47
    assert report["summary"]["clone_posts"] == 3
    assert report["summary"]["verification_clone_routes"] == 50
    assert report["summary"]["unresolved_local_urls"] == 0
    assert report["summary"]["comparison_routes"] == 5
    assert not report["failures"]["validation"]
    assert not report["failures"]["verification"]
    assert not report["failures"]["comparison"]
    assert report_path.is_file()
