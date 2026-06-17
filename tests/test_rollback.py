import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def run_mrp(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mrp.cli.main", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def rollback_repo(tmp_path: Path, marker: bool = True) -> Path:
    repo = tmp_path / "repo"
    for path in [
        repo / "content" / "artists",
        repo / "content" / "releases",
        repo / "deploy",
        repo / "reports" / "rollback",
        repo / "reports" / "verification",
        repo / "reports" / "deployment",
        repo / "builds" / "local-production",
        repo / "builds" / "staging" / "build-123",
        repo / "builds" / "archive" / "production-20260617T120000Z",
    ]:
        path.mkdir(parents=True)

    write_json(
        repo / "content/artists/pcbender.json",
        {"artist": {"id": "pcbender", "name": "PCBender", "visibility": "public"}},
    )
    write_json(
        repo / "content/releases/circuiting.json",
        {
            "release": {
                "id": "circuiting",
                "slug": "circuiting",
                "title": "Circuiting",
                "artist_id": "pcbender",
                "status": "live",
                "cover_image": "site/public/assets/releases/circuiting-cover.svg",
            }
        },
    )
    write_targets(repo)
    write_site(repo / "builds/staging/build-123", "build")
    write_site(repo / "builds/archive/production-20260617T120000Z", "archive")
    write_site(repo / "builds/local-production", "current")
    if marker:
        (repo / "builds/local-production/.allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=production\n")
    return repo


def write_targets(repo: Path) -> None:
    (repo / "deploy/targets.yaml").write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "local-production": {
                        "type": "local",
                        "environment": "production",
                        "path": "builds/local-production",
                        "require_marker": True,
                    }
                }
            },
            sort_keys=False,
        )
    )


def write_site(root: Path, label: str) -> None:
    write_file(root / "index.html", f'<a href="/artists/pcbender/">{label}</a>\n')
    write_file(root / "artists/pcbender/index.html", '<a href="/releases/circuiting/">Circuiting</a>\n')
    write_file(root / "releases/circuiting/index.html", '<img src="/assets/releases/circuiting-cover.svg">\n')
    write_file(root / "assets/releases/circuiting-cover.svg", "<svg></svg>\n")
    write_file(root / "sitemap.xml", "<urlset></urlset>\n")
    write_file(root / "feed.xml", "<rss></rss>\n")
    write_json(root / "build-manifest.json", {"label": label})


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_rollback_requires_confirmation(tmp_path):
    repo = rollback_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "rollback", "--to", "build-123")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "confirmation_required"
    assert "current" in (repo / "builds/local-production/index.html").read_text()


def test_rollback_to_build_restores_and_verifies(tmp_path):
    repo = rollback_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "rollback", "--to", "build-123", "--yes")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "rolled_back"
    assert payload["candidate"]["build_id"] == "build-123"
    assert "build" in (repo / "builds/local-production/index.html").read_text()
    assert (repo / payload["verification_report_path"]).is_file()
    assert (repo / payload["report_path"]).is_file()


def test_rollback_without_to_uses_latest_archive(tmp_path):
    repo = rollback_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "rollback", "--yes")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "rolled_back"
    assert payload["candidate"]["kind"] == "archive"
    assert "archive" in (repo / "builds/local-production/index.html").read_text()


def test_rollback_refuses_missing_marker(tmp_path):
    repo = rollback_repo(tmp_path, marker=False)

    result = run_mrp("--repo", str(repo), "--json", "rollback", "--to", "build-123", "--yes")

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["field"] == "safety"
