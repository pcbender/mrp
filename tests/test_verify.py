import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def site_out_root(repo: Path) -> Path:
    return repo.parent / "site-out"


def staging_path(repo: Path) -> Path:
    return site_out_root(repo) / "staging"


def staged_cover_path(repo: Path, release_id: str = "circuiting") -> Path:
    for extension in ("json", "yaml", "yml"):
        path = repo / "content" / "releases" / f"{release_id}.{extension}"
        if not path.exists():
            continue
        data = json.loads(path.read_text()) if extension == "json" else yaml.safe_load(path.read_text())
        cover = data["release"]["cover_image"]
        return staging_path(repo) / cover.removeprefix("site/public/")
    raise AssertionError(f"Missing fixture release: {release_id}")


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


def verified_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    target = staging_path(repo)
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
                        "path": "staging",
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
    cover_path = staged_cover_path(repo)
    cover_url = f"/{cover_path.relative_to(target).as_posix()}"
    write_file(target / "releases/circuiting/index.html", f'<img src="{cover_url}">\n')
    write_file(cover_path, "image\n")
    write_file(target / "sitemap.xml", "<urlset></urlset>\n")
    write_file(target / "feed.xml", "<rss></rss>\n")
    return repo


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_verify_staging_passes_for_valid_local_target(tmp_path):
    repo = verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["target"] == "local-staging"
    assert payload["summary"]["errors"] == 0
    assert (repo / payload["report_path"]).is_file()


