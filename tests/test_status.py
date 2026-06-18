import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def site_out_root(repo: Path) -> Path:
    return repo.parent / "site-out"


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


def status_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    for name in ["validation", "build", "deployment", "verification", "approval", "rollback"]:
        (repo / "reports" / name).mkdir(parents=True, exist_ok=True)
    write_report(repo, "validation", "20260617T120000Z.json", {"command": "validate", "status": "passed", "release": "circuiting"})
    write_report(
        repo,
        "build",
        "20260617T120100Z-site.json",
        {"command": "build", "status": "passed", "build_id": "build-123", "release": "circuiting"},
    )
    write_report(
        repo,
        "deployment",
        "20260617T120200Z-local-staging-build-123.json",
        {"command": "stage", "status": "passed", "build_id": "build-123", "target": "local-staging", "release": "circuiting"},
    )
    write_report(
        repo,
        "deployment",
        "20260617T120300Z-publish-build-123.json",
        {"command": "publish", "status": "published", "build_id": "build-123", "target": "local-production", "release": "circuiting"},
    )
    write_report(
        repo,
        "verification",
        "20260617T120400Z-local-production.json",
        {"command": "verify", "status": "passed", "build_id": "build-123", "target": "local-production", "release": "circuiting"},
    )
    write_report(
        repo,
        "approval",
        "circuiting-20260617T120500Z.json",
        {"command": "approve", "status": "approved", "approval_id": "approval-123", "build_id": "build-123", "release": "circuiting"},
    )
    (site_out_root(repo) / "archive/production-20260617T120000Z").mkdir(parents=True)
    return repo


def write_report(repo: Path, kind: str, name: str, data) -> None:
    path = repo / "reports" / kind / name
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_status_human_output_is_useful(tmp_path):
    repo = status_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "status", "--release", "circuiting", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    assert "MRP status" in result.stdout
    assert "Release: circuiting (live)" in result.stdout
    assert "Rollback available: True" in result.stdout
    assert "approval: approved" in result.stdout


def test_status_json_reports_release_and_latest_state(tmp_path):
    repo = status_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "status", "--release", "circuiting", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["release"]["id"] == "circuiting"
    assert payload["latest"]["build"]["build_id"] == "build-123"
    assert payload["latest"]["staging_deployment"]["target"] == "local-staging"
    assert payload["latest"]["publish"]["status"] == "published"
    assert payload["rollback_available"] is True


def test_status_unknown_release_fails_cleanly(tmp_path):
    repo = status_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "status", "--release", "missing", site_out_root=site_out_root(repo))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["field"] == "release"
