import json
import shutil
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


def content_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "content", repo / "content")
    shutil.copytree(ROOT / "site" / "public" / "assets", repo / "site" / "public" / "assets")
    shutil.rmtree(repo / "site" / "public" / "assets" / "wp", ignore_errors=True)
    shutil.rmtree(repo / "content" / "clone", ignore_errors=True)
    (repo / "content" / "clone" / "pages").mkdir(parents=True)
    (repo / "content" / "clone" / "posts").mkdir(parents=True)
    (repo / "content" / "clone" / "assets").mkdir(parents=True)
    (repo / "reports" / "migration").mkdir(parents=True)
    (repo / "reports" / "validation").mkdir(parents=True)
    return repo


def fake_source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    artifact = source / "import-artifacts" / "maricoparecords"
    (source / "Assets").mkdir(parents=True)
    (source / "Assets" / "maricoparecords.WordPress.2026-06-17.xml").write_text("<rss><channel /></rss>")
    (artifact / "defined-skills" / "raw").mkdir(parents=True)
    (artifact / "defined-skills" / "raw" / "source-inventory.json").write_text("{}")
    (artifact / "defined-skills" / "raw" / "normalized-wordpress-content.json").write_text("{}")
    (artifact / "IMPORT_REPORT.md").write_text("# Import\n")
    (artifact / "live-capture").mkdir(parents=True)
    (artifact / "live-capture" / "capture-manifest.json").write_text(json.dumps({"pages": [], "assets": []}))

    asset_root = artifact / "live-capture" / "raw" / "assets" / "www.maricoparecords.com"
    (asset_root / "wp-content" / "uploads").mkdir(parents=True)
    (asset_root / "wp-content" / "themes" / "anima-plus").mkdir(parents=True)
    (asset_root / "wp-includes" / "js").mkdir(parents=True)
    (asset_root / "wp-content" / "uploads" / "pcbender.png").write_bytes(b"image")
    (asset_root / "wp-content" / "themes" / "anima-plus" / "style.css").write_text("body{}\n")
    (asset_root / "wp-includes" / "js" / "wp.js").write_text("window.wp = {};\n")

    page_root = artifact / "live-capture" / "raw" / "pages" / "www.maricoparecords.com"
    page_root.mkdir(parents=True)
    (page_root / "index.html").write_text(
        '<link href="/wp-content/themes/anima-plus/style.css" rel="stylesheet">'
        '<script src="/wp-includes/js/wp.js"></script>'
        '<img src="/wp-content/uploads/missing.png">',
    )
    return source


def write_clone_record(repo: Path) -> None:
    path = repo / "content" / "clone" / "pages" / "artists-pcbender.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "clone": {
                    "id": "artists-pcbender",
                    "kind": "artist_page",
                    "title": "PCBender",
                    "status": "review",
                    "route": {"canonical_path": "/artists/pcbender/", "aliases": []},
                    "source": {
                        "system": "wordpress",
                        "id": "791",
                        "post_type": "page",
                        "post_status": "publish",
                        "slug": "pcbender",
                        "link": "https://www.maricoparecords.com/artists/pcbender/",
                        "guid": None,
                        "captured_path": None,
                    },
                    "content_html": '<img src="https://www.maricoparecords.com/wp-content/uploads/pcbender.png">',
                    "excerpt": None,
                    "seo": {"title": "PCBender", "description": None},
                    "assets": [],
                    "notes": [],
                }
            },
            sort_keys=False,
        )
    )


def test_clone_assets_mirrors_referenced_wordpress_assets(tmp_path):
    repo = content_repo(tmp_path)
    source = fake_source(tmp_path)
    write_clone_record(repo)

    result = run_mrp("--repo", str(repo), "--json", "clone-assets", "--source", str(source))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "clone-assets"
    assert payload["status"] == "completed"
    assert payload["summary"]["referenced"] == 4
    assert payload["summary"]["copied"] == 3
    assert payload["summary"]["missing"] == 1
    assert (repo / "site/public/assets/wp/wp-content/uploads/pcbender.png").read_bytes() == b"image"
    assert (repo / "site/public/assets/wp/wp-content/themes/anima-plus/style.css").is_file()
    assert (repo / "site/public/assets/wp/wp-includes/js/wp.js").is_file()

    manifest = yaml.safe_load((repo / "content/clone/assets/manifest.yaml").read_text())
    assert len(manifest["clone_assets"]) == 4
    assert {asset["status"] for asset in manifest["clone_assets"]} == {"mirrored", "missing"}
    assert any(asset["type"] == "style" for asset in manifest["clone_assets"])
    assert any(asset["type"] == "script" for asset in manifest["clone_assets"])

    validation = run_mrp("--repo", str(repo), "--json", "validate")
    assert validation.returncode == 0
    assert json.loads(validation.stdout)["summary"]["clone_assets"] == 4


def test_clone_assets_is_idempotent(tmp_path):
    repo = content_repo(tmp_path)
    source = fake_source(tmp_path)
    write_clone_record(repo)

    first = run_mrp("--repo", str(repo), "--json", "clone-assets", "--source", str(source))
    second = run_mrp("--repo", str(repo), "--json", "clone-assets", "--source", str(source))

    assert first.returncode == 0
    assert second.returncode == 0
    payload = json.loads(second.stdout)
    assert payload["summary"]["copied"] == 0
    assert payload["summary"]["skipped_existing"] == 3


def test_clone_assets_missing_source_fails_cleanly(tmp_path):
    repo = content_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "clone-assets", "--source", str(tmp_path / "missing"))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "config"
    assert "Could not find website migration artifacts" in payload["message"]
    assert (repo / payload["report_path"]).is_file()
