import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_mrp(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def repo_with_verification(tmp_path: Path, status: str = "passed") -> Path:
    repo = tmp_path / "repo"
    (repo / "reports" / "verification").mkdir(parents=True)
    (repo / "reports" / "approval").mkdir(parents=True)
    (repo / "reports" / "verification" / "20260617T120000Z-local-staging.json").write_text(
        json.dumps(
            {
                "command": "verify",
                "status": status,
                "target": "local-staging",
                "release": None,
                "build_id": "build-123",
                "generated_at": "2026-06-17T12:00:00Z",
            }
        )
        + "\n"
    )
    return repo


def test_approve_without_verification_fails(tmp_path):
    repo = tmp_path / "repo"

    result = run_mrp("--repo", str(repo), "--json", "approve", "--release", "circuiting")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["field"] == "verification"
    assert (repo / payload["report_path"]).is_file()


def test_approve_verified_release_writes_record(tmp_path):
    repo = repo_with_verification(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "approve", "--release", "circuiting")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "approved"
    assert payload["release"] == "circuiting"
    assert payload["build_id"] == "build-123"
    assert payload["mode"] == "human"
    assert payload["verification_report_path"].endswith("20260617T120000Z-local-staging.json")
    assert (repo / payload["report_path"]).is_file()


def test_approve_build_must_match_latest_verified_build(tmp_path):
    repo = repo_with_verification(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "approve", "--build", "other-build")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["field"] == "build"


def test_status_reads_latest_approval(tmp_path):
    repo = repo_with_verification(tmp_path)
    approval = run_mrp("--repo", str(repo), "--json", "approve", "--build", "build-123")
    approval_payload = json.loads(approval.stdout)

    result = run_mrp("--repo", str(repo), "--json", "status")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["latest"]["approval"]["approval_id"] == approval_payload["approval_id"]
    assert payload["latest"]["approval"]["build_id"] == "build-123"
