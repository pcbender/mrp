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


def verified_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    target = repo / "builds" / "local-staging"
    shutil.copytree(ROOT / "content", repo / "content")
    for name in ["artists", "releases", "pages", "posts"]:
        shutil.rmtree(repo / "content" / name)
        (repo / "content" / name).mkdir()
    shutil.copy2(ROOT / "content/artists/pcbender.json", repo / "content/artists/pcbender.json")
    shutil.copy2(ROOT / "content/releases/circuiting.json", repo / "content/releases/circuiting.json")
    (repo / "deploy").mkdir(parents=True)
    (repo / "reports" / "verification").mkdir(parents=True)
    target.mkdir(parents=True)

    (repo / "deploy" / "targets.yaml").write_text(
        yaml.safe_dump(
            {
                "targets": {
                    "local-staging": {
                        "type": "local",
                        "environment": "staging",
                        "path": "builds/local-staging",
                        "require_marker": True,
                    }
                }
            },
            sort_keys=False,
        )
    )
    (target / ".allow-deploy").write_text("MARICOPA_RECORDS_DEPLOY_TARGET=staging\n")
    write_file(target / "index.html", '<a href="/artists/pcbender/">PCBender</a>\n')
    write_file(target / "artists/index.html", '<a href="/artists/pcbender/">PCBender</a>\n')
    write_file(target / "artists/pcbender/index.html", '<a href="/releases/circuiting/">Circuiting</a>\n')
    write_file(target / "releases/index.html", '<a href="/releases/circuiting/">Circuiting</a>\n')
    write_file(target / "releases/circuiting/index.html", '<img src="/assets/releases/circuiting-cover.svg">\n')
    write_file(target / "assets/releases/circuiting-cover.svg", "<svg></svg>\n")
    write_file(target / "sitemap.xml", "<urlset></urlset>\n")
    write_file(target / "feed.xml", "<rss></rss>\n")
    return repo


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_verify_staging_passes_for_valid_local_target(tmp_path):
    repo = verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["target"] == "local-staging"
    assert payload["summary"]["errors"] == 0
    assert (repo / payload["report_path"]).is_file()


def test_verify_missing_release_page_fails(tmp_path):
    repo = verified_repo(tmp_path)
    (repo / "builds/local-staging/releases/circuiting/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("releases/circuiting/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_cover_image_fails(tmp_path):
    repo = verified_repo(tmp_path)
    (repo / "builds/local-staging/assets/releases/circuiting-cover.svg").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("assets/releases/circuiting-cover.svg" in error["message"] for error in payload["errors"])


def test_verify_placeholder_token_fails(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(repo / "builds/local-staging/about-us/index.html", "TODO\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "placeholder" for error in payload["errors"])


def test_verify_ignores_placeholder_tokens_in_mirrored_wordpress_assets(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(repo / "builds/local-staging/assets/wp/wp-content/themes/anima-plus/shortcodes.js", "/* TODO upstream */\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"


def test_verify_ignores_protocol_relative_external_links(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(repo / "builds/local-staging/about-us/index.html", '<link rel="stylesheet" href="//fonts.googleapis.com/css?family=Raleway">')

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"


def migrated_verified_repo(tmp_path: Path) -> Path:
    repo = verified_repo(tmp_path)
    write_file(
        repo / "content/pages/music.yaml",
        yaml.safe_dump(
            {
                "page": {
                    "id": "music",
                    "slug": "music",
                    "title": "Music",
                    "normalized_path": "/music/",
                    "content_html": "<p>Music</p>",
                }
            },
            sort_keys=False,
        ),
    )
    write_file(
        repo / "content/posts/news.yaml",
        yaml.safe_dump(
            {
                "post": {
                    "id": "news",
                    "slug": "news",
                    "title": "News",
                    "normalized_path": "/news/",
                    "content_html": "<p>News</p>",
                }
            },
            sort_keys=False,
        ),
    )
    write_file(
        repo / "content/redirects.yaml",
        yaml.safe_dump(
            {
                "redirects": [
                    {
                        "source_path": "/2025/02/26/news/",
                        "normalized_path": "/2025/02/26/news/",
                        "status": "normalized",
                    }
                ]
            },
            sort_keys=False,
        ),
    )
    write_file(
        repo / "content/assets/manifest.yaml",
        yaml.safe_dump(
            {
                "assets": [
                    {
                        "id": "migrated-cover",
                        "path": "site/public/assets/migrated/cover.jpg",
                        "type": "image",
                        "usage": ["migrated_content"],
                        "required": True,
                        "alt": None,
                    }
                ]
            },
            sort_keys=False,
        ),
    )
    write_file(repo / "builds/local-staging/music/index.html", "<p>Music</p>\n")
    write_file(repo / "builds/local-staging/news/index.html", "<p>News</p>\n")
    write_file(repo / "builds/local-staging/2025/02/26/news/index.html", "<p>News alias</p>\n")
    write_file(repo / "builds/local-staging/assets/migrated/cover.jpg", "image\n")
    return repo


def test_verify_migration_surface_passes_for_routes_assets_and_aliases(tmp_path):
    repo = migrated_verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["migration"]["enabled"] is True
    assert payload["migration"]["pages"] == 1
    assert payload["migration"]["posts"] == 1
    assert payload["migration"]["routes_checked"] == 3
    assert payload["migration"]["asset_records_checked"] == 1


def test_verify_missing_migrated_route_fails(tmp_path):
    repo = migrated_verified_repo(tmp_path)
    (repo / "builds/local-staging/music/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("music/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_migrated_asset_fails(tmp_path):
    repo = migrated_verified_repo(tmp_path)
    (repo / "builds/local-staging/assets/migrated/cover.jpg").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("assets/migrated/cover.jpg" in error["message"] for error in payload["errors"])


def test_verify_excluded_migration_path_fails(tmp_path):
    repo = migrated_verified_repo(tmp_path)
    write_file(repo / "builds/local-staging/cart/index.html", "<p>Cart</p>\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "migration.excluded_path" for error in payload["errors"])
