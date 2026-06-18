import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def site_out_root(repo: Path) -> Path:
    return repo.parent / "site-out"


def staging_path(repo: Path) -> Path:
    return site_out_root(repo) / "staging"


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


def comparison_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    source = tmp_path / "source"
    target = staging_path(repo)
    page_root = source / "import-artifacts" / "maricoparecords" / "live-capture" / "raw" / "pages" / "www.maricoparecords.com"
    (source / "Assets").mkdir(parents=True)
    (source / "Assets" / "maricoparecords.WordPress.2026-06-17.xml").write_text("<rss><channel /></rss>")
    (source / "import-artifacts" / "maricoparecords" / "defined-skills" / "raw").mkdir(parents=True)
    (source / "import-artifacts" / "maricoparecords" / "defined-skills" / "raw" / "source-inventory.json").write_text("{}")
    (
        source
        / "import-artifacts"
        / "maricoparecords"
        / "defined-skills"
        / "raw"
        / "normalized-wordpress-content.json"
    ).write_text("{}")
    (source / "import-artifacts" / "maricoparecords" / "IMPORT_REPORT.md").write_text("# Import\n")
    (source / "import-artifacts" / "maricoparecords" / "live-capture" / "capture-manifest.json").parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    (source / "import-artifacts" / "maricoparecords" / "live-capture" / "capture-manifest.json").write_text(
        json.dumps({"pages": [], "assets": []})
    )
    routes = {
        "/": "Maricopa Records",
        "/artists/pcbender/": "mystique",
        "/artists/pcbender/circuiting/": "Circuiting is not just an album",
        "/licensing-custom-songs/music-licensing/": "Music Licensing",
        "/2025/02/26/the-future-of-ai-in-music/": "The Future of AI in Music",
    }
    for route, marker in routes.items():
        write_file(page_root / route_file(route), page_html(marker, "https://www.maricoparecords.com/wp-content/uploads/test.png"))
        write_file(target / route_file(route), page_html(marker, "/assets/wp/wp-content/uploads/test.png"))
    (repo / "deploy").mkdir(parents=True)
    (repo / "reports" / "comparison").mkdir(parents=True)
    (target / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")
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
    return repo, source


def route_file(route: str) -> str:
    return "index.html" if route == "/" else f"{route.strip('/')}/index.html"


def page_html(marker: str, asset: str) -> str:
    return f"""<!doctype html>
<html>
<head><title>{marker} | Maricopa Records</title></head>
<body>
  <main class="wp-site-blocks">
    <div class="wp-block-group stk-block">
      <h1>{marker}</h1>
      <img src="{asset}">
    </div>
  </main>
</body>
</html>
"""


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_clone_compare_reports_representative_page_matches(tmp_path):
    repo, source = comparison_repo(tmp_path)

    result = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "clone-compare",
        "--source",
        str(source),
        "--target",
        "local-staging",
        site_out_root=site_out_root(repo),
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["summary"]["routes_compared"] == 5
    assert payload["summary"]["failures"] == 0
    assert all(item["checks"]["markers"]["missing"] == [] for item in payload["comparisons"])
    assert (repo / payload["report_path"]).is_file()


def test_clone_compare_missing_marker_fails(tmp_path):
    repo, source = comparison_repo(tmp_path)
    target_file = staging_path(repo) / "artists/pcbender/index.html"
    target_file.write_text(target_file.read_text().replace("mystique", "PCBender"))

    result = run_mrp(
        "--repo",
        str(repo),
        "--json",
        "clone-compare",
        "--source",
        str(source),
        "--target",
        "local-staging",
        site_out_root=site_out_root(repo),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "marker" for error in payload["failures"])
