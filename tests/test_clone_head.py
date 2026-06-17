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
    (repo / "reports" / "migration").mkdir(parents=True)
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
    page_root = artifact / "live-capture" / "raw" / "pages" / "www.maricoparecords.com"
    (page_root / "artists" / "pcbender").mkdir(parents=True)
    (page_root / "index.html").write_text(page_html("/wp-content/themes/anima-plus/style.css", "/wp-includes/js/wp.js"))
    (page_root / "artists" / "pcbender" / "index.html").write_text(
        page_html("/wp-content/themes/anima-plus/style.css", "/wp-includes/js/wp.js", page_css="/wp-content/plugins/page.css")
    )
    return source


def page_html(shared_css: str, shared_js: str, page_css: str | None = None) -> str:
    page_link = f'<link rel="stylesheet" href="{page_css}">' if page_css else ""
    return f"""<!doctype html>
<html>
<head>
  <link rel="stylesheet" id="theme-css" href="{shared_css}" media="all">
  <link rel="preload" href="/wp-content/themes/anima-plus/fonts/font.woff2" as="font">
  {page_link}
  <script src="{shared_js}" id="wp-js"></script>
  <script src="https://www.google-analytics.com/analytics.js"></script>
  <style>.wp-block-test {{ color: red; }}</style>
</head>
<body></body>
</html>
"""


def test_clone_head_extracts_and_rewrites_dependencies(tmp_path):
    repo = content_repo(tmp_path)
    source = fake_source(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "clone-head", "--source", str(source))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["command"] == "clone-head"
    assert payload["status"] == "completed"
    assert payload["summary"]["pages"] == 2
    assert payload["summary"]["shared_stylesheets"] == 1
    assert payload["summary"]["shared_scripts"] == 1
    assert payload["summary"]["shared_preloads"] == 1
    assert payload["summary"]["excluded_external"] == 2

    manifest = yaml.safe_load((repo / "content/clone/head-manifest.yaml").read_text())["clone_head"]
    assert manifest["shared"]["stylesheets"][0]["local_path"] == "/assets/wp/wp-content/themes/anima-plus/style.css"
    assert manifest["shared"]["scripts"][0]["local_path"] == "/assets/wp/wp-includes/js/wp.js"
    assert manifest["shared"]["preloads"][0]["local_path"] == "/assets/wp/wp-content/themes/anima-plus/fonts/font.woff2"
    pcbender = next(page for page in manifest["pages"] if page["canonical_path"] == "/artists/pcbender/")
    assert any(item["local_path"] == "/assets/wp/wp-content/plugins/page.css" for item in pcbender["stylesheets"])
    assert pcbender["inline_styles"][0]["content"] == ".wp-block-test { color: red; }"


def test_clone_head_missing_source_fails_cleanly(tmp_path):
    repo = content_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "clone-head", "--source", str(tmp_path / "missing"))

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["stage"] == "config"
    assert "Could not find website migration artifacts" in payload["message"]
    assert (repo / payload["report_path"]).is_file()
