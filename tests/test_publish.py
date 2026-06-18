import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


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


def publishable_repo(tmp_path: Path, approval: bool = True, marker: bool = True) -> Path:
    repo = tmp_path / "repo"
    out_root = site_out_root(repo)
    build_id = "build-123"
    build = out_root / "builds" / "staging" / build_id
    production = out_root / "prod"
    for path in [
        repo / "content" / "artists",
        repo / "content" / "releases",
        repo / "deploy",
        repo / "reports" / "approval",
        repo / "reports" / "build",
        repo / "reports" / "deployment",
        repo / "reports" / "verification",
        production,
        build,
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
                "status": "approved",
                "cover_image": "site/public/assets/releases/circuiting-cover.svg",
            }
        },
    )
    write_site(build)
    write_json(
        repo / "reports" / "build" / f"{build_id}.json",
        {
            "command": "build",
            "status": "passed",
            "build_id": build_id,
            "build_path": str(build),
            "release": "circuiting",
        },
    )
    if approval:
        write_json(
            repo / "reports" / "approval" / "circuiting-20260617T120000Z.json",
            {
                "command": "approve",
                "status": "approved",
                "approval_id": "circuiting-20260617T120000Z",
                "build_id": build_id,
                "release": "circuiting",
                "mode": "human",
            },
        )
    (repo / "deploy" / "targets.yaml").write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "local-production": {
                        "type": "local",
                        "environment": "production",
                        "path": "prod",
                        "require_marker": True,
                    }
                }
            },
            sort_keys=False,
        )
    )
    if marker:
        (production / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=production\n")
    return repo


def write_site(root: Path) -> None:
    write_file(root / "index.html", '<a href="/artists/pcbender/">PCBender</a>\n')
    write_file(root / "artists/pcbender/index.html", '<a href="/releases/circuiting/">Circuiting</a>\n')
    write_file(root / "releases/circuiting/index.html", '<img src="/assets/releases/circuiting-cover.svg">\n')
    write_file(root / "assets/releases/circuiting-cover.svg", "<svg></svg>\n")
    write_file(root / "sitemap.xml", "<urlset></urlset>\n")
    write_file(root / "feed.xml", "<rss></rss>\n")
    write_json(root / "build-manifest.json", {"build_id": "build-123"})


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def test_publish_refuses_unapproved_build(tmp_path):
    repo = publishable_repo(tmp_path, approval=False)

    result = run_mrp("--repo", str(repo), "--json", "publish", "--release", "circuiting", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["field"] == "approval"


def test_publish_refuses_missing_production_marker(tmp_path):
    repo = publishable_repo(tmp_path, marker=False)

    result = run_mrp("--repo", str(repo), "--json", "publish", "--release", "circuiting", site_out_root=site_out_root(repo))

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["errors"][0]["field"] == "safety"


def test_publish_deploys_verifies_and_marks_release_live(tmp_path):
    repo = publishable_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "publish", "--release", "circuiting", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "published"
    assert payload["build_id"] == "build-123"
    assert (site_out_root(repo) / "prod/index.html").is_file()
    assert (repo / payload["deployment_report_path"]).is_file()
    assert (repo / payload["verification_report_path"]).is_file()
    assert (repo / payload["report_path"]).is_file()

    release = json.loads((repo / "content/releases/circuiting.json").read_text())
    assert release["release"]["status"] == "live"
