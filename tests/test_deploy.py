import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def run_mrp(*args: str, cwd: Path = ROOT, site_out_root: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if site_out_root is not None:
        env["MRP_SITE_OUT_ROOT"] = str(site_out_root)
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def deployable_repo(tmp_path: Path, marker: bool = True) -> Path:
    repo = tmp_path / "repo"
    out_root = tmp_path / "site-out"
    build_id = "20260617T120000Z-site"
    build_path = out_root / "builds" / "staging" / build_id
    target_path = out_root / "staging"
    report_path = repo / "reports" / "build" / f"{build_id}.json"

    build_path.mkdir(parents=True)
    target_path.mkdir(parents=True)
    report_path.parent.mkdir(parents=True)
    (repo / "reports" / "deployment").mkdir(parents=True)
    (repo / "deploy").mkdir(parents=True)

    (build_path / "index.html").write_text("<html>MRP</html>\n")
    (build_path / "build-manifest.json").write_text(json.dumps({"build_id": build_id}) + "\n")
    report_path.write_text(
        json.dumps(
            {
                "command": "build",
                "status": "passed",
                "build_id": build_id,
                "build_path": str(build_path),
                "release": None,
            }
        )
        + "\n"
    )
    (repo / "deploy" / "targets.yaml").write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "local-staging": {
                        "type": "local",
                        "environment": "staging",
                        "path": "staging",
                        "require_marker": True,
                    }
                }
            },
            sort_keys=False,
        )
    )
    if marker:
        (target_path / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")
    return repo


def test_stage_local_target_copies_build_and_writes_report(tmp_path):
    repo = deployable_repo(tmp_path)
    out_root = tmp_path / "site-out"

    result = run_mrp("--repo", str(repo), "--json", "stage", "--target", "local-staging", site_out_root=out_root)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["target"] == "local-staging"
    assert payload["copied_files"] == 2
    assert (out_root / "staging/index.html").read_text() == "<html>MRP</html>\n"
    assert (repo / payload["report_path"]).is_file()


def test_stage_local_target_removes_stale_files_but_preserves_marker(tmp_path):
    repo = deployable_repo(tmp_path)
    out_root = tmp_path / "site-out"
    stale = out_root / "staging/old-route/index.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("<html>old</html>\n")

    result = run_mrp("--repo", str(repo), "--json", "stage", "--target", "local-staging", site_out_root=out_root)

    assert result.returncode == 0
    assert not stale.exists()
    assert (out_root / "staging/.allow-deploy").is_file()
    assert (out_root / "staging/index.html").is_file()


def test_stage_missing_marker_is_refused(tmp_path):
    repo = deployable_repo(tmp_path, marker=False)
    out_root = tmp_path / "site-out"

    result = run_mrp("--repo", str(repo), "--json", "stage", "--target", "local-staging", site_out_root=out_root)

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "safety"
    assert "Missing deploy marker" in payload["message"]
    assert not (out_root / "staging/index.html").exists()


def test_stage_dry_run_reports_plan_without_copying(tmp_path):
    repo = deployable_repo(tmp_path)
    out_root = tmp_path / "site-out"

    result = run_mrp("--repo", str(repo), "--json", "--dry-run", "stage", "--target", "local-staging", site_out_root=out_root)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "planned"
    assert payload["plan"]["file_count"] == 2
    assert not (out_root / "staging/index.html").exists()
    assert (repo / payload["report_path"]).is_file()


def test_stage_unknown_build_fails(tmp_path):
    repo = deployable_repo(tmp_path)
    out_root = tmp_path / "site-out"

    result = run_mrp("--repo", str(repo), "--json", "stage", "--build", "missing", site_out_root=out_root)

    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "build"


def test_stage_refuses_unknown_target_type(tmp_path):
    repo = deployable_repo(tmp_path)
    out_root = tmp_path / "site-out"
    targets = yaml.safe_load((repo / "deploy/targets.yaml").read_text())
    targets["targets"]["ftp-staging"] = {
        "type": "ftp",
        "environment": "staging",
        "path": "/remote/path",
    }
    (repo / "deploy/targets.yaml").write_text(yaml.safe_dump(targets, sort_keys=False))

    result = run_mrp("--repo", str(repo), "--json", "stage", "--target", "ftp-staging", site_out_root=out_root)

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "config"
    assert "Unsupported deploy target type" in payload["message"]
