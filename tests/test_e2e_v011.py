import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/home/mrose/website-migration")


def run_mrp(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def json_command(*args: str) -> dict:
    result = run_mrp("--json", *args)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def ensure_staging_marker() -> None:
    staging = ROOT / "builds" / "local-staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")


def test_v011_full_site_staging_migration_end_to_end():
    ensure_staging_marker()

    migration = json_command("migrate-site", "--source", str(SOURCE))
    validation = json_command("validate")
    build = json_command("build")
    stage = json_command("stage", "--target", "local-staging", "--build", build["build_id"])
    verification = json_command("verify", "--target", "staging")

    report = {
        "command": "v0.1.1-full-site-e2e",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": str(SOURCE),
        "status": "passed",
        "steps": {
            "migration": migration["status"],
            "validation": validation["status"],
            "build": build["status"],
            "stage": stage["status"],
            "verification": verification["status"],
        },
        "summary": {
            "pages": validation["summary"]["pages"],
            "artists": validation["summary"]["artists"],
            "releases": validation["summary"]["releases"],
            "posts": validation["summary"]["posts"],
            "assets": migration["assets"]["manifest_records"],
            "redirects": migration["planned_writes"]["normalized_urls"],
            "exclusions": migration["summary"]["categories"]["excluded_commerce"]
            + migration["summary"]["categories"]["excluded_feedback"],
        },
        "warnings": {
            "missing_assets": migration["assets"]["missing"],
            "oversized_assets": migration["assets"]["oversized"],
            "unsupported_assets": migration["assets"]["unsupported"],
        },
        "failures": {
            "validation": validation["errors"],
            "verification": verification["errors"],
        },
        "reports": {
            "migration": migration["report_path"],
            "validation": validation["report_path"],
            "build": build["report_path"],
            "deployment": stage["report_path"],
            "verification": verification["report_path"],
        },
    }
    report_path = ROOT / "reports/migration/v011-full-site-e2e.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    assert migration["status"] == "completed"
    assert validation["status"] == "passed"
    assert build["status"] == "passed"
    assert stage["status"] == "passed"
    assert verification["status"] == "passed"
    assert verification["migration"]["enabled"] is True
    assert report["summary"]["pages"] >= 40
    assert report["summary"]["posts"] == 3
    assert report["summary"]["assets"] == 37
    assert report["summary"]["redirects"] == 52
    assert report["warnings"]["missing_assets"]
    assert not report["failures"]["validation"]
    assert not report["failures"]["verification"]
    assert report_path.is_file()
