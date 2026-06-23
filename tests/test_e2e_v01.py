import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


def ensure_markers(site_out_root: Path) -> None:
    staging = site_out_root / "staging"
    production = site_out_root / "prod"
    staging.mkdir(parents=True, exist_ok=True)
    production.mkdir(parents=True, exist_ok=True)
    (staging / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")
    (production / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=production\n")


def test_v01_local_release_flow_end_to_end(tmp_path, isolated_repo):
    site_out_root = tmp_path / "site-out"
    ensure_markers(site_out_root)
    release = "circuiting"
    summary = {}

    inspect = json_command("inspect", repo=isolated_repo, site_out_root=site_out_root)
    assert inspect["status"] == "ok"

    validation = json_command("validate", "--release", release, repo=isolated_repo, site_out_root=site_out_root)
    summary["validation"] = validation["status"]

    build = json_command("build", "--release", release, repo=isolated_repo, site_out_root=site_out_root)
    build_id = build["build_id"]
    summary["build"] = build["status"]

    stage = json_command("stage", "--target", "local-staging", "--build", build_id, repo=isolated_repo, site_out_root=site_out_root)
    summary["stage"] = stage["status"]

    staging_verification = json_command("verify", "--target", "staging", "--release", release, repo=isolated_repo, site_out_root=site_out_root)
    summary["staging verification"] = staging_verification["status"]

    approval = json_command("approve", "--release", release, "--build", build_id, repo=isolated_repo, site_out_root=site_out_root)
    summary["approval"] = "recorded" if approval["status"] == "approved" else approval["status"]

    publish = json_command("publish", "--release", release, "--build", build_id, repo=isolated_repo, site_out_root=site_out_root)
    summary["publish"] = publish["status"]

    production_verification = json_command("verify", "--target", "production", "--release", release, repo=isolated_repo, site_out_root=site_out_root)
    summary["production verification"] = production_verification["status"]

    rollback = json_command("rollback", "--to", build_id, "--yes", repo=isolated_repo, site_out_root=site_out_root)
    summary["rollback"] = rollback["status"]

    rollback_verification = json_command("verify", "--target", "production", "--release", release, repo=isolated_repo, site_out_root=site_out_root)
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
