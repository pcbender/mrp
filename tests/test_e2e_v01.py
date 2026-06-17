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


def json_command(*args: str) -> dict:
    result = run_mrp("--json", *args)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def ensure_markers() -> None:
    staging = ROOT / "builds" / "local-staging"
    production = ROOT / "builds" / "local-production"
    staging.mkdir(parents=True, exist_ok=True)
    production.mkdir(parents=True, exist_ok=True)
    (staging / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")
    (production / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=production\n")


def test_v01_local_release_flow_end_to_end():
    ensure_markers()
    release = "circuiting"
    summary = {}

    inspect = json_command("inspect")
    assert inspect["status"] == "ok"

    validation = json_command("validate", "--release", release)
    summary["validation"] = validation["status"]

    build = json_command("build", "--release", release)
    build_id = build["build_id"]
    summary["build"] = build["status"]

    stage = json_command("stage", "--target", "local-staging", "--build", build_id)
    summary["stage"] = stage["status"]

    staging_verification = json_command("verify", "--target", "staging", "--release", release)
    summary["staging verification"] = staging_verification["status"]

    approval = json_command("approve", "--release", release, "--build", build_id)
    summary["approval"] = "recorded" if approval["status"] == "approved" else approval["status"]

    publish = json_command("publish", "--release", release, "--build", build_id)
    summary["publish"] = publish["status"]

    production_verification = json_command("verify", "--target", "production", "--release", release)
    summary["production verification"] = production_verification["status"]

    rollback = json_command("rollback", "--yes")
    summary["rollback"] = rollback["status"]

    rollback_verification = json_command("verify", "--target", "production", "--release", release)
    summary["rollback verification"] = rollback_verification["status"]

    assert summary == {
        "validation": "passed",
        "build": "passed",
        "stage": "passed",
        "staging verification": "passed",
        "approval": "recorded",
        "publish": "published",
        "production verification": "passed",
        "rollback": "rolled_back",
        "rollback verification": "passed",
    }