def test_verify_missing_release_page_fails(tmp_path):
    repo = verified_repo(tmp_path)
    (staging_path(repo) / "releases/circuiting/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("releases/circuiting/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_cover_image_fails(tmp_path):
    repo = verified_repo(tmp_path)
    cover_path = staged_cover_path(repo)
    cover_path.unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    expected = cover_path.relative_to(staging_path(repo)).as_posix()
    assert any(expected in error["message"] for error in payload["errors"])


def test_verify_placeholder_token_fails(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(staging_path(repo) / "about-us/index.html", "TODO\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "placeholder" for error in payload["errors"])


def test_verify_ignores_placeholder_tokens_in_mirrored_wordpress_assets(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(staging_path(repo) / "assets/wp/wp-content/themes/anima-plus/shortcodes.js", "/* TODO upstream */\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"


def test_verify_ignores_protocol_relative_external_links(tmp_path):
    repo = verified_repo(tmp_path)
    write_file(staging_path(repo) / "about-us/index.html", '<link rel="stylesheet" href="//fonts.googleapis.com/css?family=Raleway">')

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

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
    write_file(staging_path(repo) / "music/index.html", "<p>Music</p>\n")
    write_file(staging_path(repo) / "news/index.html", "<p>News</p>\n")
    write_file(staging_path(repo) / "2025/02/26/news/index.html", "<p>News alias</p>\n")
    write_file(staging_path(repo) / "assets/migrated/cover.jpg", "image\n")
    return repo


def test_verify_migration_surface_passes_for_routes_assets_and_aliases(tmp_path):
    repo = migrated_verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

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
    (staging_path(repo) / "music/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("music/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_migrated_asset_fails(tmp_path):
    repo = migrated_verified_repo(tmp_path)
    (staging_path(repo) / "assets/migrated/cover.jpg").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("assets/migrated/cover.jpg" in error["message"] for error in payload["errors"])


def test_verify_excluded_migration_path_fails(tmp_path):
    repo = migrated_verified_repo(tmp_path)
    write_file(staging_path(repo) / "cart/index.html", "<p>Cart</p>\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "migration.excluded_path" for error in payload["errors"])


def clone_verified_repo(tmp_path: Path) -> Path:
    repo = verified_repo(tmp_path)
    pages_dir = repo / "content" / "clone" / "pages"
    posts_dir = repo / "content" / "clone" / "posts"
    assets_dir = repo / "content" / "clone" / "assets"
    shutil.rmtree(pages_dir, ignore_errors=True)
    shutil.rmtree(posts_dir, ignore_errors=True)
    shutil.rmtree(assets_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True)
    posts_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    write_file(
        pages_dir / "artists-pcbender.yaml",
        yaml.safe_dump(
            {
                "clone": {
                    "id": "artists-pcbender",
                    "kind": "artist_page",
                    "title": "PCBender",
                    "route": {"canonical_path": "/artists/pcbender/", "aliases": []},
                    "content_html": "<p>mystique</p>",
                }
            },
            sort_keys=False,
        ),
    )
    write_file(
        pages_dir / "artists-pcbender-circuiting.yaml",
        yaml.safe_dump(
            {
                "clone": {
                    "id": "artists-pcbender-circuiting",
                    "kind": "release_page",
                    "title": "Circuiting",
                    "route": {"canonical_path": "/artists/pcbender/circuiting/", "aliases": []},
                    "content_html": "<p>Circuiting is not just an album</p>",
                }
            },
            sort_keys=False,
        ),
    )
    write_file(
        assets_dir / "manifest.yaml",
        yaml.safe_dump(
            {
                "clone_assets": [
                    {
                        "id": "wp-pcbender",
                        "source_url": "https://www.maricoparecords.com/wp-content/uploads/pcbender.png",
                        "local_path": "site/public/assets/wp/wp-content/uploads/pcbender.png",
                        "status": "mirrored",
                        "required": True,
                    }
                ]
            },
            sort_keys=False,
        ),
    )
    write_file(
        staging_path(repo) / "artists/pcbender/index.html",
        '<article class="wp-clone-content" data-clone-kind="artist_page">mystique<img src="/assets/wp/wp-content/uploads/pcbender.png"></article>',
    )
    write_file(
        staging_path(repo) / "artists/pcbender/circuiting/index.html",
        '<article class="wp-clone-content" data-clone-kind="release_page">Circuiting is not just an album</article>',
    )
    write_file(staging_path(repo) / "assets/wp/wp-content/uploads/pcbender.png", "image\n")
    return repo


def test_verify_clone_surface_passes_for_routes_assets_and_markers(tmp_path):
    repo = clone_verified_repo(tmp_path)

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "passed"
    assert payload["clone"]["enabled"] is True
    assert payload["clone"]["pages"] == 2
    assert payload["clone"]["posts"] == 0
    assert payload["clone"]["routes_checked"] == 2
    assert payload["clone"]["asset_records_checked"] == 1
    assert payload["clone"]["rendered_wp_asset_refs_checked"] == 1
    assert payload["clone"]["known_markers_checked"] == 2


def test_verify_missing_clone_route_fails(tmp_path):
    repo = clone_verified_repo(tmp_path)
    (staging_path(repo) / "artists/pcbender/circuiting/index.html").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any("artists/pcbender/circuiting/index.html" in error["message"] for error in payload["errors"])


def test_verify_missing_rendered_clone_asset_fails(tmp_path):
    repo = clone_verified_repo(tmp_path)
    (staging_path(repo) / "assets/wp/wp-content/uploads/pcbender.png").unlink()

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "clone.asset" for error in payload["errors"])


def test_verify_missing_clone_marker_fails(tmp_path):
    repo = clone_verified_repo(tmp_path)
    write_file(
        staging_path(repo) / "artists/pcbender/index.html",
        '<article class="wp-clone-content" data-clone-kind="artist_page">PCBender</article>',
    )

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "clone.marker" for error in payload["errors"])


def test_verify_excluded_clone_path_fails(tmp_path):
    repo = clone_verified_repo(tmp_path)
    write_file(staging_path(repo) / "checkout/index.html", "<p>Checkout</p>\n")

    result = run_mrp("--repo", str(repo), "--json", "verify", "--target", "staging", site_out_root=site_out_root(repo))

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert any(error["field"] == "clone.excluded_path" for error in payload["errors"])
